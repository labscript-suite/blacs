import gtk
from output_classes import DO
from tab_base_classes import Tab, Worker, define_state

class pineblaster(Tab):
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self, BLACS, PineBlasterWorker, notebook, settings)
        self.settings = settings
        self.device_name = settings['device_name']        
        self.usbport = self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection
        self.fresh = True
        self.static_mode = True
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/pineblaster.glade')
        self.builder.connect_signals(self)
        
        self.toplevel = self.builder.get_object('toplevel')
        self.checkbutton_fresh = self.builder.get_object('force_fresh_program')
        self.smart_disabled = self.builder.get_object('hbox_fresh_program')
        self.smart_enabled = self.builder.get_object('hbox_smart_in_use')
        self.builder.get_object('title').set_text(self.settings['device_name'])
        
        self.digital_outs = []
        clock_togglebutton = self.builder.get_object('fast_clock')
        clock_output = DO(self.device_name + '_fast_clock', 'fast clock', clock_togglebutton, self.program_static)
        clock_output.update(settings)
        self.digital_outs.append(clock_output)
        
        # Insert our GUI into the viewport provided by BLACS:
        self.viewport.add(self.toplevel)
        
        # Initialise the Pineblaster:
        self.initialise_pineblaster()
        
        # Program the hardware with the initial values of everything:
        self.program_static()   
        
    @define_state
    def initialise_pineblaster(self):
        self.queue_work('initialise_pineblaster', self.device_name, self.usbport)
        
    @define_state
    def destroy(self):        
        self.queue_work('close')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab() 
    
    @define_state    
    def program_static(self, widget=None):
        pass
        
        
class PineBlasterWorker(Worker):
    def init(self):
        global h5py; import h5_lock, h5py
        global serial; import serial
        self.smart_cache = None
    
    def initialise_pineblaster(self, name, usbport):
        self.device_name = name
        self.pineblaster = serial.Serial(usbport, 115200)
        for i in range(10):
            self.pineblaster.write('hello\r\n')
            result = self.pineblaster.read(timeout=1)
            assert result == 'hello\r\n'
    
    def close(self):
        self.pineblaster.close()
        
    def program_static(self, values):
        pass
        
    def program_buffered(self):
        pass
