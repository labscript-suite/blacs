from hardware_interfaces.output_types.RF import *
from hardware_interfaces.output_types.DO import *
from hardware_interfaces.output_types.DDS import *

import spinapi
from hardware_programming import pulseblaster as pb_programming

import gobject
import pygtk
import gtk
import time

import h5py


class pulseblaster(object):

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
    def __init__(self,notebook,settings):
        
        # is the init method finished...no!
        self.init_done = False
        self.static_mode = False
        
        # Capabilities
        self.num_RF = 2
        self.num_DO = 4 #sometimes might be 4
        self.num_DO_widgets = 12
        
        self.settings = settings
        self.device_name = settings["device_name"]        
        self.pb_num = int(settings["device_num"])
        
        spinapi.lock.acquire()
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
        
        spinapi.lock.release()
        
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/pulseblaster.glade')
        self.tab = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text(self.settings["device_name"])
        
        # Need to connect signals!
        self.builder.connect_signals(self)
        
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
            self.rf_outputs.append(RF(self,self.ignore_update,i,hardware_name,real_name,[0.0000003,100.0,0.0,1.0,0,360]))
            # Make DO control object for RF channels
            self.rf_do_outputs.append(DO(self,self.ignore_update,i,hardware_name + " active",real_name + " active"))
            # Make DDS object
            self.dds_outputs.append(DDS(self,self.static_update,self.rf_outputs[i],self.rf_do_outputs[i]))            
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
                self.do_outputs.append(DO(self,self.static_update,i,temp.get_text(),real_name))
            
            # inactive widgets
            else:
                self.builder.get_object("flag_"+str(i)).set_sensitive(False)
                # set label text
                temp = self.builder.get_object("flag_hardware_label_"+str(i))
                temp.set_text("Flag "+str(i))
                temp2 = self.builder.get_object("flag_real_label_"+str(i))
                temp2.set_text("")
                
        
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
        
        # This prevents the status check from being called while another API call is in progress (eg, mid programming)
        # TODO: Replace Via a global spinapi lock
        #self.pause_status = False
        self.timeout = gtk.timeout_add(50,self.status_monitor)
        
        tablabelbuilder = gtk.Builder()
        tablabelbuilder.add_from_file('tab_label.glade')
        tablabel = tablabelbuilder.get_object('toplevel')
        self.tab_label_widgets = {"not_ready":tablabelbuilder.get_object('not_ready'),"ready":tablabelbuilder.get_object('ready'),"inadvisable":tablabelbuilder.get_object('inadvisable')}
        tablabelbuilder.get_object('label').set_label(self.settings["device_name"])
        
        notebook.append_page(self.tab,tablabel)
        notebook.set_tab_reorderable(self.tab,True)
        
        self.sm = settings["state_machine"]
        
        # We are done with the init!
        self.init_done = True 
        self.static_mode = True
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method cleans up the class before the program exits. In this case, we close the worker thread!
    #
    def destroy(self):        
        gtk.timeout_remove(self.timeout)
        spinapi.lock.acquire()
        spinapi.pb_select_board(self.pb_num)
        spinapi.pb_stop()
        spinapi.pb_close()
        spinapi.lock.release()
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method sets the values of front panel controls to "defaults"
    #    
    def set_defaults(self):    
        for i in range(0,self.num_RF):
            self.rf_outputs[i].update_value(self.settings["f"+str(i)],self.settings["a"+str(i)],self.settings["p"+str(i)])
           
    # Dummy function!
    def ignore_update(self,output):
        pass
    
    # 
    # This function gets the status of the Pulseblaster from the spinapi, and updates the front panel widgets!
    #
    def status_monitor(self):
        #if self.pause_status is True:
        #    return True
        self.sm.enter("Status Check")
        spinapi.lock.acquire()
        spinapi.pb_select_board(self.pb_num)
        self.status = spinapi.pb_read_status()
        spinapi.lock.release()
        #print self.status
        # Update widgets
        a = ["stopped","reset","running","waiting"]
        for name in a:
            if self.status[name] == True:
                self.status_widgets[name+"_no"].hide()
                self.status_widgets[name+"_yes"].show()
            else:                
                self.status_widgets[name+"_no"].show()
                self.status_widgets[name+"_yes"].hide()
                
        # Update Tab Label
        if self.ready() and self.static_mode:
            self.tab_label_widgets["ready"].show()
            self.tab_label_widgets["not_ready"].hide()
        else:
            self.tab_label_widgets["ready"].hide()
            self.tab_label_widgets["not_ready"].show()
            
        
        self.sm.exit()        
        return True
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Returns the status of the device. Is it ready for transition to buffered?
    #
    def ready(self):
        if self.status["running"] and not self.status["stopped"] and not self.status["reset"] and not self.status["waiting"] and self.static_mode and self.init_done:
            return True
        return False
    
    #
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    #
    # Static update of hardware (unbuffered)
    #
    # This does not run until the initialisation is complete
    # This does not run if we have transitioned to buffered mode!
    #
    def static_update(self,output):
        # if the init isn't done, skip this!
        if not self.init_done or not self.static_mode:
            return
        
        #convert numbers to correct representation
        #output.amp = int(output.amp*1024)/1024.0
        #output.phase = int(output.phase*16384)/16384.0
              
        # is it a DO update or a DDS update?
        if isinstance(output,DDS):
            search_array = self.dds_outputs
        elif isinstance(output,DO):
            search_array = self.do_outputs
        
        # search for the output that has been updated, so we can get the right widget to update
        channel = None
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
        
        # Pause status check so we don't query status halfway through programming
        # TODO: Replace with global spinapi lock
        #self.pause_status = True
        # Program hardware 
        spinapi.lock.acquire()
        spinapi.pb_select_board(self.pb_num)
        
        freq = []
        phase = []
        amp = []
        en = []
        for i in range(0,self.num_RF):
            # Select DDS:
            spinapi.pb_select_dds(i)
            # Program the frequency registers for DDS: 
            freq.append(spinapi.program_freq_regs( self.dds_outputs[i].rf.freq*spinapi.MHz ))
            # Program the phase registers for DDS:
            phase.append(spinapi.program_phase_regs(self.dds_outputs[i].rf.phase))
            # Program the amplitude registers for DDS:
            amp.append(spinapi.program_amp_regs(self.dds_outputs[i].rf.amp))
            # Get enable state for DDS
            if self.dds_outputs[i].do.state:
                en.append(spinapi.ANALOG_ON)
            else:
                en.append(spinapi.ANALOG_OFF)
        
        
            
        # send instructrions for the program to be executed:
        spinapi.pb_start_programming(spinapi.PULSE_PROGRAM)

        start = spinapi.pb_inst_dds2(freq[0], phase[0], amp[0], en[0], spinapi.NO_PHASE_RESET,
                                     freq[1], phase[1], amp[1], en[1], spinapi.NO_PHASE_RESET, self.encode_flags(), spinapi.BRANCH, 0, 0.5*spinapi.us)
                             
        

        spinapi.pb_stop_programming()
        spinapi.lock.release()
        
        # Resume status check
        #self.pause_status = False
    
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
    def start(self):
        #self.pause_status = True
        #time.sleep(2)
        spinapi.lock.acquire()
        spinapi.pb_select_board(self.pb_num)
        spinapi.pb_start()
        spinapi.lock.release()
        #self.pause_status = False
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Program experimental sequence
    #
    # Needs to handle seemless transition from static to experiment sequence
    #
    def transition_to_buffered(self,h5file):        
        # disable static update
        self.static_mode = False
        #self.pause_status = True
        #time.sleep(2)
        # Program hardware
        
        initial_values = {"freq0":self.dds_outputs[0].rf.freq, "amp0":self.dds_outputs[0].rf.amp, "phase0":self.dds_outputs[0].rf.phase, "ddsen0":self.dds_outputs[0].do.state,
                          "freq1":self.dds_outputs[1].rf.freq, "amp1":self.dds_outputs[1].rf.amp, "phase1":self.dds_outputs[1].rf.phase, "ddsen1":self.dds_outputs[1].do.state,
                          "flags":self.encode_flags()}
        self.last_instruction = pb_programming.program_from_h5_file(self.pb_num,h5file,initial_values)
        
        #self.pause_status = False
        # Return Ready status   
        
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # return to unbuffered (static) mode
    #
    # Needs to handle seemless transition from experiment sequence to static mode
    #    
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is sending out updates.
                
        #reenable static updates
        self.static_mode = True
        
                
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
            
    def on_flag_toggled(self,widget):
        update_channel = None
        for i in range(0,self.num_DO):
            if widget == self.do_widgets[i]:
                update_channel = i
                break
        self.do_outputs[update_channel].update_value(self.do_widgets[update_channel].get_active())
            