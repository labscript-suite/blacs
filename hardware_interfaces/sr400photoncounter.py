import gtk
from output_classes import DO
from tab_base_classes import Tab, Worker, define_state

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
    def transition_to_static(self,notify_queue):
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static', notify_queue)
        
    def leave_transition_to_static(self,notify_queue, _results):
        self.static_mode = True
        notify_queue.put(self.device_name)
    
class PhotonCounterWorker(Worker):
    def init(self):
        global h5py; import h5_lock, h5py
        global serial; import serial
        global time; import time
    
    def initialise_photoncounter(self, name, usbport):
        self.device_name = name
        self.photoncounter = serial.Serial(usbport, 115200, timeout=1)
        
        
        # Device has a finite startup time:
        time.sleep(5)
        self.photoncounter.write('hello\r\n')
        response = self.photoncounter.readline()
        if response == 'hello\r\n':
            return
        elif response:
            raise Exception('PineBlaster is confused: saying %s instead of hello'%(repr(response)))
        else:
            raise Exception('PineBlaster is not saying hello back when greeted politely. How rude. Maybe it needs a reboot.')
            
    def close(self):
        self.photoncounter.close()
        
    def program_buffered(self, h5file, fresh):
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/%s'%self.device_name]
            duration = group.attrs['duration']
        self.photoncounter.write('set duration to %d and get ready to go!\r\n'%duration)
        response = self.photoncounter.readline()
        if response != 'ok\r\n':
            raise Exception(response)
        
    def transition_to_static(self):
        self.photoncounter.write('reset. stop counting. whatever')
        response = self.photoncounter.readline()
        if response != 'ok\r\n':
            raise Exception(response)
            
    def abort(self):
        self.transition_to_static()
        
        
        
        
        
