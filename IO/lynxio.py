__author__ = 'Kaushik Ghose and George Dimitriadis'


"""Functions to read the flotilla of files produced by the Neuralynx system."""

from struct import unpack as upk, pack as pk, calcsize as csize
import logging, pylab
import os, platform, sys

logger = logging.getLogger(__name__)

NUM_SAMPLES_IN_PACKET = 512
HEADER_BYTE_SIZE = 2* 8 * 1024 # For some reason this works for a header size of 32Kb and not for a 16kB header

#NOTE: For python 3  fin = open(filename, mode='br')

def read_header(fin):
    """Standard 16 kB header."""
    return fin.read(HEADER_BYTE_SIZE)

def read_single_csc(fin, assume_same_fs=True, memmap=False):
    """Read a continuous record file. We return the raw packets but, in addition, if we set assume_same_fs as true we
    return a trace with all the data concatenated together, assuming that a constant sampling frequency was maintained
    through out. Gaps in the record are padded with zeros.
    Input:
    fin - file handle
    assume_same_fs - if True, concatenate any segments together, fill time gaps with zeros and return average Fs
    Ouput:
    Dictionary with fields
      'header' - the file header
      'packets' - the actual packets as read. This is a new pylab dtype with fields:
        'timestamp' - timestamp (us)
        'chan' - channel
        'Fs' - the sampling frequency
        'Ns' - the number of valid samples in the packet
        'samp' - the samples in the packet.
          e.g. x['packets']['samp'] will return a 2D array, number of packets long and 512 wide (since each packet carries 512 wave points)
          similarly x['packets']['timestamp'] will return an array number of packets long
      'Fs': the average frequency computed from the timestamps (can differ from the nominal frequency the device reports)
      'trace': the concatenated data from all the packets
      't0': the timestamp of the first packet.
    NOTE: while 'packets' returns the exact packets read, 'Fs' and 'trace' assume that the record has no gaps and that the
    sampling frequency has not changed during the recording
    """
    hdr = read_header(fin)
    csc_packet = pylab.dtype([
    ('timestamp', 'Q'),
    ('chan', 'I'),
    ('Fs', 'I'),
    ('Ns', 'I'),
    ('samp', '512h')
    ])

    if not memmap:
        data = pylab.fromfile(fin, dtype=csc_packet, count=-1)
    else:
        data = pylab.memmap(fin, dtype=csc_packet, mode = 'r', offset=HEADER_BYTE_SIZE)
    Fs = None
    trace = None
    if assume_same_fs:
        if data['Fs'].std() > 1e-6: #
            logger.warning('Fs is not fixed across trace, not packing packets together')
            assume_same_fs = False

    if not assume_same_fs or memmap: return {'header': hdr, 'packets': data}

    sample_duration_us = (1./data['Fs'][0])*1e6
    packet_duration_us = 513 * sample_duration_us
    #For the version we are dealing with, Neuralynx packets are always 512
    #This is actually a very poor estimate if the sampling freq is low, since it rounds to nearest Hz
    #So we'll not rely on this but come up with our own estimate
    #Using 512 samples makes the estimate in high sampling frequencies be 1 or 2 us smaller than the dt_us
    #So we are going to assume that any pause we did takes longer than 1/Fs seconds

    samp = data['samp']
    ts_us = data['timestamp']
    dt_us = pylab.diff(ts_us).astype('f')
    idx = pylab.find(dt_us > packet_duration_us) #This will find any instances where we paused the recording
    if idx.size == 0:#No padding needed
        trace = samp.ravel()
        Fs = (data['Ns'][:-1]/(dt_us*1e-6)).mean()
    else: #We have some padding to do.
        logger.debug('Gaps in record, padding')
        #Our first task is to find all the contiguous sections of data
        idx += 1 #Shifting indexes to point at the packets that come after a gap
        idx = pylab.insert(idx, 0, 0) #Now idx contains the indexes of every packet that starts a contiguous section
        idx = pylab.append(idx,ts_us.size) #And the index of the last packet
        Ns = data['Ns']
        estimFs_sum = 0
        N_samps = 0
        sections = []
        for n in range(idx.size-1): #collect all the sections
            n0 = idx[n]; n1=idx[n+1]
            sections.append(samp[n0:n1].ravel())
            if n1-n0 > 1:#We need more than one packet in a section to get an estimate
                estimFs_sum += (Ns[n0:n1-1]/(dt_us[n0:n1-1]*1e-6)).sum()
                N_samps += n1-1-n0

        Fs = estimFs_sum / float(N_samps)
        #Now pad the data appropriately
        padded = [sections[0]]
        cum_N = sections[0].size
        for n in range(1,len(sections)):
            #Now figure out how many zeros we have to pad to get the right length
            Npad = int((ts_us[idx[n]] - ts_us[0])*1e-6*Fs - cum_N)
            padded.append(pylab.zeros(Npad))
            padded.append(sections[n])
            cum_N += Npad + sections[n].size
        trace = pylab.concatenate(padded) #From this packet to the packet before the gap

    return {'header': hdr, 'packets': data, 'Fs': Fs, 'trace': trace, 't0': ts_us[0]}


