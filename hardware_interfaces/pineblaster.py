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
    def toggle_fresh(self, button):
        # When the user clicks the checkbutton to enable and disable
        # smart programming:
        if button.get_active():
            self.smart_enabled.hide()
            self.smart_disabled.show()
            self.fresh = True
        else:
            self.smart_enabled.show()
            self.smart_disabled.hide()
            self.fresh = False
            
    @define_state    
    def program_static(self, widget=None):
        if self.static_mode:
            self.queue_work('program_static', self.digital_outs[0].state)
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False
        self.digital_outs[0].set_state(0,program=False)
        self.queue_work('program_buffered', h5file, self.fresh)
        self.do_after('leave_program_buffered', notify_queue)
    
    def leave_program_buffered(self, notify_queue, _results):
        # Enable smart programming:
        self.checkbutton_fresh.show() 
        self.checkbutton_fresh.set_active(False) 
        self.checkbutton_fresh.toggled()
        # Notify the queue manager thread that we've finished
        # transitioning to buffered:
        notify_queue.put(self.device_name)
    
    @define_state
    def abort_buffered(self):
        self.queue_work('abort')
        self.checkbutton_fresh.set_active(False) 
        self.checkbutton_fresh.hide()
        self.checkbutton_fresh.toggled()
    
    @define_state
    def transition_to_static(self,notify_queue):
        self.static_mode = True
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static', notify_queue)
        
    def leave_transition_to_static(self,notify_queue, _results):
        self.static_mode = True
        self.digital_outs[0].set_state(0)
        notify_queue.put(self.device_name)
    
    @define_state
    def start_run(self, notify_queue):
        self.queue_work('start_run')
        self.statemachine_timeout_add(1,self.status_monitor, notify_queue)
    
    @define_state
    def status_monitor(self, notify_queue):
        self.queue_work('status_monitor')
        self.do_after('leave_status_monitor', notify_queue)
        
    def leave_status_monitor(self, notify_queue, _results):
        if _results:
            # experiment is over:
            self.timeouts.remove(self.status_monitor)
            notify_queue.put(self.device_name)
            
class PineBlasterWorker(Worker):
    def init(self):
        global h5py; import h5_lock, h5py
        global serial; import serial
        global time; import time
        self.smart_cache = []
    
    def initialise_pineblaster(self, name, usbport):
        self.device_name = name
        self.pineblaster = serial.Serial(usbport, 115200, timeout=1)
        # Device has a finite startup time:
        time.sleep(5)
        self.pineblaster.write('hello\r\n')
        response = self.pineblaster.readline()
        if response == 'hello\r\n':
            return
        elif response:
            raise Exception('PineBlaster is confused: saying %s instead of hello'%(repr(response)))
        else:
            raise Exception('PineBlaster is not saying hello back when greeted politely. How rude. Maybe it needs a reboot.')
            
    def close(self):
        self.pineblaster.close()
        
    def program_static(self, value):
        self.pineblaster.write('go high\r\n' if value else 'go low\r\n')
        response = self.pineblaster.readline()
        assert response == 'ok\r\n', 'PineBlaster said \'%s\', expected \'ok\''%repr(response)
        
    def program_buffered(self, h5file, fresh):
        if fresh:
            self.smart_cache = []
        self.program_static(0)
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/%s'%self.device_name]
            pulse_program = group['PULSE_PROGRAM'][:]
            self.is_master_pseudoclock = group.attrs['is_master_pseudoclock']
        for i, instruction in enumerate(pulse_program):
            if i == len(self.smart_cache):
                # Pad the smart cache out to be as long as the program:
                self.smart_cache.append(None)
            # Only program instructions that differ from what's in the smart cache:
            if self.smart_cache[i] != instruction:
                self.pineblaster.write('set %d %d %d\r\n'%(i, instruction['period'], instruction['reps']))
                response = self.pineblaster.readline()
                assert response == 'ok\r\n', 'PineBlaster said \'%s\', expected \'ok\''%repr(response)
                self.smart_cache[i] = instruction
        if not self.is_master_pseudoclock:
            # Get ready for a hardware trigger:
            self.pineblaster.write('hwstart\r\n')
            response = self.pineblaster.readline()
            assert response == 'ok\r\n', 'PineBlaster said \'%s\', expected \'ok\''%repr(response)
            
    def start_run(self):
        # Start in software:
        self.pineblaster.write('start\r\n')
        response = self.pineblaster.readline()
        assert response == 'ok\r\n', 'PineBlaster said \'%s\', expected \'ok\''%repr(response)
    
    def status_monitor(self):
        # Wait to see if it's done within the timeout:
        response = self.pineblaster.readline()
        if response:
            assert response == 'done\r\n'
            return True
        return False
        
    def transition_to_static(self):
        # Wait until the pineblaster says it's done:
        if not self.is_master_pseudoclock:
            # If we're the master pseudoclock then this already happened
            # in status_monitor, so we don't need to do it again
            response = self.pineblaster.readline()
            assert response == 'done\r\n', 'PineBlaster said \'%s\', expected \'ok\''%repr(response)
            print 'done!'
        
    def abort(self):
        self.pineblaster.write('restart\r\n')
        time.sleep(5)
        
        
        
        
        
        
            
