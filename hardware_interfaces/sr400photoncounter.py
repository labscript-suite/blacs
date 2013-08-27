import gtk
from output_classes import DO
from tab_base_classes import Tab, Worker, define_state

import numpy

class sr400photoncounter(Tab):
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self, BLACS, PhotonCounterWorker, notebook, settings)
        self.settings = settings
        self.device_name = settings['device_name']        
        self.usbport = self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/sr400photoncounter.glade')
        
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text(self.device_name + ' running on ' + self.usbport)
        
        # Insert our GUI into the viewport provided by BLACS:
        self.viewport.add(self.toplevel)
        
        # Initialise the photoncounter:
        self.initialise_photoncounter()
        
        
    @define_state
    def initialise_photoncounter(self):
        self.queue_work('initialise_photoncounter', self.device_name, self.usbport)
        
    @define_state
    def destroy(self):        
        self.queue_work('close')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab() 
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.queue_work('program_buffered', h5file)
        self.do_after('leave_program_buffered', notify_queue)
    
    def leave_program_buffered(self, notify_queue, _results):
        # Notify the queue manager thread that we've finished
        # transitioning to buffered:
        notify_queue.put(self.device_name)
    
    @define_state
    def abort_buffered(self):
        self.queue_work('abort')
    
    @define_state
    def transition_to_static(self, notify_queue):
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static', notify_queue)
        
    def leave_transition_to_static(self, notify_queue, _results):
        notify_queue.put(self.device_name)
    
    
class PhotonCounterWorker(Worker):
    def init(self):
        global h5py; import h5_lock, h5py
        global serial; import serial
        global time; import time
        global io; import io
        
    def initialise_photoncounter(self, name, usbport):
        self.device_name = name
        self.ser = serial.Serial(usbport, timeout=1)
        # Confirm that connection is working:      
        self.write('CM 0')
        self.write('CM')
        assert self.read() == '0'

    def write(self, s):
        self.logger.debug('sending: %s'%s)
        self.ser.write(s+'\r')
        
    def read(self):
        """This seemed like the best way to readline when EOL is \r only.
        The method pyserial recommends, the python io module docs warn is unreliable.
        So we'll just roll our own readline function, no big deal."""
        result = ''
        while True:
            char = self.ser.read(1)
            if char == '\r':
                self.logger.debug('read: %s'%result)
                return result
            result += char
            
    def close(self):
        self.ser.close()
        
    def program_buffered(self, h5file):
        self.h5file = h5file
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/%s'%self.device_name]
            
            bin_size_10MHz = group.attrs['bin_size_10MHz']
            n_periods = group.attrs['n_periods']
            dwell_time = group.attrs['dwell_time']
            
        # Set count mode to 'A,B FOR T PRESET'.
        # This also resets the counter ready for a new scan:
        self.write('CM 0')

        # Confirm that connection is working
        self.write('CM')
        assert self.read() == '0'

        # Set dwell time to minimum:
        self.write('DT %.1g'%dwell_time)

        # Tell it to stop when it finishes counting:
        self.write('NE 0')

        # CI i, j: Set Counter A (i=0) to use Input 1 (j = 1)
        self.write('CI 0, 1')

        # CI i, j: Set Counter T (i=2) to use 10MHz (j=0)
        self.write('CI 2, 0')

        # Set the bin size in multiples of the T counter (the 10MHz clock):
        self.write('CP 2, %.1g'%bin_size_10MHz)

        # Set the number of periods in a scan:
        self.write('NP %d'%n_periods)
        
        # save n_periods for later data retrieval:
        self.n_periods = n_periods
        
    def transition_to_static(self):
        self.write('EA')
        data = []
        for i in range(self.n_periods):
            result = self.read()
            data.append(int(result))
        data = numpy.array(data,dtype=int)
        with h5py.File(self.h5file) as f:
            group = f.create_group('/data/%s'%self.device_name)
            group.create_dataset('COUNTS', data=data)
            
    def abort(self):
        self.transition_to_static()
        
        
        
        
        
