import gtk
from output_classes import AO, DO, RF, DDS
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
            freq_spinbutton = self.builder.get_object("frequency_adj_%d"%i)
            amp_spinbutton = self.builder.get_object("amplitude_adj_%d"%i)
            phase_spinbutton = self.builder.get_object("phase_adj_%d"%i)
            gate_checkbutton = self.builder.get_object("amp_switch_%d"%i)
            label = self.builder.get_object("channel_%d_label"%i) 
            
            # Find out the name of the connected device (if there is a device connected)
            channel = "Channel %d"%i
            device = self.settings["connection_table"].find_child(self.settings["device_name"],"channel %d"%i)
            name = ' - ' + connection_table_row.name if device else ''

            # Set the label to reflect the connected device's name:
            label.set_text(channel + name)

            # Make output objects:
            freq = AO(name, channel, freq_spinbutton, self.program_static, self.freq_min, self.freq_max, self.freq_step)
            amp = AO(name, channel, amp_spinbutton, self.program_static, self.amp_min, self.amp_max, self.amp_step)
            phase = AO(name, channel, phase_spinbutton, self.program_static,self.phase_min, self.phase_max, self.phase_step)
            gate = DO(name, channel, gate_checkbutton, self.program_static)
            rf = RF(amp, freq, phase)
            dds = DDS(rf, gate)
            
            # Store for later access:
            self.dds_outputs.append(dds)
         
            # Store outputs keyed by widget, so that we can look them up in gtk callbacks:
            self.outputs_by_widget[freq_spinbutton] = i, 'freq', freq
            self.outputs_by_widget[amp_spinbutton] = i, 'amp', amp
            self.outputs_by_widget[phase_spinbutton] = i, 'phase', phase
            self.outputs_by_widget[gate_checkbutton] = i, 'gate', gate
            
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
        _results['en0'] = results['en1'] = True
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
            dds.freq.set_value(self.values['freq%d'%i],program=False)
            dds.amp.set_value(self.values['amp%d'%i],program=False)
            dds.phase.set_value(self.values['phase%d'%i],program=False)
            dds.gate.set_state(self.values['en%d'%i],program=False)
        
    @define_state
    def program_static(self,widget):
        # Skip if in buffered mode:
        if self.static_mode:
            # The novatech only programs one output at a time. There
            # is no current code which programs many outputs in quick
            # succession, so there is no speed penalty for this:
            channel, type, output = self.output_by_widget[widget]
            # is an amplitude change:
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
        self.queue_work('transition_to_static')
        # Update the gui to reflect the current hardware values:
        # The final results don't say anything about the checkboxes;
        # turn them on:
        self.final_values['en0'] = self.final_values['en1'] = True
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
        self.old_table = None
        
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
        for i, line in enumerate(response[:2]):
            freq, phase, amp = line.split()
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

    def program_buffered(self,device_name,h5file,initial_values,fresh):
        self.old_table=novatech_programming.program_from_h5_file(self.connection,device_name,h5file,initial_values,self.old_table,fresh)

    def transition_to_static(self):
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        #self.connection.write('I p\r\n')
        #if self.connection.readline() != "OK\r\n":
        #    raise Exception('Error: Failed to execute command: "I p"')
        last_row0=self.old_table[0,:,-1]
        last_row1=self.old_table[1,:,-1]
        self.connection.write('F0 %f\r\n'%(last_row0[0]/10.0**7))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set F0')
        self.connection.write('V0 %u\r\n'%(last_row0[2]))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set V0')
        self.connection.write('P0 %u\r\n'%(last_row0[1]))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set P0')
        self.connection.write('F1 %f\r\n'%(last_row1[0]/10.0**7))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set F1')
        self.connection.write('V1 %u\r\n'%(last_row1[2]))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set V1')
        self.connection.write('P1 %u\r\n'%(last_row1[1]))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to set P1')
        
    def close_connection(self):
        self.connection.close()

