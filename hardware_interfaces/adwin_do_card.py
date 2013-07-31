import gtk
from output_classes import DO
from tab_base_classes import Tab, Worker, define_state
import subproc_utils
import itertools

class adwin_do_card(Tab):
    num_DO = 32
    num_AO = 0
    num_RF = 0
    num_AI = 0
    max_ao_voltage = 10.0
    min_ao_voltage = -10.0
    ao_voltage_step = 0.1
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,ADWinDOCardWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.device_number, self.card_number = eval(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
        self.static_mode = True
        self.static_updates_queued = 0
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/adwin_do_card.glade')
        self.builder.connect_signals(self)   
        self.toplevel = self.builder.get_object('toplevel')
        
        self.digital_outs = []
        self.digital_outs_by_channel = {}    
        for i in range(self.num_DO):
            # get the widget:
            toggle_button = self.builder.get_object("do_toggle_%d"%(i+1))
		
            #programatically change labels!
            channel_label= self.builder.get_object("do_hardware_label_%d"%(i+1))
            name_label = self.builder.get_object("do_real_label_%d"%(i+1))
            
            channel_label.set_text("DO"+str(i+1))
            channel = str(i+1)
            
            device = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
            name = device.name if device else '-'
            
            name_label.set_text(name)
            
            output = DO(name, channel, toggle_button, self.program_static)
            output.update(settings)
            
            self.digital_outs.append(output)
            self.digital_outs_by_channel[channel] = output
            
        self.viewport.add(self.toplevel)
        self.initialise_device()
        self.program_static() 
    
    @define_state
    def initialise_device(self):
        self.queue_work('initialise', self.device_number, self.card_number)
        
    def get_front_panel_state(self):
        state = {}
        for i in range(self.num_AO):
            state["DO"+str(i)] = self.digital_outs[i].state
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
            self.queue_work('program_static',[output.state for output in self.digital_outs])
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
                    
    @define_state
    def destroy(self):
        self.destroy_complete = True
        self.close_tab() 
        
class ADWinDOCardWorker(Worker):
    def initialise(self, device_number, card_number):
        self.device_number = device_number
        self.card_number = card_number
        self.request_static_update = subproc_utils.Event('ADWin_static_update_request', type='post')
        self.static_update_complete = subproc_utils.Event('ADWin_static_update_complete', type='wait')
        # We need a sequence number so that we don't respond to old
        # events thinking they are new ones in the case that another tab
        # is out of step with our requests (say in the case of this tab
        # restarting while the parent adwin is still processing an event)
        self.request_number_generator = itertools.count()
        
    def program_static(self, values):
        # Post an event asking for the server (running in the ADWin main
        # tab) to do a static update. Ensure it is directed only at the
        # adwin with the correct device number:
        request_number = self.request_number_generator.next()
        self.request_static_update.post(id=self.device_number, data={'type':'digital', 'card': self.card_number,'values':values, 'request_number': request_number})
        # Wait for a response. id of event is the device and card number, so we don't respond to events directed at other cards/devices:
        result = self.static_update_complete.wait(id=[self.device_number, self.card_number, request_number])
        if isinstance(result, Exception):
            raise result
        
        
