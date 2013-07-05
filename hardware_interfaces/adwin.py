import gtk
import threading
from output_classes import AO
from tab_base_classes import Tab, Worker, define_state
import subproc_utils
import h5py
import numpy
import time

class adwin(Tab):
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,ADWinWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.device_number = int(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
        self.static_mode = True
        self.destroy_complete = False
        # A dict to store the last requested static update values for
        # each card. This is so that this tab can set these values
        # itself in the case of a reboot:
        if 'last_seen_values' not in self.settings:
            self.settings['last_seen_values'] = {}
        
        # Gtk stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/adwin.glade')
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text('%s: device no %d'%(self.device_name, self.device_number))
        self.device_responding = self.builder.get_object('responding')
        self.device_notresponding = self.builder.get_object('notresponding')
        self.device_working = self.builder.get_object('working')
        self.entry_boot_image = self.builder.get_object('entry_boot_image')
        self.entry_process_1 = self.builder.get_object('entry_process_1')
        self.entry_process_2 = self.builder.get_object('entry_process_2')
        self.viewport.add(self.toplevel)
        self.restore_save_data()
        self.builder.connect_signals(self)
        
        self.static_update_request = subproc_utils.Event('ADWin_static_update_request', type='wait')
        self.static_update_complete = subproc_utils.Event('ADWin_static_update_complete', type='post')
        
        # start the thread that will handle requests for output updates from the other tabs:
        request_handler_thread = threading.Thread(target=self.request_handler_loop)
        request_handler_thread.daemon = True
        request_handler_thread.start()
        
        self.initialise_device()

    def get_save_data(self):
        return {'boot image': self.entry_boot_image.get_text(),
                'process 1': self.entry_process_1.get_text(),
                'process 2': self.entry_process_2.get_text()}
    
    def restore_save_data(self):
        save_data = self.settings['saved_data']
        if save_data:
            if save_data['boot image'] is not None:
                self.entry_boot_image.set_text(save_data['boot image'])
            if save_data['process 1'] is not None:
                self.entry_process_1.set_text(save_data['process 1'])
            if save_data['process 2'] is not None:
                self.entry_process_2.set_text(save_data['process 2'])
        else:
            self.logger.warning('No previous front panel state to restore')
    
    @define_state
    def on_change_firmware_paths(self, widget):
        # Save settings so that a tab restart doesn't lose them:
        self.settings['saved_data'] = self.get_save_data()
    
        
    def request_handler_loop(self):
        """Simply collects static_update requests from other calling
        processes/threads and translates them into static update calls
        here"""
        while True:
            data = self.static_update_request.wait(id=self.device_number)
            self.static_update(data)
            # Cache this request so the latest request on each card can be re-executed in the case of a reboot:
            self.settings['last_seen_values'][data['card']] = data
            
    @define_state
    def static_update(self, data, response_required=True):
        if data['type'] == 'analog':
            self.queue_work('analog_static_update', data['card'], data['values'])
        elif data['type'] == 'digital':
            self.queue_work('digital_static_update', data['card'], data['values'])
        if response_required:
            # If this update was internally generated instead of being
            # requested by another tab, we don't need to respond to
            # the tab that originally requested it. In fact responding
            # might confuse future requests from that tab (it shouldn't,
            # as requests have unique numerical ids, but still).
            self.do_after('post_update_done', data['card'], data['request_number'])
        
    def post_update_done(self, card, request_number, _results):
        """Tells the caller that their static update has been processed"""
        if _results is not None:
            response = True
        else:
            # The update did not complete properly:
            response = Exception('Setting the device output did not complete correctly.' +
                                 'Please see the corresponding ADWin tab for more info.')
        self.static_update_complete.post(id=[self.device_number, card, request_number],data=response)
    
    def on_boot_button_clicked(self, button):
        self.initialise_device()
            
    @define_state
    def initialise_device(self):
        boot_image_path = self.entry_boot_image.get_text()
        process_1_image_path = self.entry_process_1.get_text()
        process_2_image_path = self.entry_process_2.get_text()
        paths = [boot_image_path, process_1_image_path, process_2_image_path]
        if any([path is None for path in [boot_image_path, process_1_image_path, process_2_image_path]]):
            return
        self.device_responding.hide()
        self.device_notresponding.hide()
        self.device_working.show()
        self.queue_work('initialise', self.device_name, self.device_number, 
                        boot_image_path, process_1_image_path, process_2_image_path)
        self.do_after('after_initialise_device')
        
    def after_initialise_device(self, _results):
        self.device_working.hide()
        if _results:
            self.restore_cached_output_values()
            self.device_responding.show()
            self.device_notresponding.hide()
        else:
            self.device_responding.hide()
            self.device_notresponding.show()
    
    def restore_cached_output_values(self):
        """In case of a restart of the tab or a reboot of the adwin, we
        wish to restore the output values that the other tabs requested
        in the past. Rather than communicate with the tabs, we have
        stored the last request from each one. So this function simply
        calls self.static_update for each one of these stored requests"""
        for card, data in self.settings['last_seen_values'].items():
            self.static_update(data, response_required=False)
            
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False
        self.queue_work('program_buffered', h5file)
        self.do_after('leave_transition_to_buffered', notify_queue)

    @define_state
    def abort_buffered(self):      
        self.static_mode = True
        # We don't have to do anything
        pass
           
    @define_state
    def leave_transition_to_buffered(self, notify_queue, _results):
        self.static_mode = True
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
        if _results is True or _results is None:
            # experiment is over or we got an exception:
            self.timeouts.remove(self.status_monitor)
            notify_queue.put(self.device_name)
     
    @define_state
    def transition_to_static(self, notify_queue):
        self.static_mode = True
        # We don't need to do anything:
        notify_queue.put(self.device_name)
                     
    @define_state
    def destroy(self):
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
        
    
class ADWinWorker(Worker):

    CPU_FREQ = 300e6 # Hz
    
    ADWIN_CURRENT_TIME = 1
    ADWIN_TOTAL_TIME = 2
    ADWIN_CYCLE_DELAY = 4
    ADWIN_NEW_DATA = 5
    ADWIN_RUN_NUMBER = 6
    
    ANALOG_TIMEPOINT = 1
    ANALOG_DURATION = 2
    ANALOG_CARD_NUM = 3
    ANALOG_CHAN_NUM = 4
    ANALOG_RAMP_TYPE = 5
    ANALOG_PAR_A = 6
    ANALOG_PAR_B = 7
    ANALOG_PAR_C = 8
    
    DIGITAL_TIMEPOINT = 10
    DIGITAL_CARD_NUM = 11
    DIGITAL_VALUES = 12
    

    def init(self):
        global ADwin; import ADwin
        
    def initialise(self, device_name, device_number, boot_image_path, process_1_image_path, process_2_image_path):
        self.device_name = device_name
        self.aw = ADwin.ADwin(device_number)

    
        self.aw.Boot(boot_image_path)
        self.aw.Load_Process(process_1_image_path)
        self.aw.Load_Process(process_2_image_path)
        self.aw.Start_Process(1)
        self.aw.Start_Process(2)
        return True # indicates success


    def analog_static_update(self, card, voltages):
        output_values = []
        # Convert the output values to integers as required by the API:
        for voltage in voltages:
            if not -10 <= voltage <= 10:
                raise ValueError('voltage not in range [-10,10]:' + str(voltage))
            output_value = int((voltage+10)/20.*(2**16-1))
            output_values.append(output_value)
        for i, output_value in enumerate(output_values):
            chan = array_index = i+1 # ADWin uses indexing that starts from one
            
            # Set the timepoint:
            self.aw.SetData_Long([0], self.ANALOG_TIMEPOINT, Startindex=array_index, Count=1)
            # The duration, minimum possible; 1 cycle:
            self.aw.SetData_Long([1], self.ANALOG_DURATION, Startindex=array_index, Count=1)
            # The card_number and channel:
            self.aw.SetData_Long([card], self.ANALOG_CARD_NUM, Startindex=array_index, Count=1)
            self.aw.SetData_Long([chan], self.ANALOG_CHAN_NUM, Startindex=array_index, Count=1)
            # The ramp type and parameters such as to create just a constant
            # value through use of a trivial linear ramp:
            self.aw.SetData_Long([0], self.ANALOG_RAMP_TYPE, Startindex=array_index, Count=1)
            self.aw.SetData_Long([output_value], self.ANALOG_PAR_A, Startindex=array_index, Count=1)
            self.aw.SetData_Long([0], self.ANALOG_PAR_B, Startindex=array_index, Count=1)
            self.aw.SetData_Long([output_value], self.ANALOG_PAR_C, Startindex=array_index, Count=1)
        # And now the stop instruction:
        array_index += 1
        self.aw.SetData_Long([2147483647], self.ANALOG_TIMEPOINT, Startindex=array_index, Count=1)
        # Set the total cycle time, a small number:
        self.aw.Set_Par(self.ADWIN_TOTAL_TIME, 2)
        # Set the delay, large enough for all the channels to be programmed:
        self.aw.Set_Par(self.ADWIN_CYCLE_DELAY, 3000) # 10us
        # Tell the program that there is new data:
        self.aw.Set_Par(self.ADWIN_NEW_DATA, 1)
        return True # indicates success


    def digital_static_update(self, card, values):
        output_values = 0
        # Convert the digital values to an integer bitfield as required by the API:
        for i, value in enumerate(values):
            if value:
                output_values += 2**i
        # Set the timepoint:
        self.aw.SetData_Long([0], self.DIGITAL_TIMEPOINT, Startindex=1, Count=1)
        # The card_number:
        self.aw.SetData_Long([card], self.DIGITAL_CARD_NUM, Startindex=1, Count=1)
        # The output values:
        self.aw.SetData_Long([output_values], self.DIGITAL_VALUES, Startindex=1, Count=1)
        # And now the stop instruction:
        self.aw.SetData_Long([2147483647], self.DIGITAL_TIMEPOINT, Startindex=2, Count=1)
        # Set the total cycle time, a small number:
        self.aw.Set_Par(self.ADWIN_TOTAL_TIME, 2)
        # Set the delay, some small value:
        self.aw.Set_Par(self.ADWIN_CYCLE_DELAY, 3000)
        # Tell the program that there is new data:
        self.aw.Set_Par(self.ADWIN_NEW_DATA, 1)
        return True # indicates success
        
        
    def program_buffered(self, h5file):
        with h5py.File(h5file) as f:
            # Get the instructions:
            group = f['devices'][self.device_name]
            analog_table = numpy.array(group['ANALOG_OUTS'])
            digital_table = numpy.array(group['DIGITAL_OUTS'])
            cycle_time = group.attrs['cycle_time']
            stop_time = group.attrs['stop_time']
        
        # Program the analog out table:
        self.aw.SetData_Long(list(analog_table['t']), self.ANALOG_TIMEPOINT, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['duration']), self.ANALOG_DURATION, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['card']), self.ANALOG_CARD_NUM, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['channel']), self.ANALOG_CHAN_NUM, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['ramp_type']), self.ANALOG_RAMP_TYPE, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['A']), self.ANALOG_PAR_A, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['B']), self.ANALOG_PAR_B, Startindex=1, Count=len(analog_table))
        self.aw.SetData_Long(list(analog_table['C']), self.ANALOG_PAR_C, Startindex=1, Count=len(analog_table))
    
        # Program the digital out table:
        self.aw.SetData_Long(list(digital_table['t']), self.DIGITAL_TIMEPOINT, Startindex=1, Count=len(digital_table))
        self.aw.SetData_Long(list(digital_table['card']), self.DIGITAL_CARD_NUM, Startindex=1, Count=len(digital_table))
        self.aw.SetData_Long(list(digital_table['bitfield']), self.DIGITAL_VALUES, Startindex=1, Count=len(digital_table))
        
        # Set the total run time:
        self.aw.Set_Par(self.ADWIN_TOTAL_TIME, int(stop_time))

        # set the cycle delay in multiples of cpu ticks:
        self.aw.Set_Par(self.ADWIN_CYCLE_DELAY, int(round(cycle_time*self.CPU_FREQ)))
        
    def start_run(self):
        # Say go!
        self.aw.Set_Par(self.ADWIN_NEW_DATA, 1)
            
    def status_monitor(self):
        # Are we done? Check every 0.1 seconds for 2 seconds:
        start_time = time.time()
        while time.time() < start_time + 2:
            time.sleep(0.1)
            current_time = self.aw.Get_Par(self.ADWIN_CURRENT_TIME)
            total_time = self.aw.Get_Par(self.ADWIN_TOTAL_TIME)
            has_started_this_run = not self.aw.Get_Par(self.ADWIN_NEW_DATA)
            # We want to detect that the run has started (by looking at
            # the new data field) and that it finished (by looking to see if
            # the current time of the run equals the total time). If we
            # only check the latter we get false positives due to the
            # times remaining from the previous run.
            if has_started_this_run and current_time == total_time:
                return True
        return False
        
