
import numpy as np
from numba import cuda
import accelerate.cuda.blas as cublas
import accelerate.cuda.sorting as sorting
import numba
from numba import float32, guvectorize
import math
from timeit import default_timer as timer


# ----------------------------------------------------------------------------------------------------------------------
# Functions relating to calculating the high dimensional space distances, sorting them and picking the 3 x perplexity
#  closer ones

@guvectorize([(float32[:, :], float32[:])], '(m,k)->(m)', nopython=True)
def _create_dot_product(a, dots_a):
    for i in np.arange(a.shape[0]):
        dots_a[i] = np.dot(a[i, :], a[i, :])


@cuda.jit
def _sums_of_dots_gpu(dots_a, dots_b, s_o_dots):
    a_index = cuda.threadIdx.x + cuda.blockDim.x * cuda.blockIdx.x

    if a_index < dots_a.shape[0]:
        for b_index in range(dots_b.shape[0]):
            s_o_dots[a_index, b_index] = dots_a[a_index] + dots_b[b_index]


def _calculate_distances_on_gpu(a, b, distances_on_gpu, verbose=False):
    m = a.shape[0]
    n = b.shape[0]
    k = a.shape[1]

    # calculate the inner product of each row for both matrices
    s1 = timer()
    dots_a = _create_dot_product(a)
    dots_b = _create_dot_product(b)
    e1 = timer()
    dot_time = e1 - s1
    if verbose:
        print("Making the dot products Time:", "%.3f" % dot_time, "s")

    # calculate the ||a||^2 + ||b||^2 sum of dot products matrix (a.a + b.b) on the gpu and save on the gpu_temp matrix
    s2 = timer()
    ddots_a = cuda.to_device(np.asfortranarray(dots_a))
    ddots_b = cuda.to_device(np.asfortranarray(dots_b))

    threads_per_block = 512
    blocks_per_grid = math.ceil(ddots_a.shape[0] / threads_per_block)
    _sums_of_dots_gpu[blocks_per_grid, threads_per_block](ddots_a, ddots_b, distances_on_gpu)
    numba.cuda.synchronize()

    e2 = timer()
    s_o_dot_time = e2 - s2
    if verbose:
        print("Summing the dot products on the GPU Time:", "%.3f" % s_o_dot_time, "s")

    # calculate the -2<a,b> cross dot products matrix and do the sum (||a||^2 + ||b||^2) -2<a,b>
    s3 = timer()
    da = cuda.to_device(np.asfortranarray(a))
    db = cuda.to_device(np.asfortranarray(b))
    blas = cublas.Blas()
    blas.gemm('N', 'T', m, n, k, -2.0, da, db, 1.0, distances_on_gpu)
    numba.cuda.synchronize()

    e3 = timer()
    time_gemm = e3 - s3
    if verbose:
        print("cuBLAS gemm Time:", "%.3f" % time_gemm, "s")


def _sort_distances_get_knns(num_of_neighbours, distances_on_gpu, start_index, verbose=False):

    m = distances_on_gpu.shape[0]
    n = distances_on_gpu.shape[1]

    s = timer()

    radix_sort = sorting.RadixSort(maxcount=n, dtype=np.float32)
    selected_sorted_distances = np.empty((m, num_of_neighbours))
    selected_sorted_indices = np.empty((m, num_of_neighbours))
    for i in np.arange(m):
        values = np.array(np.arange(n) + start_index, dtype=np.float32)
        values_on_gpu = cuda.to_device(values)
        radix_sort.sort(keys=distances_on_gpu[i], vals=values_on_gpu)
        selected_sorted_distances[i, :] = distances_on_gpu[i, :num_of_neighbours].copy_to_host()
        selected_sorted_indices[i, :] = values_on_gpu[:num_of_neighbours].copy_to_host()

    e = timer()
    sort_time = e - s
    if verbose:
        print("Sorting Time:", "%.3f" % sort_time, "s")

    return selected_sorted_indices, selected_sorted_distances