# def read_all_csc(folder, assume_same_fs=True, memmap=False):
#     files = [folder+"\\"+f for f in os.listdir(folder) if f.endswith('.ncs')]
#     order = [int(file.split('.')[0].split('CSC')[1]) for file in files]
#     sort_order =  sorted(range(len(order)),key=order.__getitem__)
#     ordered_files = [files[i] for i in sort_order]
#
#     data = pylab.array([])
#     for file in ordered_files:
#         fin = open(file, mode='br')
#         x = read_single_csc(fin, assume_same_fs=assume_same_fs, memmap=memmap)
#         if not assume_same_fs or memmap:
#             channel_data = x['packets']['samp'].ravel()
#         else:
#             channel_data = x['trace']
#         pylab.append(data, channel_data, axis=1)
#
#     return data
def read_all_csc(data_folder, dtype='int16', assume_same_fs=True, memmap=False, memmap_folder=None, save_for_spikedetekt=False, channels_to_save=None, return_sliced_data=False):
    if sys.version_info[0] > 2:
        mode = 'br'
    else:
        mode = 'r'

    os_name = platform.system()
    if os_name == 'Windows':
        sep = '\\'
    elif os_name=='Linux':
        sep = r'/'

    files = [os.path.join(data_folder, f) for f in os.listdir(data_folder) if f.endswith('.ncs')]
    order = [int(file.split('.')[0].split('CSC')[1]) for file in files]
    sort_order =  sorted(range(len(order)),key=order.__getitem__)
    ordered_files = [files[i] for i in sort_order]

    if memmap:
        if not memmap_folder:
            raise NameError("A memmap_folder should be defined for memmapped data")
        out_filename = data_folder.split(sep)[-1]+'.dat'
        out_full_filename = os.path.join(memmap_folder, out_filename)

    data = None
    i = 0;
    for file in ordered_files:
        fin = open(file, mode=mode)
        x = read_single_csc(fin, assume_same_fs=assume_same_fs, memmap=memmap)
        if not assume_same_fs or memmap:
            channel_data = x['packets']['samp'].ravel()
            if data is None:
                data = pylab.memmap(out_full_filename, dtype=dtype, mode='w+', shape=(pylab.size(files), channel_data.size))
            else:
                data[i,:] = channel_data
                data.flush()
                i = i+1
                print(i)
        else:
            channel_data = x['trace']
            if data is None:
                data = pylab.zeros(shape=(pylab.size(files), channel_data.size), dtype=dtype)
            else:
                data[i,:] = channel_data
                i = i+1
                print(i)

    data_to_return = data
    if save_for_spikedetekt:
        if channels_to_save:
            data2 = data[channels_to_save,:]
            if return_sliced_data:
                data_to_return = data2
        else:
            data2 = data
        data2 = pylab.transpose(data2)
        data2.reshape(data2.size)
        filename = os.path.join(memmap_folder, 'spikedetekt_'+out_filename)
        data2.astype(dtype).tofile(filename)

    return data_to_return

