import gtk
from output_classes import AO
from tab_base_classes import Tab, Worker, define_state
import subproc_utils

class adwin_ao_card(Tab):
    num_DO = 0
    num_AO = 8
    num_RF = 0
    num_AI = 0
    max_ao_voltage = 10.0
    min_ao_voltage = -10.0
    ao_voltage_step = 0.1
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,ADWinAOCardWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.device_number, self.card_number = eval(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
        self.static_mode = True
        self.static_updates_queued = 0
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/adwin_ao_card.glade')
        self.builder.connect_signals(self)   
        self.toplevel = self.builder.get_object('toplevel')
            
        self.analog_outs = []
        self.analog_outs_by_channel = {}
        for i in range(self.num_AO):
            # Get the widgets:
            spinbutton = self.builder.get_object("AO_value_%d"%(i+1))
            combobox = self.builder.get_object('ao_units_%d'%(i+1))
            channel = str(i+1)
            device = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
            name = device.name if device else '-'
                
            # store widget objects
            self.builder.get_object("AO_label_a"+str(i+1)).set_text("AO"+str(i+1))            
            self.builder.get_object("AO_label_b"+str(i+1)).set_text(name)            
            
            # Setup unit calibration:
            calib = None
            calib_params = {}
            def_calib_params = "V"
            if device:
                # get the AO from the connection table, find its calibration details
                calib = device.unit_conversion_class
                calib_params = eval(device.unit_conversion_params)
            
            output = AO(name, channel,spinbutton, combobox, calib, calib_params, def_calib_params, self.program_static, self.min_ao_voltage, self.max_ao_voltage, self.ao_voltage_step)
            output.update(settings)
                    
            self.analog_outs.append(output)
            self.analog_outs_by_channel[channel] = output
            
        self.viewport.add(self.toplevel)
        self.initialise_device()
        self.program_static() 
    
    @define_state
    def initialise_device(self):
        self.queue_work('initialise', self.device_number, self.card_number)
        
    def get_front_panel_state(self):
        state = {}
        for i in range(self.num_AO):
            state["AO"+str(i)] = self.analog_outs[i].value
        return state
    
    def program_static(self, output=None):
        # Don't allow events to pile up; only two allowed in the queue at a time.
        # self.get_front_panel_state() is only called when program_static_state() runs, and so
        # the effect of clicking many times quickly is that only the first and last updates happen.
        # This is usually what you want, if you click n times, the result is that the last click you
        # made is the one which is programmed.
        if self.static_updates_queued < 2:
            self.static_updates_queued += 1
            self.program_static_state()
             
    @define_state
    def program_static_state(self,output=None):
        if self.static_mode:
            self.queue_work('program_static',[output.value for output in self.analog_outs])
            self.do_after('leave_program_static')
            
    def leave_program_static(self, _results):
        # Keep track of how many program_static events are in the queue:
        self.static_updates_queued -= 1
        if self.static_updates_queued <0:
            self.static_updates_queued = 0
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False
        # Don't have to do anything, all the programming happens in the
        # parent ADWin tab.  So we're done here.
        notify_queue.put(self.device_name)
    
    @define_state
    def abort_buffered(self):      
        self.static_mode = True
        # Again, we don't have to do anything
        pass
    
    @define_state        
    def transition_to_static(self, notify_queue):
        self.static_mode = True
        # Do we need to do anything here? Update the outputs?
        
#        self.queue_work('transition_to_static')
#        self.do_after('leave_transition_to_static',notify_queue)
#        # Update the GUI with the final values of the run:
#        for channel, value in self.final_values.items():
#            self.analog_outs_by_channel[channel].set_value(value,program=False)
        
    
                    
    @define_state
    def destroy(self):
        self.destroy_complete = True
        self.close_tab() 
        
class ADWinAOCardWorker(Worker):
    def initialise(self, device_number, card_number):
        self.device_number = device_number
        self.card_number = card_number
        self.request_static_update = subproc_utils.Event('ADWin_static_update_request', type='post')
        self.static_update_complete = subproc_utils.Event('ADWin_static_update_complete', type='wait')
        
    def program_static(self, values):
        # Post an event asking for the server (running in the ADWin main
        # tab) to do a static update. Ensure it is directed only at the
        # adwin with the correct device number:
        self.request_static_update.post(id=self.device_number, data={'type':'analog', 'card': self.card_number,'values':values})
        # Wait for a response. id of event is the device and card number, so we don't respond to events directed at other cards/devices:
        result = self.static_update_complete.wait(id=[self.device_number, self.card_number])
        if isinstance(result, Exception):
            raise result
        
        
