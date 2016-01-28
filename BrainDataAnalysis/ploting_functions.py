# -*- coding: utf-8 -*-
"""
Created on Tue Nov 19 13:10:15 2013

@author: George Dimitriadis
"""

import numpy as np
import scipy.interpolate as interpolate
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import pandas as pd
import itertools
import warnings
import BrainDataAnalysis.Utilities as ut
import BrainDataAnalysis.timelocked_analysis_functions as tlf
import matplotlib.animation as animation
from matplotlib.widgets import Button
from mpldatacursor import datacursor



def plot_avg_time_locked_data(timeLockedData, timeAxis, subplot=None, timeToPlot=None, remove_channels=None, picker=None, labels=False, figure_id=0, figure=None):
    if timeToPlot==None:
        if np.size(np.shape(timeLockedData)) > 1:
            samplesToPlot = [0, np.shape(timeLockedData)[1]]
        else:
            samplesToPlot = [0, np.shape(timeLockedData)[0]]
    else:
        Freq = len(timeAxis)/(timeAxis[-1]-timeAxis[0])
        startingTimeDif = timeToPlot[0] - timeAxis[0]
        endingTimeDif = timeToPlot[1] - timeAxis[0]
        if startingTimeDif < 0:
            raise ArithmeticError("The starting time to plot must be after the starting time of the trial")
        if endingTimeDif < 0:
            raise ArithmeticError("The end time to plot must be after the starting time of the trial")
        samplesToPlot = [startingTimeDif*Freq, endingTimeDif*Freq]

    if figure is None:
        fig = plt.figure(figure_id)
    else:
        fig = figure

    if subplot is not None:
        ax = fig.add_subplot(subplot)
    else:
        ax = fig.add_subplot(111)

    if picker:
        def on_pick(event):
            event.artist.set_visible(not event.artist.get_visible())
            print(ax.lines.index(event.artist))
            fig.canvas.draw()
        fig.canvas.callbacks.connect('pick_event', on_pick)


    if remove_channels is not None:
        timeLockedData[remove_channels, :] = float('nan')
    if np.size(np.shape(timeLockedData)) > 1:
        lines = ax.plot(timeAxis[samplesToPlot[0]:samplesToPlot[1]], np.transpose(timeLockedData[:, samplesToPlot[0]:samplesToPlot[1]]), picker=picker)
    else:
        lines = ax.plot(timeAxis[samplesToPlot[0]:samplesToPlot[1]], timeLockedData[samplesToPlot[0]:samplesToPlot[1]], picker=picker)

    if labels:
        datacursor(hover=True)
        for i in np.arange(0,len(lines)):
            lines[i].set_label(str(i))

    fig.add_subplot(ax)

    plt.show()
    return ax


def recalculate_ylims(data):
    if data.min()>0:
        min_offset = data.min()*0.2
    else:
        min_offset = data.min()*1.8
    if data.max()>0:
        max_offset = data.max()*1.8
    else:
        max_offset = data.max()*0.2

    return min_offset, max_offset


