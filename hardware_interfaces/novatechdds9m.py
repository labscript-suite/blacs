import gtk
from output_classes import AO, DO, DDS
from tab_base_classes import Tab, Worker, define_state

class novatechdds9m(Tab):
    # Capabilities
    num_DDS = 4
    
    freq_min = 0.0000001   # In MHz
    freq_max = 170.0
    freq_step = 1
    amp_min = 0            # In Vpp
    amp_max = 1023
    amp_step = 1
    phase_min = 0          # In Degrees
    phase_max = 360
    phase_step = 1
        
    def __init__(self,notebook,settings,restart=False):
        Tab.__init__(self,NovatechDDS9mWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.fresh = False # whether to force a full reprogramming of table mode
        self.static_mode = True
        self.destroy_complete = False

        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/novatechdds9m.glade')
        self.builder.connect_signals(self)
        
        self.toplevel = self.builder.get_object('toplevel')
        self.checkbutton_fresh = self.builder.get_object('force_fresh_program')
        self.smart_disabled = self.builder.get_object('hbox_fresh_program')
        self.smart_enabled = self.builder.get_object('hbox_smart_in_use')
        self.builder.get_object('title').set_text(self.settings["device_name"]+" - Port: "+self.settings["COM"])
                
        self.dds_outputs = []
        self.outputs_by_widget = {}
        for i in range(self.num_DDS):
            # Get the widgets for the DDS:
            freq_spinbutton = self.builder.get_object('freq_chnl_%d'%i)
            freq_unit_selection = self.builder.get_object('freq_unit_chnl_%d'%i)
            amp_spinbutton = self.builder.get_object('amp_chnl_%d'%i)
            amp_unit_selection = self.builder.get_object('amp_unit_chnl_%d'%i)
            phase_spinbutton = self.builder.get_object('phase_chnl_%d'%i)
            phase_unit_selection = self.builder.get_object('phase_unit_chnl_%d'%i)
            gate_checkbutton = self.builder.get_object("amp_switch_%d"%i)
            label = self.builder.get_object("channel_%d_label"%i) 
            
            # Find out the name of the connected device (if there is a device connected)
            channel = "Channel %d"%i
            device = self.settings["connection_table"].find_child(self.settings["device_name"],"channel %d"%i)
            name = device.name if device else '-'

            # Set the label to reflect the connected device's name:
            label.set_text(channel + ' - ' + name)

            freq_calib = None
            freq_calib_params = {}
            def_freq_calib_params = "MHz"
            amp_calib = None
            amp_calib_params = {}
            def_amp_calib_params = "Arb."
            phase_calib = None
            phase_calib_params = {}
            def_phase_calib_params = "Degrees"
            if device:
                # get the 3 AO children from the connection table, find their calibration details
                if (device.name+'_freq') in device.child_list:
                    if device.child_list[device.name+'_freq'] != "None":
                        freq_calib = device.child_list[device.name+'_freq'].unit_conversion_class
                        freq_calib_params = eval(device.child_list[device.name+'_freq'].unit_conversion_params)
                if (device.name+'_amp') in device.child_list:
                    if device.child_list[device.name+'_amp'] != "None":
                        amp_calib = device.child_list[device.name+'_amp'].unit_conversion_class
                        amp_calib_params = eval(device.child_list[device.name+'_amp'].unit_conversion_params)
                if (device.name+'_phase') in device.child_list:
                    if device.child_list[device.name+'_phase'] != "None":
                        phase_calib = device.child_list[device.name+'_phase'].unit_conversion_class
                        phase_calib_params = eval(device.child_list[device.name+'_phase'].unit_conversion_params)   
            
            # Make output objects:
            freq = AO(name+'_freq', channel+'_freq', freq_spinbutton, freq_unit_selection, freq_calib, freq_calib_params, def_freq_calib_params, self.program_static, self.freq_min, self.freq_max, self.freq_step)
            amp = AO(name+'_amp', channel+'_amp', amp_spinbutton, amp_unit_selection, amp_calib, amp_calib_params, def_amp_calib_params, self.program_static, self.amp_min, self.amp_max, self.amp_step)
            phase = AO(name+'_phase', channel+'_phase', phase_spinbutton, phase_unit_selection, phase_calib, phase_calib_params, def_phase_calib_params, self.program_static, self.phase_min, self.phase_max, self.phase_step)
            gate = DO(name+'_gate', channel+'_gate', gate_checkbutton, self.program_static)
            
            dds = DDS(freq,amp,phase, gate)
            
            # Store for later access:
            self.dds_outputs.append(dds)
         
            # Store outputs keyed by widget, so that we can look them up in gtk callbacks:
            self.outputs_by_widget[freq_spinbutton.get_adjustment()] = i, 'freq', freq
            self.outputs_by_widget[amp_spinbutton.get_adjustment()] = i, 'amp', amp
            self.outputs_by_widget[phase_spinbutton.get_adjustment()] = i, 'phase', phase
            self.outputs_by_widget[gate.action] = i, 'gate', gate
            
        # Insert our GUI into the viewport provided by BLACS:    
        self.viewport.add(self.toplevel)
        
        # Initialise the Novatech DDS9M
        self.initialise_novatech()
        
    @define_state
    def initialise_novatech(self):
        self.queue_work('initialise_novatech', self.settings["COM"], 115200)
        self.do_after('leave_initialise')
    
    def leave_initialise(self,_results):
        # Update the GUI to reflect the current hardware values:
        # The novatech doesn't have anything to say about the checkboxes;
        # turn them on:
        for i in range(4):
            _results['en%d'%i] = True
        self.set_front_panel_state(_results)
                    
    @define_state
    def destroy(self):
        self.queue_work('close_connection')
        self.do_after('leave_destroy')
    
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
    
    def get_front_panel_state(self):
        return {"freq0":self.dds_outputs[0].freq.value, "amp0":self.dds_outputs[0].amp.value, "phase0":self.dds_outputs[0].phase.value, "en0":self.dds_outputs[0].gate.state,
                "freq1":self.dds_outputs[1].freq.value, "amp1":self.dds_outputs[1].amp.value, "phase1":self.dds_outputs[1].phase.value, "en1":self.dds_outputs[1].gate.state,
                "freq2":self.dds_outputs[2].freq.value, "amp2":self.dds_outputs[2].amp.value, "phase2":self.dds_outputs[2].phase.value, "en2":self.dds_outputs[2].gate.state,
                "freq3":self.dds_outputs[3].freq.value, "amp3":self.dds_outputs[3].amp.value, "phase3":self.dds_outputs[3].phase.value, "en3":self.dds_outputs[3].gate.state}
    
    def set_front_panel_state(self, values):
        """Updates the gui without reprogramming the hardware"""
        for i, dds in enumerate(self.dds_outputs):
            if 'freq%d'%i in values:
                dds.freq.set_value(values['freq%d'%i],program=False)
            if 'amp%d'%i in values:
                dds.amp.set_value(values['amp%d'%i],program=False)
            if 'phase%d'%i in values:    
                dds.phase.set_value(values['phase%d'%i],program=False)
            if 'en%d'%i in values:
                dds.gate.set_state(values['en%d'%i],program=False)
        
    @define_state
    def program_static(self,widget):
        # Skip if in buffered mode:
        if self.static_mode:
            # The novatech only programs one output at a time. There
            # is no current code which programs many outputs in quick
            # succession, so there is no speed penalty for this:
            channel, type, output = self.outputs_by_widget[widget]
            # If its the user clicking a checkbutton, then really what
            # we're doing is an amplitude change:
            if type == 'gate':
                value = output.state*self.dds_outputs[channel].amp.value
                type = 'amp'
            else:
                value = output.value
            self.queue_work('program_static',channel, type, value)
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False 
        self.queue_work('program_buffered',self.settings['device_name'],h5file,self.get_front_panel_state(),self.fresh)
        self.do_after('leave_program_buffered',notify_queue)        
    
    def leave_program_buffered(self,notify_queue,_results):
        # Enable smart programming:
        self.checkbutton_fresh.show() 
        self.checkbutton_fresh.set_active(False) 
        self.checkbutton_fresh.toggled()
        # These are the final values that the novatech will be in
        # at the end of the run. Store them so that we can use them
        # in transition_to_static:
        self.final_values = _results
        # Notify the queue manager thread that we've finished
        # transitioning to buffered:
        notify_queue.put(self.device_name)
    
    def abort_buffered(self):
        self.transition_to_static(notify_queue=None)
    
    @define_state    
    def transition_to_static(self,notify_queue):
        if notify_queue is None:
            abort = True
        else: abort = False
        self.queue_work('transition_to_static',abort=abort)
        # Update the gui to reflect the current hardware values:
        if not abort:
            # The final results don't say anything about the checkboxes;
            # turn them on:
            for i in range(4):
                self.final_values['en%d'%i] = True
            self.set_front_panel_state(self.final_values)
        self.static_mode=True
        # Tell the queue manager that we're done:
        if notify_queue:
            notify_queue.put(self.device_name)
    
    @define_state
    def toggle_fresh(self,button):
        if button.get_active():
            self.smart_enabled.hide()
            self.smart_disabled.show()
            self.fresh = True
        else:
            self.smart_enabled.show()
            self.smart_disabled.hide()
            self.fresh = False
        
    def get_child(self,type,channel):
        """Allows virtual devices to obtain this tab's output objects"""
        if type == "DDS":
            if channel in range(self.num_DDS):
                return self.dds_outputs[channel]
        return None
        
        
class NovatechDDS9mWorker(Worker):
    def init(self):
        global serial; import serial
        global h5py; import h5py
        self.smart_cache = {'STATIC_DATA': None, 'TABLE_DATA': ''}
        
    def initialise_novatech(self,port,baud_rate):
        self.connection = serial.Serial(port, baudrate = baud_rate, timeout=0.1)
        self.connection.readlines()
        
        self.connection.write('e d\r\n')
        response = self.connection.readline()
        if response == 'e d\r\n':
            # if echo was enabled, then the command to disable it echos back at us!
            response = self.connection.readline()
        if response != "OK\r\n":
            raise Exception('Error: Failed to execute command: "e d"')
        
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        
        # Get the currently output values:
        self.connection.write('QUE\r\n')
        try:
            response = [self.connection.readline() for i in range(5)]
        except socket.timeout:
            raise Exception('Failed to execute QUE')
        results = {}
        for i, line in enumerate(response[:4]):
            freq, phase, amp, ignore, ignore, ignore, ignore = line.split()
            # Convert hex multiple of 0.1 Hz to MHz:
            results['freq%d'%i] = float(int(freq,16))/10**7
            # Convert hex to int:
            results['amp%d'%i] = int(amp,16)
            # Convert hex fraction of 16384 to degrees:
            results['phase%d'%i] = int(phase,16)*360/16384.0
        return results
        
    def program_static(self,channel,type,value):
        if type == 'freq':
            self.connection.write('F%d %f\r\n'%(channel,value))
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: '+'F%d %f\r\n'%(channel,value))
        elif type == 'amp':
            self.connection.write('V%d %u\r\n'%(channel,value))
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: '+'V%d %u\r\n'%(channel,value))
        elif type == 'phase':
            self.connection.write('P%d %u\r\n'%(channel,value*16384/360))
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: '+'P%d %u\r\n'%(channel,value*16384/360))
        else:
            raise TypeError(type)
        # Now that a static update has been done, we'd better invalidate the saved STATIC_DATA:
        self.smart_cache['STATIC_DATA'] = None
       
    def program_buffered(self,device_name,h5file,initial_values,fresh):
        # Store the initial values in case we have to abort and restore them:
        self.initial_values = initial_values
        # Store the final values to for use during transition_to_static:
        self.final_values = {}
        with h5py.File(h5file) as hdf5_file:
            group = hdf5_file['/devices/'+device_name]
            # If there are values to set the unbuffered outputs to, set them now:
            if 'STATIC_DATA' in group:
                data = group['STATIC_DATA'][0]
                if fresh or data != self.smart_cache['STATIC_DATA']:
                    self.logger.debug('Static data has changed, reprogramming.')
                    self.smart_cache['SMART_DATA'] = data
                    self.connection.write('F2 %f\r\n'%(data['freq2']/10.0**7))
                    self.connection.readline()
                    self.connection.write('V2 %u\r\n'%(data['amp2']))
                    self.connection.readline()
                    self.connection.write('P2 %u\r\n'%(data['phase2']))
                    self.connection.readline()
                    self.connection.write('F3 %f\r\n'%(data['freq3']/10.0**7))
                    self.connection.readline()
                    self.connection.write('V3 %u\r\n'%data['amp3'])
                    self.connection.readline()
                    self.connection.write('P3 %u\r\n'%data['phase3'])
                    self.connection.readline()
                    
                    # Save these values into final_values so the GUI can
                    # be updated at the end of the run to reflect them:
                    self.final_values['freq2'] = data['freq2']/10.0**7
                    self.final_values['freq3'] = data['freq3']/10.0**7
                    self.final_values['amp2'] = data['amp2']
                    self.final_values['amp3'] = data['amp3']
                    self.final_values['phase2'] = data['phase2']*360/16384.0
                    self.final_values['phase3'] = data['phase3']*360/16384.0
                    
            # Now program the buffered outputs:
            if 'TABLE_DATA' in group:
                data = group['TABLE_DATA'][:]
                for i, line in enumerate(data):
                    oldtable = self.smart_cache['TABLE_DATA']
                    for ddsno in range(2):
                        if fresh or i >= len(oldtable) or (line['freq%d'%ddsno],line['phase%d'%ddsno],line['amp%d'%ddsno]) != (oldtable['freq%d'%ddsno],oldtable['phase%d'%ddsno],oldtable['amp%d'%ddsno]):
                            self.connection.write('t%d %04x %08x,%04x,%04x,ff\r\n '%(ddsno, i,line['freq%d'%ddsno],line['phase%d'%ddsno],line['amp%d'%ddsno]))
                            self.connection.readline()
                # Store the table for future smart programming comparisons:
                try:
                    self.smart_cache['TABLE_DATA'][:len(data)] = data
                    self.logger.debug('Stored new table as subset of old table')
                except: # new table is longer than old table
                    self.smart_cache['TABLE_DATA'] = data
                    self.logger.debug('New table is longer than old table and has replaced it.')
                    
                # Get the final values of table mode so that the GUI can
                # reflect them after the run:
                self.final_values['freq0'] = data[-1]['freq0']/10.0**7
                self.final_values['freq1'] = data[-1]['freq1']/10.0**7
                self.final_values['amp0'] = data[-1]['amp0']
                self.final_values['amp1'] = data[-1]['amp1']
                self.final_values['phase0'] = data[-1]['phase0']*360/16384.0
                self.final_values['phase1'] = data[-1]['phase1']*360/16384.0
                
            # Transition to table mode:
            self.connection.write('m t\r\n')
            self.connection.readline()
            # Transition to hardware updates:
            self.connection.write('I e\r\n')
            self.connection.readline()
            # We are now waiting for a rising edge to trigger the output
            # of the second table pair (first of the experiment)
            return self.final_values
            
    def transition_to_static(self,abort = False):
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        if abort:
            # If we're aborting the run, then we need to reset DDSs 2 and 3 to their initial values.
            # 0 and 1 will already be in their initial values. We also need to invalidate the smart
            # programming cache for them.
            values = self.initial_values
            DDSs = [2,3]
            self.smart_cache['STATIC_DATA'] = None
        else:
            # If we're not aborting the run, then we need to set DDSs 0 and 1 to their final values.
            # 2 and 3 will already be in their final values.
            values = self.final_values
            DDSs = [0,1]
            
        for ddsnumber in DDSs:
            if 'freq%d'%ddsnumber in values:
                 command = 'F%d %f\r\n' %(ddsnumber, values['freq%d'%ddsnumber])
                 self.connection.write(command)
                 if self.connection.readline() != "OK\r\n":
                     raise Exception('Error: Failed to execute %s'%command)
            if 'amp%d'%ddsnumber in values:
                 gate_factor = values['en%d'%ddsnumber] if 'en%d'%ddsnumber in values else 1
                 command = 'V%d %d\r\n' %(ddsnumber, values['amp%d'%ddsnumber]*gate_factor)
                 self.connection.write(command)
                 if self.connection.readline() != "OK\r\n":
                     raise Exception('Error: Failed to execute %s'%command)
            if 'phase%d'%ddsnumber in values:
                 command = 'P%d %d\r\n' %(ddsnumber, values['phase%d'%ddsnumber]*16384/360)
                 self.connection.write(command)
                 if self.connection.readline() != "OK\r\n":
                     raise Exception('Error: Failed to execute %s'%command)
                     
    def close_connection(self):
        self.connection.close()