def _segment_sort_distances_get_knns(num_of_neighbours, distances_on_gpu, start_index, number_of_sorts=100,
                                     verbose=False):

    m = distances_on_gpu.shape[0]
    n = distances_on_gpu.shape[1]
    k = num_of_neighbours + 1

    selected_sorted_distances = np.empty((m, num_of_neighbours))
    selected_sorted_indices = np.empty((m, num_of_neighbours))

    s = timer()
    p = np.append(np.arange(0, m, int(m / number_of_sorts)), m)
    for i in np.arange(1, p.shape[0]):
        delta_m = p[i] - p[i - 1]
        keys = np.ascontiguousarray(distances_on_gpu.copy_to_host()[p[i - 1]:p[i], :].reshape(n * delta_m))
        values = np.ascontiguousarray(np.tile(np.arange(n) + start_index, (delta_m, 1)).reshape(n * delta_m))
        segments = np.ascontiguousarray(np.arange(0, n * delta_m, n)[1:] + start_index)
        sorting.segmented_sort(keys=keys, vals=values, segments=segments)
        keys = np.reshape(keys, (delta_m, n))[:, :k]
        values = np.reshape(values, (delta_m, n))[:, :k]
        selected_sorted_distances[p[i - 1]:p[i], :] = keys[:, 1:]  # throw away the dist to self
        selected_sorted_indices[p[i - 1]:p[i], :] = values[:, 1:]
        if verbose:
            print('     Sorted ' + str(i) + ' of ' + str(p.shape[0]) + ' segments of this iteration')
    e = timer()
    sort_time = e - s
    print("SORTING TIME:", "%.3f" % sort_time, "s")

    return selected_sorted_indices, selected_sorted_distances


def calculate_knn_distances_close_on_probe(template_features_sorted, indices_of_first_and_second_matrices,
                                           perplexity=100, verbose=True):

    start = timer()

    indices_of_first_matrices = indices_of_first_and_second_matrices[0]
    indices_of_second_matrices = indices_of_first_and_second_matrices[1]

    num_of_neighbours = perplexity * 3
    selected_sorted_indices = np.empty((template_features_sorted.shape[0], num_of_neighbours))
    selected_sorted_distances = np.empty((template_features_sorted.shape[0], num_of_neighbours))
    for matrix_index in np.arange(indices_of_first_matrices.shape[0]):
        first_matrix = np.array(template_features_sorted[indices_of_first_matrices[matrix_index][0]:
                                indices_of_first_matrices[matrix_index][1], :], dtype=np.float32)
        second_matrix = np.array(template_features_sorted[indices_of_second_matrices[matrix_index][0]:
                                 indices_of_second_matrices[matrix_index][1], :], dtype=np.float32)

        m = first_matrix.shape[0]
        n = second_matrix.shape[0]

        s = timer()
        if matrix_index != 0:
            del distances_on_gpu
        cuda.current_context().trashing.clear()

        if verbose:
            print('LOADING UP THE GPU')
        temp = np.array(np.zeros((m, n), dtype=np.float32))
        distances_on_gpu = cuda.to_device(np.asfortranarray(temp))
        e = timer()
        load_time = e - s
        if verbose:
            print("Loading matrix time:", "%.3f" % load_time, "s")

        if verbose:
            print('ITERATION NUMBER: ' + str(matrix_index + 1))

        _calculate_distances_on_gpu(a=first_matrix, b=second_matrix, distances_on_gpu=distances_on_gpu, verbose=verbose)

        gpu_mem = cuda.current_context().get_memory_info()
        available_gpu_mem = 0.9*gpu_mem[0]
        number_of_sorts = int(np.ceil((16 * n * m) / available_gpu_mem))  # 4 is the bytes per float32, 2 is the two
        # arrays that need to be loaded to gpu, the other factor of 2 is probably a doubling overhead in the algorithm

        if verbose:
            print('     Number of sorting segments = ' + str(number_of_sorts + 2))

        temp_indices, temp_distances = \
            _segment_sort_distances_get_knns(num_of_neighbours=num_of_neighbours, distances_on_gpu=distances_on_gpu,
                                             start_index=indices_of_second_matrices[matrix_index][0],
                                             number_of_sorts=number_of_sorts, verbose=verbose)

        selected_sorted_indices[indices_of_first_matrices[matrix_index][0]: indices_of_first_matrices[matrix_index][1],
                                :] = np.ascontiguousarray(temp_indices)
        selected_sorted_distances[indices_of_first_matrices[matrix_index][0]: indices_of_first_matrices[matrix_index][1],
                                  :] = np.ascontiguousarray(temp_distances)
        if verbose:
            print('FINISHED CALCULATING ' + str(matrix_index + 1) + ' OF ' + str(indices_of_first_matrices.shape[0]) +
                  ' ITERATIONS')

        end = timer()
        full_time = end - start
        if verbose:
            print("Spend Time:", "%.3f" % full_time, "s")

    return selected_sorted_indices, selected_sorted_distances