def scan_through_2nd_dim(data, freq=32556, timeToPlot=1, startTime=0, plot_around_time_points=None,
                         remove_channels=None, figure_id=0, picker=None, labels=False):

    if plot_around_time_points is None:
        samplesToPlot = [startTime*freq, (startTime+timeToPlot)*freq]
    else:
        startTime = (plot_around_time_points[0] - timeToPlot / 2)
        samplesToPlot = [startTime * freq, (plot_around_time_points[0] + timeToPlot / 2) * freq]

    time_axis = np.arange(samplesToPlot[0]/freq, samplesToPlot[1]/freq, 1.0/freq)

    fig = plt.figure(figure_id)
    ax_multidim_data = fig.add_subplot(111)

    if picker:
        def on_pick(event):
            event.artist.set_visible(False)
            print(ax_multidim_data.lines.index(event.artist))
            fig.canvas.draw()
        fig.canvas.callbacks.connect('pick_event', on_pick)

    if np.size(np.shape(data)) > 1:
        data_to_plot =  np.transpose(data[:, int(samplesToPlot[0]):int(samplesToPlot[1])])
        number_of_channels = np.size(data, 0)
        number_of_time_points = np.size(data, 1)
        if remove_channels is not None:
            data_to_plot = data_to_plot.astype(float)
            data_to_plot[:, remove_channels] = float('nan')
    else:
        data_to_plot = data[samplesToPlot[0]:samplesToPlot[1]]
        number_of_channels = 1
        number_of_time_points = len(data)
        if remove_channels is not None:
            data_to_plot =  np.transpose(data[:, samplesToPlot[0]:samplesToPlot[1]])
            data_to_plot[remove_channels] = float('nan')

    lines = ax_multidim_data.plot(time_axis, data_to_plot, picker=picker)

    fig.add_subplot(ax_multidim_data)


    multidim_data_ax_offset = 0.07
    multidim_data_ax_heightChange = 0.07

    pos_multi = ax_multidim_data.get_position()
    new_pos_multi = [pos_multi.x0, pos_multi.y0+multidim_data_ax_offset, pos_multi.width, pos_multi.height-multidim_data_ax_heightChange]
    ax_multidim_data.set_position(new_pos_multi)

    bbox_props = dict(boxstyle="round", fc="w", ec="0.5", alpha=0.9)
    trial_text = plt.figtext(0.85, 0.85, "Time: "+str(startTime)+" s", ha="right", va="top", size=20, bbox=bbox_props)

    class Index:
        ind = 0

        def nextone(self, event):
            [start_point, end_point] = self.get_start_end_time_points()
            if start_point < number_of_time_points:
                self.ind += 1
                [start_point, end_point] = self.get_start_end_time_points()
                for i in np.arange(0, number_of_channels):
                    if remove_channels is None or (remove_channels is not None and i not in remove_channels):
                        if number_of_channels is 1:
                            new_data = data[start_point:end_point]
                        else:
                            new_data = data[i, start_point:end_point]
                        lines[i].set_ydata(new_data)
                    time_axis = np.arange(start_point/freq, end_point/freq, 1.0/freq)[:(end_point - start_point)]
                    lines[i].set_xdata(time_axis)
                ax_multidim_data.set_xlim([time_axis[0], time_axis[-1]])
                min_offset, max_offset = recalculate_ylims(new_data)
                ax_multidim_data.set_ylim([min_offset, max_offset])
                trial_text.set_text("Time: "+str(start_point/freq)+" s")
                plt.draw()

        def prev(self, event):
            [start_point, end_point] = self.get_start_end_time_points()
            if start_point > 0:
                self.ind -= 1
                [start_point, end_point] = self.get_start_end_time_points()
                for i in np.arange(0, number_of_channels):
                    if remove_channels is None or (remove_channels is not None and i not in remove_channels):
                        if number_of_channels is 1:
                            new_data = data[start_point:end_point]
                        else:
                            new_data = data[i, start_point:end_point]
                        lines[i].set_ydata(new_data)
                    time_axis = np.arange(start_point/freq, end_point/freq, 1.0/freq)[:(end_point - start_point)]
                    lines[i].set_xdata(time_axis)
                ax_multidim_data.set_xlim([time_axis[0], time_axis[-1]])
                min_offset, max_offset = recalculate_ylims(new_data)
                ax_multidim_data.set_ylim([min_offset, max_offset])
                trial_text.set_text("Time: "+str(start_point/freq)+" s")
                plt.draw()

        def get_start_end_time_points(self):
            if plot_around_time_points is None:
                start_point = (self.ind*timeToPlot+startTime)*freq
                end_point = ((self.ind+1)*timeToPlot+startTime)*freq
            else:
                start_point = (plot_around_time_points[self.ind] - timeToPlot / 2) * freq
                end_point = (plot_around_time_points[self.ind] + timeToPlot / 2) * freq
            return [int(start_point), int(end_point)]

    callback = Index()
    axprev = plt.axes([0.7, 0.05, 0.1, 0.075])
    axnext = plt.axes([0.81, 0.05, 0.1, 0.075])
    bnext = Button(axnext, 'Next')
    bnext.on_clicked(callback.nextone)
    bprev = Button(axprev, 'Previous')
    bprev.on_clicked(callback.prev)

    return (bnext, bprev)