def create_time_axis(timestamps, Fs, relative_to_first_ts=False):
    sample_duration_us = (1. / Fs) * 1e6
    time = pylab.zeros(len(timestamps) * NUM_SAMPLES_IN_PACKET, dtype='uint64')
    i = 0
    for ts in timestamps:
        packet_time = [ts + i*sample_duration_us for i in range(0, 512)]
        time[i * NUM_SAMPLES_IN_PACKET : i * NUM_SAMPLES_IN_PACKET + NUM_SAMPLES_IN_PACKET] = packet_time
        i+=1

    if relative_to_first_ts:
        return time-time[0]
    else:
        return time

def read_nev(fin, parse_event_string=False):
    """Read an event file.
    Input:
    fin - file handle
    parse_event_string - If set to true then parse the eventstrings nicely. This takes extra time. Default is False
    Ouput:
    Dictionary with fields
    'header' - the file header
    'packets' - the events. This is a new pylab dtype with fields corresponding to the event packets.
    'nstx'
    'npkt_id'
    'npkt_data_size'
    'timestamp' - timestamp (us)
    'eventid'
    'nttl' - value of the TTL port
    'ncrc'
    'ndummy1'
    'ndummy2'
    'dnExtra'
    'eventstring' - The alphanumeric string NeuraLynx attaches to this event
    'eventstring' - Only is parse_event_string is set to True. This is a nicely formatted eventstring
    """
    hdr = read_header(fin)
    nev_packet = pylab.dtype([
        ('nstx', 'h'),
        ('npkt_id', 'h'),
        ('npkt_data_size', 'h'),
        ('timestamp', 'Q'),
        ('eventid', 'h'),
        ('nttl', 'H'),
        ('ncrc', 'h'),
        ('ndummy1', 'h'),
        ('ndummy2', 'h'),
        ('dnExtra', '8i'),
        ('eventstring', '128c')
    ])
    data = pylab.fromfile(fin, dtype=nev_packet, count=-1)
    logger.debug('{:d} events'.format(data['timestamp'].size))
    if parse_event_string:
        logging.info('Packaging the event strings. This makes things slower.')
        # Makes things slow. Often this field is not needed
        evstring = [None]*data['timestamp'].size
        for n in range(data['timestamp'].size):
            str = ''.join(data['eventstring'][n])
            evstring[n] = str.replace('\00','').strip()
        return {'header': hdr, 'events': data, 'eventstring': evstring}
    else:
        return {'header': hdr, 'events': data}

def read_nse(fin):
    """Read single electrode spike record.
    Inputs:
    fin - file handle
    only_timestamps - if true, only load the timestamps, ignoring the waveform and feature data
    Output: Dictionary with fields
    'header'  - header info
    'packets' - pylab data structure with the spike data
    Notes:
    0. What is spike acquizition entity number? Ask neuralynx
    1. Removing LOAD_ATTR overhead by defining time_stamp_append = [time_stamp[n].append for n in xrange(100)] and using
       time_stamp_append[dwCellNumber](qwTimeStamp) in the loop does not seem to improve performance.
       It reduces readability so I did not use it.
    2. Disabling garbage collection did not help
    3. In general, dictionary lookups slow things down
    4. using numpy arrays, with preallocation is slower than the dumb, straightforward python list appending
    """

    hdr = read_header(fin)
    nse_packet = pylab.dtype([
        ('timestamp', 'Q'),
        ('saen', 'I'),
        ('cellno', 'I'),
        ('Features', '8I'),
        ('waveform', '32h')
    ])
    data = pylab.fromfile(fin, dtype=nse_packet, count=-1)
    return {'header': hdr, 'packets': data}


def write_nse(fname, time_stamps, remarks=''):
    """Write out the given time stamps into a nse file."""
    with open(fname,'wb') as fout:
        fmt = '=QII8I32h'
        dwScNumber = 1
        dwCellNumber = 1
        #dnParams = [0]*8
        #snData = [0]*32
        garbage = [0]*40

        header = remarks.ljust(16*1024,'\x00')
        fout.write(header)
        for ts in time_stamps:
          fout.write(pk(fmt, ts, dwScNumber, dwCellNumber, *garbage))


