import gtk
import h5py

from output_classes import AO, DO, RF, DDS
from tab_base_classes import Tab, Worker, define_state

class pulseblaster(Tab):
    # Capabilities
    num_DDS = 2
    num_DO = 4 #sometimes might be 12
    num_DO_widgets = 12
    
    freq_min = 0.0000003   # In MHz
    freq_max = 150.0
    freq_step = 1 
    amp_min = 0.0          # In Vpp
    amp_max = 1.0
    amp_step = 0.01
    phase_min = 0          # In Degrees
    phase_max = 360
    phase_step = 1
        
    def __init__(self,notebook,settings,restart=False):
        Tab.__init__(self,PulseblasterWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']        
        self.pb_num = int(settings['device_num'])
        self.fresh = False
        self.static_mode = True
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/pulseblaster.glade')
        self.builder.connect_signals(self)
        
        self.toplevel = self.builder.get_object('toplevel')
        self.checkbutton_fresh = self.builder.get_object('force_fresh_program')
        self.smart_disabled = self.builder.get_object('hbox_fresh_program')
        self.smart_enabled = self.builder.get_object('hbox_smart_in_use')
        self.builder.get_object('title').set_text(self.settings['device_name'])

        self.dds_outputs = []
        for i in range(self.num_DDS):
            # Get the widgets for the DDS:
            freq_spinbutton = self.builder.get_object('freq_chnl_%d'%i)
            amp_spinbutton = self.builder.get_object('amp_chnl_%d'%i)
            phase_spinbutton = self.builder.get_object('phase_chnl_%d'%i)
            gate_togglebutton = self.builder.get_object('active_chnl_%d'%i)
            label = self.builder.get_object('channel_%d_label'%i)
            
            # Find out the name of the connected device (if there is a device connected)
            channel = 'DDS %d'%i
            device = self.settings['connection_table'].find_child(self.settings['device_name'],'dds %d'%i)
            name = ' - ' + connection_table_row.name if device else ''
            
            # Set the label to reflect the connected device's name:
            label.set_text(hardware_name + real_name)
            
            # Make output objects:
            freq = AO(name, channel, freq_spinbutton, self.static_update, self.freq_min, self.freq_max, self.freq_step)
            amp = AO(name, channel, amp_spinbutton, self.static_update, self.amp_min, self.amp_max, self.amp_step)
            phase = AO(name, channel, phase_spinbutton, self.static_update,self.phase_min, self.phase_max, self.phase_step)
            gate = DO(name, channel, gate_togglebutton, self.static_update)
            rf = RF(amp, freq, phase)
            dds = DDS(rf, gate)
            
            # Set default values:
            freq.set_value(settings['f%d'%i],program=False)
            amp.set_value(settings['a%d'%i],program=False)
            phase.set_value(settings['p%d'%i],program=False)
            gate.set_value(settings['e%d'%i],program=False)
        
            # Store for later access:
            self.dds_outputs.append(dds)
            
        self.flags = []
        for i in range(0,self.num_DO_widgets):
            #Active widgets
            if i < self.num_DO:
                # get the widgets for the flag:
                flag_togglebutton = self.builder.get_object('flag_%d'%i)
                channel_label = self.builder.get_object('flag_hardware_label_%d'%i)
                name_label = self.builder.get_object('flag_real_label_%d'%i)
                
                # Find out the name of the connected device (if there is a device connected)
                device = self.settings['connection_table'].find_child(self.settings['device_name'],'flag %d'%i)
                name = device.name if channel_name else '-'
                
                # Set the label to reflect the connected device's name:
                channel_label.set_text('Flag %d'%i)
                name_label.set_text(name)
                
                # Make output object:
                flag = DO(name, channel, flag_togglebutton, self.static_update)
            
                # Set default value:
                flag.set_value(settings['flags'][i],program=False)
                
                # Store for later:
                self.flags.append(flag)
            else:
                # This pulseblaster doesn't this flag - hide the button:
                self.builder.get_object('flag_%d'%i).hide()

        # Status monitor timout
        self.statemachine_timeout_add(2000, self.status_monitor)
        
        # Default values for status prior to the status monitor first running:
        self.status = {'stopped':False,'reset':False,'running':False, 'waiting':False}
        
        # Get status widgets
        self.status_widgets = {'stopped_yes':self.builder.get_object('stopped_yes'),
                               'stopped_no':self.builder.get_object('stopped_no'),
                               'reset_yes':self.builder.get_object('reset_yes'),
                               'reset_no':self.builder.get_object('reset_no'),
                               'running_yes':self.builder.get_object('running_yes'),
                               'running_no':self.builder.get_object('running_no'),
                               'waiting_yes':self.builder.get_object('waiting_yes'),
                               'waiting_no':self.builder.get_object('waiting_no')}
        
        self.viewport.add(self.toplevel)
        
        # Initialise the Pulseblaster:
        self.initialise_pulseblaster()
        
        # Program the hardware with the initial values of everything:
        self.program_static()  

    @define_state
    def initialise_pulseblaster(self):
        self.queue_work('initialise_pulseblaster')
        
    # This method should be common to all hardware interfaces.
    @define_state
    def destroy(self):        
        self.queue_work('pb_close')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
    
    # This function gets the status of the Pulseblaster from the spinapi,
    # and updates the front panel widgets!
    @define_state
    def status_monitor(self,notify_queue=None):
        self.queue_work('pb_read_status')
        self.do_after('status_monitor_leave', notify_queue)
        
    def status_monitor_leave(self,notify_queue,_results):
        # When called with a queue, this function writes to the queue
        # when the pulseblaster is waiting. This indicates the end of
        # an experimental run.
        self.status = _results
        if notify_queue is not None and self.status['waiting']:
            # Experiment is over. Tell the queue manager about it, then
            # set the status checking timeout back to every 2 seconds
            # with no queue.
            notify_queue.put('done')
            self.timeouts.remove(self.status_monitor)
            self.statemachine_timeout_add(2000,self.status_monitor)
        # Update widgets
        a = ['stopped','reset','running','waiting']
        for name in a:
            if self.status[name] == True:
                self.status_widgets[name+'_no'].hide()
                self.status_widgets[name+'_yes'].show()
            else:                
                self.status_widgets[name+'_no'].show()
                self.status_widgets[name+'_yes'].hide()
        
    def get_front_panel_state(self):
        return {'freq0':self.dds_outputs[0].freq.value, 'amp0':self.dds_outputs[0].amp.value, 'phase0':self.dds_outputs[0].phase.value, 'en0':self.dds_outputs[0].gate.state,
                'freq1':self.dds_outputs[1].freq.value, 'amp1':self.dds_outputs[1].amp.value, 'phase1':self.dds_outputs[1].phase.value, 'en1':self.dds_outputs[1].gate.state,
                'flags':''.join(['1' if flag.state else '0' for flag in self.flags]).ljust(12,'0')}
    
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    # Static update of hardware (unbuffered)
    @define_state
    def program_static(self,widget=None):
        # Skip if in buffered mode:
        if self.static_mode:
            self.queue_work('program_static',self.get_front_panel_state())
        
    @define_state
    def start(self):
        self.queue_work('pb_start')
    
    @define_state
    def stop(self):
        self.queue_work('pb_stop')
    
    @define_state    
    def reset(self):
        self.queue_work('pb_reset')
    
    # ** This method should be common to all hardware interfaces **
    # Program experimental sequence
    # Needs to handle seamless transition from static to experiment sequence
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False 
        initial_values = self.get_front_panel_state()
        self.queue_work('program_buffered',h5file,initial_values,self.fresh)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        # Enable smart programming:
        self.checkbutton_fresh.show() 
        self.checkbutton_fresh.set_active(False) 
        self.checkbutton_fresh.toggled()
        # These are the final values that the pulseblaster will be in
        # at the end of the run. Store them so that we can use them
        # in transition_to_static:
        self.final_values = _results
        # Notify the queue manager thread that we've finished transitioning to buffered:
        notify_queue.put(self.device_name)
       
    def abort_buffered(self):
        # Do nothing. The Pulseblaster is always ready!
        self.static_mode = True
        
    @define_state
    def start_run(self, notify_queue):
        """Starts the Pulseblaster, notifying the queue manager when
        the run is over"""
        self.timeouts.remove(self.status_monitor)
        self.start()
        self.statemachine_timeout_add(50,self.status_monitor,notify_queue)
        
    # ** This method should be common to all hardware interfaces **
    # Return to unbuffered (static) mode
    # Needs to handle seamless transition from experiment sequence to static mode
    @define_state
    def transition_to_static(self,notify_queue):
        # Once again, the pulseblaster is always ready! However we need
        # to update the gui to reflect the current hardware values:
        for i, flag in enumerate(self.flags):
            flag.set_value(self.final_values['flag%d'%i],program=False)
        for i, dds in enumerate(self.dds_outputs):
            dds.freq.set_value(self.final_values['freq%d'%i],program=False)
            dds.amp.set_value(self.final_values['amp%d'%i],program=False)
            dds.phase.set_value(self.final_values['phase%d'%i],program=False)
            dds.gate.set_value(self.final_values['en%d'%i],program=False)
        # Reenable static updates triggered by GTK events
        self.static_mode = True
        # Notify the queue manager thread that we've finished transitioning to static:
        notify_queue.put(self.device_name)

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
            
    # ** This method should be common to all hardware interfaces **
    # Returns the DO/RF/AO/DDS object associated with a given channel.
    # This is called before instantiating virtual devices, so that they can
    # be given a reference to channels they use 
    def get_child(self,type,channel):
        if type == 'RF':
            if channel >= 0 and channel < self.num_DDS:
                return self.dds_outputs[channel]
        elif type == 'DO':
            if channel >= 0 and channel < self.num_DO:
                return self.flags[channel]
        elif type == 'DDS':
            if channel >= 0 and channel < self.num_DDS:
                return self.flags[channel]
        return None
    

class PulseblasterWorker(Worker):
    def init(self):
        exec 'from spinapi import *' in globals()
        self.smart_cache = {'amps':None,'freqs':None,'phases':None,'pulse_program':None,'ready_to_go':False}
    
    def initialise_pulseblaster(self, pb_num):
        self.pb_num = pb_num
        pb_select_board(self.pb_num)
        pb_init()
        pb_core_clock(75)
        pb_stop()

    def program_static(self,values):
        # Program the DDS registers:
        for i in range(2):
            pb_select_dds(i)
            # Program the frequency, amplitude and phase into their
            # zeroth registers:
            program_amp_regs(dds_outputs['amp%d'%i])
            program_freq_regs(values['freq%d'%i]) # method expects MHz
            program_phase_regs(values['phase%d'%i])

        # Write the first two lines of the pulse program:
        pb_start_programming(PULSE_PROGRAM)
        # Line zero is a wait:
        pb_inst_dds2(0,0,0,values['en0'],0,0,0,0,values['en1'],0,values['flags'], WAIT, 0, 100)
        # Line one is a brach to line 0:
        pb_inst_dds2(0,0,0,values['en0'],0,0,0,0,values['en1'],0,values['flags'], BRANCH, 0, 100)
        spinapi.pb_stop_programming()
        
        # Now we're waiting on line zero, so when we start() we'll go to
        # line one, then brach back to zero, completing the static update:
        pb_start()
        
        # The pulse program now has a branch in line one, and so can't proceed to the pulse program
        # without a reprogramming of the first two lines:
        self.smart_cache['ready_to_go'] = False
        
    def program_buffered(self,h5file,initial_values,fresh):
        return pb_programming.program_from_h5_file(self.pb_num,h5file,initial_values)
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/pulseblaster_%d'%self.pb_num]
            # Program the DDS registers:
            ampregs = []
            freqregs = []
            phaseregs = []
            for i in range(2):
                amps = group['DDS%d/AMP_REGS'%i][:]
                freqs = group['DDS%d/FREQ_REGS'%i][:]
                phases = group['DDS%d/PHASE_REGS'%i][:]
                
                amps[0] = initial_values['amp%d'%i]
                freqs[0] = initial_values['freq%d'%i] # had better be in MHz!
                phases[0] = initial_values['phase%d'%i]
                
                pb_select_dds(i)
                # Only reprogram each thing if there's been a change:
                if fresh or amps != self.smart_cache['amps']:   
                    self.smart_cache['amps'] = amps
                    program_amp_regs(*amps)
                if fresh or freqs != self.smart_cache['freqs']:
                    self.smart_cache['freqs'] = freqs
                    program_freq_regs(*freqs)
                if fresh or phases != self.smart_cache['phases']:      
                    self.smart_cache['phases'] = phases
                    program_phase_regs(*phases)
                
                ampregs.append(amps)
                freqregs.append(freqs)
                phaseregs.append(phases)
                
            # Now for the pulse program:
            pulse_program = group['PULSE_PROGRAM'][2:]
            
            #Let's get the final state of the pulseblaster. z's are the args we don't need:
            freqreg0,phasereg0,ampreg0,en0,z,freqreg1,phasereg1,ampreg1,en1,z,flags,z,z,z = pulse_program[-1]
            finalfreq0 = freqs0[freqreg0]
            finalfreq1 = freqs1[freqreg1]
            finalamp0 = amps0[ampreg0]
            finalamp1 = amps1[ampreg1]
            finalphase0 = phase0[phasereg0]
            finalphase1 = phase1[phasereg1]
            
            if self.smart_cache['initial_values'] != initial_values or \
            self.smart_cache['pulse_program'] != pulse_program or \
            not self.smart_programming['ready_to_go']:
            
                self.smart_cache['initial_values'] = initial_values
                pb_start_programming(PULSE_PROGRAM)
                # Line zero is a wait on the final state of the program:
                pb_inst_dds2(freqreg0,phasereg0,ampreg0,en0,0,freqreg1,phasereg1,ampreg1,en1,0,flags,WAIT,0,1*ms)
                # Line one is a continue with the current front panel values:
                pb_inst_dds2(0,0,0,initial_values['en0'],0,0,0,0,initial_values['en1'],0,initial_values['flags'], CONTINUE, 0, 1*ms)
                # Now the rest of the program:
                if self.smart_cache['pulse_program'] != pulse_program:
                    self.smart_cache['pulse_program'] = pulse_program
                    for args in pulse_program:
                        spinapi.pb_inst_dds2(*args)
                spinapi.pb_stop_programming()
            
            # Now we build a dictionary of the final state to send back to the GUI:
            return {'freq0':finalfreq0, 'amp0':finalamp0, 'phase0':finalphase0, 'en0':en0,
                    'freq1':finalfreq1, 'amp1':finalamp1, 'phase1':finalphase1, 'en1':en1,
                    'flags':bin(flags)[2:].rjust(12,'0')[::-1]}
    