def scan_through_3rd_dim(data, timeAxis, timeToPlot=None, parallel_data=None, parallel_time=None, remove_channels=None, figure_id=0):

    fig = plt.figure(figure_id)

    if parallel_data is not None:
        subplot = 211
    else:
        subplot = None

    if len(np.shape(data))== 2:
        data = np.reshape(data, newshape=(1, np.shape(data)[0], np.shape(data)[1]))

    ax_multidim_data = plot_avg_time_locked_data(data[:, :, 0], timeAxis, subplot=subplot, timeToPlot=timeToPlot, remove_channels=remove_channels, figure=fig)

    if parallel_data is None:
        multidim_data_ax_offset = 0.07
        multidim_data_ax_heightChange = multidim_data_ax_offset
    else:
        subplot = 212
        ta = timeAxis
        if parallel_time is not None:
            ta = parallel_time
        ax_parralel_data = plot_avg_time_locked_data(parallel_data[:, 0], ta, subplot=subplot, timeToPlot=timeToPlot, figure=fig)
        multidim_data_ax_offset = -0.15
        multidim_data_ax_heightChange = multidim_data_ax_offset
        parralel_ax_offset = 0.07

        pos_parralel = ax_parralel_data.get_position()
        new_pos_parralel = [pos_parralel.x0, pos_parralel.y0+parralel_ax_offset, pos_parralel.width, pos_parralel.height-parralel_ax_offset+multidim_data_ax_offset]
        ax_parralel_data.set_position(new_pos_parralel)

    pos_multi = ax_multidim_data.get_position()
    new_pos_multi = [pos_multi.x0, pos_multi.y0+multidim_data_ax_offset, pos_multi.width, pos_multi.height-multidim_data_ax_heightChange]
    ax_multidim_data.set_position(new_pos_multi)

    bbox_props = dict(boxstyle="round", fc="w", ec="0.5", alpha=0.9)
    trial_text = plt.figtext(0.85, 0.85, "Trial: "+str(0), ha="right", va="top", size=20, bbox=bbox_props)

    class Index:
        ind = 0
        def next(self, event):
            if self.ind < np.size(data, 2) - 1:
                self.ind += 1
                lines_multi_data = ax_multidim_data.get_lines()
                for i in np.arange(0, np.size(data, 0)):
                    new_data = np.squeeze(data[i, :, self.ind])
                    lines_multi_data[i].set_ydata(new_data)
                if parallel_data is not None:
                    line_parallel_data = ax_parralel_data.get_lines()
                    line_parallel_data[0].set_ydata(parallel_data[:, self.ind])
                #min_offset, max_offset = recalculate_ylims(new_data)
                #ax_multidim_data.set_ylim([min_offset, max_offset])
                trial_text.set_text("Trial: "+str(self.ind))
                plt.draw()

        def prev(self, event):
            if self.ind > 0:
                self.ind -= 1
                lines = ax_multidim_data.get_lines()
                for i in np.arange(0, np.size(data, 0)):
                    new_data = np.squeeze(data[i, :, self.ind])
                    lines[i].set_ydata(new_data)
                if parallel_data is not None:
                    line_parallel_data = ax_parralel_data.get_lines()
                    line_parallel_data[0].set_ydata(parallel_data[:, self.ind])
                #min_offset, max_offset = recalculate_ylims(new_data)
                #ax_multidim_data.set_ylim([min_offset, max_offset])
                trial_text.set_text("Trial: "+str(self.ind))
                plt.draw()

    callback = Index()
    axprev = plt.axes([0.7, 0.05, 0.1, 0.075])
    axnext = plt.axes([0.81, 0.05, 0.1, 0.075])
    bnext = Button(axnext, 'Next')
    bnext.on_clicked(callback.next)
    bprev = Button(axprev, 'Previous')
    bprev.on_clicked(callback.prev)

    return (bnext, bprev)