def extract_nrd_ec(fname, ftsname, fttlname, fchanname, channel_list, channels=64, max_pkts=-1, buffer_size=10000, error_bugout=1000000000):
    """Read and write out selected raw traces from the .nrd file with error checking.
    Inputs:
    fname - name of nrd file
    ftsname - name under which timestamp vector will be saved
    fttlname - name under which the events will be saved
    fchanname - a list of file names for the
    channel_list - Which AD channels to convert.
    channels - total channels in the system
    max_pkts - total packets to read. If set to -1 then read all packets
    buffer_size   - how many chunks to read at a time.
    error_bugout - If the sum of stx, crc and timestamp errors exceed this value quit reading the file
    Outputs:
    Data are written to file
    e.g.
    ----------------------------------------------------------------------------------------------------------------------
    from neurapy.neuralynx import lynxio
    import logging
    logging.basicConfig(level=logging.DEBUG)
    channels = 64
    fname = '/Users/kghose/Research/2013/Projects/Workingmemory/Data/NeuraLynx/2013-01-25_14-53-04/DigitalLynxRawDataFile.nrd'
    channel_list = [0,1,2]
    ftsname = 'timestamps.raw'
    fttlname = 'ttl.raw'
    fchanname = ['chan_{:000d}.raw'.format(ch) for ch in channel_list]
    lynxio.extract_nrd(fname, ftsname, fttlname, fchanname, channel_list, channels, max_pkts=1000)
    ----------------------------------------------------------------------------------------------------------------------
    Data are written as a pure stream of binary data and can be easily and efficiently read using the numpy read function.
    For convenience, a function that reads the timestamps, events and channels (read_extracted_data) is included in the library.
    """
    def seek_packet(f):
        """Skip forward until we find the STX magic number."""
        #Read in 32bit increments until the magic number is found
        start = f.tell()
        pkt = f.read(4)
        while len(pkt) == 4:
            if pkt == '\x00\x08\x00\x00': #Magic number 2048 0x0800
                f.seek(-4,1) #Realign
                break
            pkt = f.read(4)
        stop = f.tell()
        return stop - start

        logger.info('Notice: you are using the slow version of the extractor. All error checks are done')

        #nrd packet format
        nrd_packet = pylab.dtype([
            ('stx', 'i'),
            ('pkt_id', 'i'),
            ('pkt_data_size', 'i'),
            ('timestamp high', 'I'), #Neuralynx timestamp is ... in its own 32 bit world
            ('timestamp low', 'I'),
            ('status', 'i'),
            ('ttl', 'I'),
            ('extra', '10i'),
            ('data', '{:d}i'.format(channels)),
            ('crc', 'i')
        ])
        packet_size = nrd_packet.itemsize

        pkt_cnt = 0
        garbage_bytes = 0
        stx_err_cnt = 0
        pkt_id_err_cnt = 0
        pkt_size_err_cnt = 0
        pkt_ts_err_cnt = 0
        pkt_crc_err_cnt = 0

        if max_pkts != -1: #An insidious bug was killed here!
            if buffer_size > max_pkts:
                buffer_size = max_pkts

        #The files we will write to.
        fts = open(ftsname,'wb')
        fttl = open(fttlname,'wb')
        fchan = [open(fcn,'wb') for fcn in fchanname]

        last_ts = 0
        with open(fname,'rb') as f:
            hdr = read_header(f)
            logger.info('File header: {:s}'.format(hdr))

            garbage_bytes += seek_packet(f)
            these_packets = pylab.fromfile(f, dtype=nrd_packet, count=buffer_size)
            while these_packets.size > 0:
                all_packets_good = True
                packets_read = these_packets.size

                idx = pylab.find(these_packets['stx'] != 2048)
                if idx.size > 0:
                    stx_err_cnt += 1
                    all_packets_good = False
                    max_good_packets = idx[0]
                    these_packets = these_packets[:max_good_packets]

                if these_packets.size > 0:
                    idx = pylab.find(these_packets['pkt_id'] != 1)
                    if idx.size > 0:
                      pkt_id_err_cnt += 1
                      all_packets_good = False
                      max_good_packets = idx[0]
                      these_packets = these_packets[:max_good_packets]

                if these_packets.size > 0:
                    idx = pylab.find(these_packets['pkt_data_size'] != 10 + channels)
                    if idx.size > 0:
                      pkt_size_err_cnt += 1
                      all_packets_good = False
                      max_good_packets = idx[0]
                      these_packets = these_packets[:max_good_packets]

                if these_packets.size > 0:
                    #crc computation
                    field32 = pylab.vstack([these_packets[k].T for k in nrd_packet.fields.keys()]).astype('I')
                    crc = pylab.zeros(these_packets.size,dtype='I')
                    for idx in range(field32.shape[0]):
                        crc ^= field32[idx,:]
                    idx = pylab.find(crc != 0)
                    if idx.size > 0:
                        pkt_crc_err_cnt += 1
                        all_packets_good = False
                        max_good_packets = idx[0]
                        these_packets = these_packets[:max_good_packets]

                if these_packets.size > 0:
                    ts = pylab.array((these_packets['timestamp high'].astype('uint64')<<32) | (these_packets['timestamp low']), dtype='uint64')
                    bad_idx = -1
                    if last_ts > ts[0]:#Time stamps out of order at buffer boundary
                        bad_idx = 0
                    else:
                        idx = pylab.find(ts[:-1] > ts[1:])
                        if idx.size > 0:
                            bad_idx = idx[0] + 1
                    if bad_idx > -1:
                        logger.info('Out of order timestamp {:d}'.format(int(ts[bad_idx])))
                        pkt_ts_err_cnt += 1
                        all_packets_good = False
                        max_good_packets = bad_idx
                        these_packets = these_packets[:max_good_packets]
                        ts = ts[:max_good_packets]

                if these_packets.size > 0:
                    last_ts = ts[-1] #Ready for the next read
                    ts.tofile(fts)
                    these_packets['ttl'].tofile(fttl)
                    for idx,ch in enumerate(channel_list):
                        these_packets['data'][:,ch].tofile(fchan[idx])

                pkt_cnt += these_packets.size
                if max_pkts != -1:
                    if pkt_cnt >= max_pkts: #NOTE: This may give us upto buffer_size -1 more packets than we want.
                        break

                if not all_packets_good:
                    f.seek((these_packets.size-packets_read)*packet_size+4,1) #Rewind all the way except 32 bits
                    garbage_bytes += seek_packet(f)

                if pkt_ts_err_cnt + pkt_crc_err_cnt + stx_err_cnt > error_bugout:
                    logger.warning('Too many errors, bugging out')
                    break

                these_packets = pylab.fromfile(f, dtype=nrd_packet, count=buffer_size)

        fts.close()
        fttl.close()
        [fch.close() for fch in fchan]

        logger.info('Extracted {:d} packets'.format(pkt_cnt))
        logger.info('{:d} garbage words'.format(garbage_bytes))
        logger.info('{:d} packets had bad stx'.format(stx_err_cnt))
        logger.info('{:d} packets had bad pkt id'.format(pkt_id_err_cnt))
        logger.info('{:d} packets had bad crc'.format(pkt_crc_err_cnt))
        logger.info('{:d} packets had out of order timestamps'.format(pkt_ts_err_cnt))




