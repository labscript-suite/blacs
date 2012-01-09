from hardware_interfaces.output_types.RF import *
from hardware_interfaces.output_types.DO import *
from hardware_interfaces.output_types.DDS import *



import gtk
import time
import h5py

from tab_base_classes import Tab, Worker, define_state

class pulseblaster(Tab):

    # settings should contain a dictionary of information from the connection table, relevant to this device.
    # aka, it could be parent: pb_0/flag_0 (pseudoclock)
    #                  device_name: ni_pcie_6363_0
    #
    # or for a more complex device,
    #   parent:
    #   name:
    #   com_port:
    #
    #
    def __init__(self,notebook,settings,restart=False):
        # is the init method finished...no!
        self.init_done = False
        self.static_mode = False
        self.destroy_complete = False
        
        Tab.__init__(self,PulseblasterWorker,notebook,settings)
        
        
        # Capabilities
        self.num_RF = 2
        self.num_DO = 4 #sometimes might be 12
        self.num_DO_widgets = 12
        
        self.freq_min = 0.0000003   # In MHz
        self.freq_max = 150.0       # In MHz
        self.amp_min = 0.0          # In Vpp
        self.amp_max = 1.0          # In Vpp
        self.phase_min = 0          # In Degrees
        self.phase_max = 360        # In Degrees
        
        self.settings = settings
        self.device_name = settings["device_name"]        
        self.pb_num = int(settings["device_num"])
        

        
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/pulseblaster.glade')
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text(self.settings["device_name"])
        
        
        self.dds_widgets = []
        self.rf_do_outputs = []
        self.rf_outputs = []
        self.dds_outputs = []
        for i in range(0,self.num_RF):
            w1 = self.builder.get_object("freq_chnl_"+str(i))
            w2 = self.builder.get_object("amp_chnl_"+str(i))
            w3 = self.builder.get_object("phase_chnl_"+str(i))
            w4 = self.builder.get_object("active_chnl_"+str(i))
            
            self.dds_widgets.append([w1,w2,w3,w4])
            
            hardware_name = "DDS "+str(i)
            channel_name = self.settings["connection_table"].find_child(self.settings["device_name"],"dds "+str(i))
            if channel_name is not None:
                real_name = " - "+channel_name.name
            else:
                real_name = ""
            self.builder.get_object("channel_"+str(i)+"_label").set_text(hardware_name + real_name)
            
            # Make RF objects
            self.rf_outputs.append(RF(self,self.static_update,self.program_static,i,hardware_name,real_name,[self.freq_min,self.freq_max,self.amp_min,self.amp_max,self.phase_min,self.phase_max]))
            # Make DO control object for RF channels
            self.rf_do_outputs.append(DO(self,self.static_update,self.program_static,i,hardware_name + " active",real_name + " active"))
            # Make DDS object
            self.dds_outputs.append(DDS(self,self.rf_outputs[i],self.rf_do_outputs[i]))            
            # Set defaults
            self.rf_outputs[i].update_value(settings["f"+str(i)],settings["a"+str(i)],settings["p"+str(i)])  
        
        
        # Make flag DO outputs
        self.do_widgets = []
        self.do_outputs = []
        for i in range(0,self.num_DO_widgets):
            #Active widgets
            if i < self.num_DO:
                # save toggle widgets
                self.do_widgets.append(self.builder.get_object("flag_"+str(i)))
                
                
                
                # set label text
                temp = self.builder.get_object("flag_hardware_label_"+str(i))
                temp.set_text("Flag "+str(i))
                temp2 = self.builder.get_object("flag_real_label_"+str(i))
                
                channel_name = self.settings["connection_table"].find_child(self.settings["device_name"],"flag "+str(i))
                if channel_name is not None:
                    real_name = channel_name.name
                else:
                    real_name = "-"
                
                temp2.set_text(real_name)
                
                # create DO object
                self.do_outputs.append(DO(self,self.static_update,self.program_static,i,temp.get_text(),real_name))
            
            # inactive widgets
            else:
                #self.builder.get_object("flag_"+str(i)).set_sensitive(False)
                self.builder.get_object("flag_"+str(i)).hide()
                # set label text
                temp = self.builder.get_object("flag_hardware_label_"+str(i))
                temp.set_text("Flag "+str(i))
                temp2 = self.builder.get_object("flag_real_label_"+str(i))
                temp2.set_text("")
   
        # Status Monitor timeout check
        self.statemachine_timeout_add(2000, self.status_monitor)
        
        # Set up status monitor
        self.status = {"stopped":False,"reset":False,"running":False, "waiting":False}
        # Save status widgets
        self.status_widgets = {"stopped_yes":self.builder.get_object('stopped_yes'),
                               "stopped_no":self.builder.get_object('stopped_no'),
                               "reset_yes":self.builder.get_object('reset_yes'),
                               "reset_no":self.builder.get_object('reset_no'),
                               "running_yes":self.builder.get_object('running_yes'),
                               "running_no":self.builder.get_object('running_no'),
                               "waiting_yes":self.builder.get_object('waiting_yes'),
                               "waiting_no":self.builder.get_object('waiting_no')}
        
                
        self.toplevel.hide()
        self.viewport.add(self.toplevel)
        
        self.initialise_pulseblaster()
        self.set_defaults()  
        
        
        # Need to connect signals!
        self.builder.connect_signals(self)
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method cleans up the class before the program exits. In this case, we close the worker thread!
    #
    @define_state
    def destroy(self):        
        #gtk.timeout_remove(self.timeout)
        self.queue_work('close_pulseblaster')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method sets the values of front panel controls to "defaults"
    #
    @define_state
    def set_defaults(self):    
        for i in range(0,self.num_RF):
            self.rf_outputs[i].update_value(self.settings["f"+str(i)],self.settings["a"+str(i)],self.settings["p"+str(i)])
        
        
        self.toplevel.show()
        self.init_done = True
        self.static_mode = True
    
    @define_state
    def initialise_pulseblaster(self):
        self.queue_work('initialise_pulseblaster', self.pb_num)
    
    # Dummy function!
    def ignore_update(self,output):
        pass
    
    # 
    # This function gets the status of the Pulseblaster from the spinapi, and updates the front panel widgets!
    #
    @define_state
    def status_monitor(self,notify_queue=None):
        self.queue_work('get_status')
        self.do_after('status_monitor_leave',notify_queue)
        
    def status_monitor_leave(self,notify_queue,_results):
        # When called with a queue, this function writes to the queue when the pulseblaster is waiting. This indicates the end of an experimental run.
        self.status = _results
        print self.status
        print self.timeout_ids
        if notify_queue is not None and self.status["waiting"]:
            # Experiment is over. Tell the queue manager about it, then set the status checking timeout back to every 2 seconds with no queue.
            notify_queue.put('done')
            self.timeouts.remove(self.status_monitor)
            self.statemachine_timeout_add(2000,self.status_monitor)
        # Update widgets
        a = ["stopped","reset","running","waiting"]
        for name in a:
            if self.status[name] == True:
                self.status_widgets[name+"_no"].hide()
                self.status_widgets[name+"_yes"].show()
            else:                
                self.status_widgets[name+"_no"].show()
                self.status_widgets[name+"_yes"].hide()
        
        if not self.status["running"]:
            pass
            #raise Exception('Pulseblaster is not running')
        
    def get_front_panel_state(self):
        return {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "en0":self.dds_outputs[0].do.state,
                "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "en1":self.dds_outputs[1].do.state,
                "flags":int(self.encode_flags(),2)}
        
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Returns the status of the device. Is it ready for transition to buffered?
    #
    #def ready(self):
    #    if self.status["running"] and not self.status["stopped"] and not self.status["reset"] and not self.status["waiting"] and self.static_mode and self.init_done:
    #        return True
    #    return False
    
    #
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    #
    # Static update of hardware (unbuffered)
    #
    # This does not run until the initialisation is complete
    # This does not run if we have transitioned to buffered mode!
    #
    @define_state
    def static_update(self,output):
        # if the init isn't done, skip this!
        if not self.init_done or not self.static_mode:
            return
        
        channel = None      
        # is it a DO update or a DDS update?
        if isinstance(output,RF):
            search_array = self.dds_outputs
            for i in range(0,len(search_array)):
                if output == search_array[i].rf:
                    channel = i
                    # This is a hack until I sort out GTK signals for the DDS object which is a composite DO/RF output type
                    output = search_array[i]
                    break
        elif isinstance(output,DO):
            search_array = self.do_outputs
        
            # search for the output that has been updated, so we can get the right widget to update
        
            for i in range(0,len(search_array)):
                if output == search_array[i]:
                    channel = i
                    break
                
        if channel is None:
            #return error
            return

        # Update GUI    
        if isinstance(output,DDS):
            if self.dds_widgets[channel][0].get_value() != output.rf.freq:         
                self.dds_widgets[channel][0].set_value(output.rf.freq)
            
            if self.dds_widgets[channel][1].get_value() != output.rf.amp:
                self.dds_widgets[channel][1].set_value(output.rf.amp)
                    
            if self.dds_widgets[channel][2].get_value() != output.rf.phase:
                self.dds_widgets[channel][2].set_value(output.rf.phase)
                
            if self.dds_widgets[channel][3].get_active() != output.do.state:
                self.dds_widgets[channel][3].set_active(output.do.state)
                
        elif isinstance(output,DO):
            if self.do_widgets[channel].get_active() != output.state:
                self.do_widgets[channel].set_active(output.state)
        
        
    @define_state
    def program_static(self,output):
        # if the init isn't done, skip this!
        if not self.init_done or not self.static_mode:
            return
        
        # put all the data from self.dds_outputs in a dict!
        dds_outputs = {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "en0":self.dds_outputs[0].do.state,
                      "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "en1":self.dds_outputs[1].do.state}
                      
        self.queue_work('program_static',dds_outputs,self.encode_flags())
    #
    # This function takes the values of the DO controls, and builds a binary flag bit string suitable to send to the spinapi
    #    
    def encode_flags(self):
        #encode flags
        flags_string = ''        
        #functioning channels            
        for i in range(0,self.num_DO):
            if self.do_outputs[i].state:
                flags_string = flags_string + '1'
            else:
                flags_string = flags_string + '0'        
        # Non functioning channels
        for i in range(self.num_DO,self.num_DO_widgets-self.num_DO):
            flags_string = flags_string+'0'
            
        return flags_string
    
    #
    # This method starts the pulseblaster. It is currently only used at the end of an experimental sequence
    # to kick the pulseblaster back into static mode.
    #
    @define_state
    def start(self,*args):
        self.queue_work('start2')
    
    @define_state
    def stop(self,*args):
        self.queue_work('stop2')
    
    @define_state    
    def reset(self,*args):
        self.queue_work('reset2')
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Program experimental sequence
    #
    # Needs to handle seamless transition from static to experiment sequence
    #
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        # disable static update
        if not self.status["running"]:
            now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
            raise Exception('\nWarning - %s:\n' % now +
                           "Pulseblaster is not running, queue is now paused.\n" +
                           "To run your experiment, please start the pulseblaster and unpause the queue.")
            while self.error.startswith('\n'):
                self.error = self.error[1:]            
                self.errorlabel.set_markup(self.error)
                self.notresponding.show()
        
        self.static_mode = False 
        
        initial_values = {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "ddsen0":self.dds_outputs[0].do.state,
                          "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "ddsen1":self.dds_outputs[1].do.state,
                          "flags":self.encode_flags()}
        self.queue_work('program_buffered',h5file,initial_values)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        self.last_instruction = _results
        # Notify the queue manager thread that we've finished transitioning to buffered:
        notify_queue.put(self.device_name)
       
       
    def abort_buffered(self):
        # All these get queued up in the state machine, they all have @define_state:
        self.stop()     
        self.abort_buffered2()
        self.start()
        self.abort_buffered_complete()
        
    @define_state
    def abort_buffered2(self):
        dds_outputs = {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "en0":self.dds_outputs[0].do.state,
                      "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "en1":self.dds_outputs[1].do.state}         
        self.queue_work('program_static',dds_outputs,self.encode_flags())
    
    @define_state    
    def abort_buffered_complete(self):    
        #reenable static updates triggered by GTK events
        self.static_mode = True
    
    @define_state
    def start_run(self, notify_queue):
        self.timeouts.remove(self.status_monitor)
        self.start()
        self.statemachine_timeout_add(50,self.status_monitor,notify_queue)
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # return to unbuffered (static) mode
    #
    # Needs to handle seamless transition from experiment sequence to static mode
    #
    def transition_to_static(self,notify_queue):
        # These all get queued up in the state machine, they all have @define_state:
        self.transition_to_static2()
        self.start()
        self.transition_to_static_complete(notify_queue)
        
    @define_state    
    def transition_to_static2(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is sending out updates.
        #update values on GUI to last instruction (this is a little inefficient!)
        a = self.last_instruction
        #DDS Channels
        self.dds_outputs[0].update_value(a[3],a[0],a[1],a[2])
        self.dds_outputs[1].update_value(a[7],a[4],a[5],a[6])         
        
        # convert flags to a string
        # remove 0b at the start of string
        flags = bin(a[8])[2:]
        # prepend any missing zeros
        for i in range(0,self.num_DO-len(flags)):
            flags = '0' + flags
        
        # reverse string
        flags = flags[::-1]
        
        # Update DO flags
        for i in range(0,self.num_DO):
            self.do_outputs[i].update_value(flags[i])
        
        # Make sure the PB is programmed before we call pb_start(), we can't be certain when the GTK event will happen!
        # put all the data from self.dds_outputs in a dict!
        dds_outputs = {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "en0":self.dds_outputs[0].do.state,
                      "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "en1":self.dds_outputs[1].do.state}
                      
        self.queue_work('program_static',dds_outputs,self.encode_flags())
    
    def transition_to_static_complete(self,notify_queue):
        #reenable static updates triggered by GTK events
        self.static_mode = True
        # Notify the queue manager thread that we've finished transitioning to static:
        notify_queue.put(self.device_name)
        
        
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Returns the DO/RF/AO/DDS object associated with a given channel.
    # This is called before instantiating virtual devices, so that they can
    # be given a reference to channels they use 
    #     
    def get_child(self,type,channel):
        if type == "RF":
            if channel >= 0 and channel < self.num_RF:
                return self.rf_outputs[channel]
        elif type == "DO":
            if channel >= 0 and channel < self.num_DO:
                return self.do_outputs[channel]
        elif type == "DDS":
            if channel >= 0 and channel < self.num_RF:
                return self.dds_outputs[channel]
        
        return None
    
    #########################
    # PyGTK Event functions #
    #########################
    @define_state
    def on_value_change(self,widget):
        update_channel = None
        for i in range(0,self.num_RF):
            for j in range(0,len(self.dds_widgets[i])):
                if widget == self.dds_widgets[i][j]:
                    update_channel = i
                    break
            if update_channel is not None:
                break
                      
        self.dds_outputs[update_channel].update_value(self.dds_widgets[update_channel][3].get_active(),self.dds_widgets[update_channel][0].get_value(),self.dds_widgets[update_channel][1].get_value(),self.dds_widgets[update_channel][2].get_value())
    
    @define_state    
    def on_flag_toggled(self,widget):
        update_channel = None
        for i in range(0,self.num_DO):
            if widget == self.do_widgets[i]:
                update_channel = i
                break
        self.do_outputs[update_channel].update_value(self.do_widgets[update_channel].get_active())

class PulseblasterWorker(Worker):

    def init(self):
        global spinapi; import spinapi
        global pb_programming; from hardware_programming import pulseblaster as pb_programming
    
    def initialise_pulseblaster(self, pb_num):
        self.pb_num = pb_num
        #spinapi.lock.acquire()
        # start pulseblaster
        spinapi.pb_select_board(self.pb_num)
        
        # Clean up any mess from previous bad closes
        spinapi.pb_init()
        spinapi.pb_core_clock(75)
        spinapi.pb_start()
        spinapi.pb_stop()
        spinapi.pb_close()
        
        # Now initialise properly!
        spinapi.pb_init()
        spinapi.pb_core_clock(75)     
        spinapi.pb_start()
        
        #spinapi.lock.release()
        
    def close_pulseblaster(self):
        #spinapi.lock.acquire()
        #spinapi.pb_select_board(self.pb_num)
        spinapi.pb_stop()
        spinapi.pb_close()
        #spinapi.lock.release()
        
    def program_static(self,dds_outputs,flags):
        # Program hardware 
        #spinapi.lock.acquire()
        #spinapi.pb_select_board(self.pb_num)
        
        freq = []
        phase = []
        amp = []
        en = []
        for i in range(0,2):
            # Select DDS:
            spinapi.pb_select_dds(i)
            # Program the frequency registers for DDS: 
            freq.append(spinapi.program_freq_regs( dds_outputs["freq"+str(i)]*spinapi.MHz ))
            # Program the phase registers for DDS:
            phase.append(spinapi.program_phase_regs(dds_outputs["phase"+str(i)]))
            # Program the amplitude registers for DDS:
            amp.append(spinapi.program_amp_regs(dds_outputs["amp"+str(i)]))
            # Get enable state for DDS
            if dds_outputs["en"+str(i)]:
                en.append(spinapi.ANALOG_ON)
            else:
                en.append(spinapi.ANALOG_OFF)
            
        # send instructrions for the program to be executed:
        spinapi.pb_start_programming(spinapi.PULSE_PROGRAM)

        start = spinapi.pb_inst_dds2(freq[0], phase[0], amp[0], en[0], spinapi.NO_PHASE_RESET,
                                     freq[1], phase[1], amp[1], en[1], spinapi.NO_PHASE_RESET, flags, spinapi.BRANCH, 0, 0.5*spinapi.us)
                             
        spinapi.pb_stop_programming()
        #spinapi.lock.release()
    
    def program_buffered(self,h5file,initial_values):
        return pb_programming.program_from_h5_file(self.pb_num,h5file,initial_values)
    
    def start2(self):
        spinapi.pb_start()
    
    def stop2(self):
        spinapi.pb_stop()
    
    def reset2(self):
        spinapi.pb_reset()
        
    def get_status(self):
        #spinapi.lock.acquire()
        #spinapi.pb_select_board(self.pb_num)
        return spinapi.pb_read_status()
        #spinapi.lock.release()