def scan_through_image_stack(data, zlimits=None, figure_id=0):

    fig = plt.figure(figure_id)

    if zlimits is None:
        zlimits = [np.min(data), np.max(data)]

    ax_multidim_data = fig.add_subplot(111)
    ax_multidim_data.imshow(data[:, :, 0], vmin=zlimits[0], vmax=zlimits[1])

    multidim_data_ax_offset = 0.07
    multidim_data_ax_heightChange = multidim_data_ax_offset


    pos_multi = ax_multidim_data.get_position()
    new_pos_multi = [pos_multi.x0, pos_multi.y0+multidim_data_ax_offset, pos_multi.width, pos_multi.height-multidim_data_ax_heightChange]
    ax_multidim_data.set_position(new_pos_multi)

    bbox_props = dict(boxstyle="round", fc="w", ec="0.5", alpha=0.9)
    trial_text = plt.figtext(0.85, 0.85, "Trial: "+str(0), ha="right", va="top", size=20, bbox=bbox_props)

    class Index:
        ind = 0
        def next(self, event):
            if self.ind < np.size(data, 2) - 1:
                self.ind += 1
                ax_multidim_data.cla()
                ax_multidim_data.imshow(np.squeeze(data[:, :, self.ind]), vmin=zlimits[0], vmax=zlimits[1])
                trial_text.set_text("Trial: "+str(self.ind))
                plt.draw()

        def prev(self, event):
            if self.ind > 0:
                self.ind -= 1
                ax_multidim_data.cla()
                ax_multidim_data.imshow(np.squeeze(data[:, :, self.ind]), vmin=zlimits[0], vmax=zlimits[1])
                trial_text.set_text("Trial: "+str(self.ind))
                plt.draw()

    callback = Index()
    axprev = plt.axes([0.7, 0.05, 0.1, 0.075])
    axnext = plt.axes([0.81, 0.05, 0.1, 0.075])
    bnext = Button(axnext, 'Next')
    bnext.on_clicked(callback.next)
    bprev = Button(axprev, 'Previous')
    bprev.on_clicked(callback.prev)

    return (bnext, bprev)


# electrode_structure is length x width #of electrodes with the number of the intan data in each element
def spread_data(data, electrode_structure, col_spacing=3, row_spacing=0.5):

    data_baseline = (data.T - np.median(data, axis=1).T).T
    new_data = np.zeros(shape=(np.shape(data)[0], np.shape(data)[1]))

    num_of_rows = np.shape(electrode_structure)[0]
    num_of_cols = np.shape(electrode_structure)[1]


    stdv = np.average(np.std(data_baseline, axis=1), axis=0)

    col_spacing = col_spacing * stdv
    row_spacing = row_spacing * stdv
    for r in np.arange(0, num_of_rows):
        for c in np.arange(0, num_of_cols):
            new_data[electrode_structure[r, c], :] = data_baseline[electrode_structure[r, c], :] - \
                                                     r * col_spacing - \
                                                     c * row_spacing

    return new_data