def extract_nrd_fast(fname, ftsname, fttlname, fchanname, channel_list, channels=64, max_pkts=-1, buffer_size=10000):
    """Read and write out selected raw traces from the .nrd file.
    Inputs:
    fname - name of nrd file
    ftsname - name under which timestamp vector will be saved
    fttlname - name under which the events will be saved
    fchanname - a list of file names for the
    channel_list - Which AD channels to convert.
    channels - total channels in the system
    max_pkts - total packets to read. If set to -1 then read all packets
    buffer_size   - how many chunks to read at a time.
    Outputs:
    Data are written to file
    e.g.
    ----------------------------------------------------------------------------------------------------------------------
    from neurapy.neuralynx import lynxio
    import logging
    logging.basicConfig(level=logging.DEBUG)
    channels = 64
    fname = '/Users/kghose/Research/2013/Projects/Workingmemory/Data/NeuraLynx/2013-01-25_14-53-04/DigitalLynxRawDataFile.nrd'
    channel_list = [0,1,2]
    ftsname = 'timestamps.raw'
    fttlname = 'ttl.raw'
    fchanname = ['chan_{:000d}.raw'.format(ch) for ch in channel_list]
    lynxio.extract_nrd(fname, ftsname, fttlname, fchanname, channel_list, channels, max_pkts=1000)
    ----------------------------------------------------------------------------------------------------------------------
    Data are written as a pure stream of binary data and can be easily and efficiently read using the numpy read function.
    For convenience, a function that reads the timestamps, events and channels (read_extracted_data) is included in the library.
    In my experience STX, CRC, timestamp errors and garbage bytes between packets are extremely rare in a properly working system. This function eschews any kind of checks on the data read and just converts the packets. If you suspect that your data has dropped packets, crc or other issues you should try the regular version of this function. You can note if you have packet errors from your Cheetah software.
    Personally, I recommend using the _ec version of the code. It runs fast enough.
    """
    logger.info('Notice: you are using the fast version of the extractor. No error checks are done')

    #nrd packet format
    nrd_packet = pylab.dtype([
        ('stx', 'i'),
        ('pkt_id', 'i'),
        ('pkt_data_size', 'i'),
        ('timestamp high', 'I'), #Neuralynx timestamp is ... in its own 32 bit world
        ('timestamp low', 'I'),
        ('status', 'i'),
        ('ttl', 'I'),
        ('extra', '10i'),
        ('data', '{:d}i'.format(channels)),
        ('crc', 'i')
    ])
    #packet_size = nrd_packet.itemsize

    pkt_cnt = 0
    if max_pkts != -1: #An insidious bug was killed here!
        if buffer_size > max_pkts:
            buffer_size = max_pkts

    #The files we will write to. fixme: test for properly opened?
    fts = open(ftsname,'wb')
    fttl = open(fttlname,'wb')
    fchan = [open(fcn,'wb') for fcn in fchanname]

    with open(fname,'rb') as f:
        hdr = read_header(f)
        logger.info('File header: {:s}'.format(hdr))

        #Read in 32bit increments until the magic number is found
        pkt = f.read(4)
        while len(pkt) == 4:
            if pkt == '\x00\x08\x00\x00': #Magic number 2048 0x0800
                f.seek(-4,1) #Realign
                break
            pkt = f.read(4)

        these_packets = pylab.fromfile(f, dtype=nrd_packet, count=buffer_size)
        while these_packets.size > 0:
            ts = pylab.array((these_packets['timestamp high']<<32) | (these_packets['timestamp low']), dtype='uint64')
            ts.tofile(fts)
            these_packets['ttl'].tofile(fttl)
            for idx,ch in enumerate(channel_list):
                these_packets['data'][:,ch].tofile(fchan[idx])

            pkt_cnt += these_packets.size
            if max_pkts != -1:
                if pkt_cnt >= max_pkts: #NOTE: This may give us upto buffer_size -1 more packets than we want.
                    break
            these_packets = pylab.fromfile(f, dtype=nrd_packet, count=buffer_size)

    fts.close()
    fttl.close()
    [fch.close() for fch in fchan]

    logger.info('Extracted {:d} packets'.format(pkt_cnt))



def read_extracted_data(fname, type='addata'):
    """Reads data file extracted by extract_nrd.
    Inputs:
    fname - name of the file we want to read.
    type  - type of the data. Has to be one of 'ts','ttl' or 'addata'
    'ts' - time stamps which are uint64 and give values in microseconds
    'ttl' - the parallel port input which is uint32
    'addata' - the continuous A/D channel data which is int32
    Output:
    data - pylab array of appropriate type
    """
    if type == 'ts':
        fmt = 'Q'
    elif type == 'ttl':
        fmt = 'I'
    elif type == 'addata':
        fmt = 'i'
    else:
        logger.error('Unrecognized data type {:s}'.format(type))
        return None

    return pylab.memmap(fname, dtype=fmt, mode='r')