# ----------------------------------------------------------------------------------------------------------------------
# Function relating to computing the gradient of the force field in the low dimensional space

@cuda.jit
def _compute_gradient_on_gpu(t_sne, values_p, indices_p, num_of_dims, num_of_p_values, sum_q, delta):
    n, m = cuda.grid(2)

    distance = math.sqrt(math.pow((t_sne[n, 0] - t_sne[m, 0]), 2) + math.pow((t_sne[n, 1] - t_sne[m, 1]), 2))
    q = 1 / (1 + distance)
    delta[n, :] = q

    sum_q[0] += q

    cuda.syncthreads()

    value_p = 0.0
    for i in range(num_of_p_values[0]):
        if indices_p[n, i] == m:
            value_p = values_p[n, i]
            break

    mult = (value_p - q / sum_q[0]) * q

    for k in range(num_of_dims[0]):
        delta[n, k] = (t_sne[n, k] - t_sne[m, k]) * mult


def _put_array_to_device(array, array_name, verbose=True):
    s = timer()
    temp = np.array(array, np.float32)
    d_array = cuda.to_device(temp)
    e = timer()
    if verbose:
        print('     Load ' + array_name+ ' to device time: ' + str(e - s))
    return d_array


def compute_gradient(t_sne, indices_p, values_p, verbose=True):
    n = t_sne.shape[0]
    num_of_dims = t_sne.shape[1]
    num_of_p_values = indices_p.shape[1]
    sum_q = 0.0
    delta = np.empty((n, num_of_dims))

    s = timer()

    d_t_sne = _put_array_to_device(t_sne, 't_sne')
    d_indices_p = _put_array_to_device(indices_p, 'indices_p')
    d_values_p = _put_array_to_device(values_p, 'values_p')
    d_delta = _put_array_to_device(delta, 'delta')
    d_sum_q = _put_array_to_device(sum_q, 'sum_q')
    d_num_of_dims = _put_array_to_device(num_of_dims, 'num_of_dims')
    d_num_of_p_values = _put_array_to_device(num_of_p_values, 'num_of_p_values')

    threadsperblock = (32, 32)
    blockspergrid_x = math.ceil(t_sne.shape[0] / threadsperblock[0])
    blockspergrid_y = math.ceil(t_sne.shape[1] / threadsperblock[1])
    blockspergrid = (blockspergrid_x, blockspergrid_y)
    _compute_gradient_on_gpu[blockspergrid, threadsperblock](d_t_sne, d_values_p, d_indices_p, d_num_of_dims,
                                                             d_num_of_p_values, d_sum_q, d_delta)
    delta = d_delta.copy_to_host()

    e = timer()
    if verbose:
        print('COMPUTING GRADIENT TIME: ' + str(e - s))

    return delta