def plot_topoplot(channel_positions, data, show=True, **kwargs):
    if not kwargs.get('hpos'):
        hpos = 0
    else:
        hpos = kwargs['hpos']
    if not kwargs.get('vpos'):
        vpos = 0
    else:
        vpos = kwargs['vpos']   
    if not kwargs.get('width'):
        width = None
    else:
        width = kwargs['width']    
    if not kwargs.get('height'):
        height = None
    else:
        height = kwargs['height']
    if not kwargs.get('gridscale'):
        gridscale = 10
    else:
        gridscale = kwargs['gridscale']
    if not kwargs.get('interpolation_method'):
        interpolation_method = "bicubic"  # ‘none’, ‘nearest’, ‘bilinear’, ‘bicubic’, ‘spline16’, ‘spline36’, ‘hanning’, ‘hamming’, ‘hermite’, ‘kaiser’, ‘quadric’, ‘catrom’, ‘gaussian’, ‘bessel’, ‘mitchell’, ‘sinc’, ‘lanczos’
    else:
        interpolation_method = kwargs['interpolation_method']
    if not kwargs.get('zlimits'):
        zlimits = None
    else:
        zlimits = kwargs['zlimits']
    if not kwargs.get('outline'):
        outline = None
    else:
        outline = kwargs['outline']   
    
    if np.isnan(data).any():
        warnings.warn('The data passed to plot_topoplot contain NaN values. These will create unexpected results in the interpolation. Deal with them.')

    channel_positions = channel_positions.sort_index(by='Numbers', ascending=True)
    channel_positions = np.array([xy for num_idx, str_idx, xy in channel_positions.values])
    allCoordinates = channel_positions
    if outline:
        allCoordinates = [channel_positions, outline]
    
    naturalWidth = np.max(allCoordinates[:, 0]) - np.min(allCoordinates[:, 0])
    naturalHeight = np.max(allCoordinates[:, 1]) - np.min(allCoordinates[:, 1])

    if not width and not height:
        xScaling = 1
        yScaling = 1
    elif not width and height:
        yScaling = height/naturalHeight
        xScaling = yScaling
    elif width and not height:
        xScaling = width/naturalWidth
        yScaling = xScaling
    elif width and height:
        xScaling = width/naturalWidth
        yScaling = height/naturalHeight

    chanX = channel_positions[:, 0] * xScaling + hpos
    chanY = channel_positions[:, 1] * yScaling + vpos

    hlim = [np.min(chanX), np.max(chanX)]
    vlim = [np.min(chanY), np.max(chanY)]

    if interpolation_method is not 'none':
        xi, yi = np.mgrid[hlim[0]:hlim[1]:complex(0, gridscale)*(hlim[1]-hlim[0]), vlim[0]:vlim[1]:complex(0, gridscale)*(vlim[1]-vlim[0])]
    else:
        xi, yi = np.mgrid[hlim[0]:hlim[1]+1, vlim[0]:vlim[1]+1] #for no interpolation show one pixel per data point


    Zi = interpolate.griddata((chanX, chanY), data,  (xi, yi))

    if not zlimits:
        vmin = Zi.min()
        vmax = Zi.max()
    else:
        vmin = zlimits[0]
        vmax = zlimits[1]

    if not outline:
        expansion = 0.05*np.max([hlim, vlim])
        outline = pd.DataFrame(np.array([[hlim[0]-expansion, vlim[0]-expansion], [hlim[1]+expansion, vlim[0]-expansion],\
                                         [hlim[1]+expansion, vlim[1]+expansion], [hlim[0]-expansion, vlim[1]+expansion],\
                                         [hlim[0]-expansion, vlim[0]-expansion]]))

    ml = MultipleLocator(1)
    cmap = plt.get_cmap("seismic")
    image = plt.imshow(Zi.T, cmap=cmap, aspect='equal', origin='upper',  extent=[hlim[0], hlim[1], vlim[1], vlim[0]], vmin=vmin, vmax=vmax, interpolation=interpolation_method)
    plt.axes().yaxis.set_minor_locator(ml)
    plt.axes().xaxis.set_minor_locator(ml)

    scat = plt.scatter(chanX, chanY)
    if show:
        plt.colorbar(image)
        plt.show()

    return image, scat



def plot_video_topoplot(data, time_axis, channel_positions, times_to_plot=[-0.1, 0.2], time_window = 0.002, time_step = 0.002, sampling_freq = 1000, zlimits = None,filename=None):
    fig = plt.figure()
    sample_step = int(time_step * sampling_freq)
    sub_time_indices = np.arange(ut.find_closest(time_axis, times_to_plot[0]), ut.find_closest(time_axis, times_to_plot[1]))
    sub_time_indices = sub_time_indices[0::sample_step]
    if np.shape(channel_positions)[0] <= 64:
        text_y = 8.3
    elif np.shape(channel_positions)[0] <= 128:
        text_y = 16.5
    text_x = 2
    images = []
    for t in sub_time_indices:
        samples = [t, t + (time_window*sampling_freq)]
        data_to_plot = np.mean(data[:, int(samples[0]):int(samples[1])], 1)
        image, scat = plot_topoplot(channel_positions, data_to_plot, show=False, interpmethod="quadric", gridscale=5, zlimits = zlimits)
        txt = plt.text(x=text_x, y=text_y, s=str(time_axis[t])+' secs')
        images.append([image, scat, txt])
    FFwriter = animation.FFMpegWriter()
    ani = animation.ArtistAnimation(fig, images, interval=500, blit=True, repeat_delay=1000)
    plt.colorbar(mappable=image)
    if filename is not None:
        plt.rcParams['animation.ffmpeg_path'] = r"C:\George\Development\PythonProjects\AnalysisDevelopment\Code\ExtraRequirements\ffmpeg-20140618-git-7f52960-win64-static\bin\ffmpeg.exe"
        ani.save(filename, writer = FFwriter, fps=1, bitrate=5000, dpi=300, extra_args=['h264'])
    plt.show()


