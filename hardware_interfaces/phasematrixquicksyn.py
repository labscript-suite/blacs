######################################################################
## BLACS Tab for the Phase Matrix QuickSyn microwave synthesiser    ##
## Written by Shaun Johnstone, Monash University, December 2012     ##
##                                                                  ##
## This code assumes a QuickSyn with option 4 (USB interface) only  ##
## If you have a QuickSyn with other options, it would be trivial   ##
## to add a query on intialisation to ask which options are present ##
## and dynamically generate the interface as required (e.g. add     ##
## a widget for amplitude control)                                  ##
##                                                                  ##
## Note that I have used the SCPI commands rather than HEX for      ##
## readability. If you only have the SPI interface availiable then  ##
## you're going to need a lot of if statements!                     ##
######################################################################

import gtk
from output_classes import AO, DO, DDS
from tab_base_classes import Tab, Worker, define_state
from time import time
class phasematrixquicksyn(Tab):
    # Capabilities
    num_DDS = 1
       
    base_units = {'freq':'Hz'}
    base_min =   {'freq':0.5e9}
    base_max =   {'freq':10e9}
    base_step =  {'freq':10**6}
        
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,PhaseMatrixQuickSynWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.static_mode = True
        self.destroy_complete = False
        self.com_port = self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection

        
        self.queued_static_updates = 0
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/phasematrixquicksyn.glade')
        self.builder.connect_signals(self)
        
        self.toplevel = self.builder.get_object('toplevel')
        self.main_view = self.builder.get_object('main_vbox')
        self.builder.get_object('title').set_text(self.settings["device_name"]+" - Port: "+self.com_port)
                
        # Get the widgets needed for showing the prompt to push/pull values to/from the Novatech
        self.changed_widgets = {'changed_vbox':self.builder.get_object('changed_vbox')}                
        self.changed_widgets['ch_0_vbox'] = self.builder.get_object('changed_vbox_ch_0')
        self.changed_widgets['ch_0_label'] = self.builder.get_object('new_ch_label_0')
        self.changed_widgets['ch_0_push_radio'] = self.builder.get_object('radiobutton_push_BLACS_0')
        self.changed_widgets['ch_0_pull_radio'] = self.builder.get_object('radiobutton_pull_remote_0')
        
        # Get the widgets needed for showing status stuff
        self.status_widgets = {'temperature':self.builder.get_object('temperature')}
        self.status_widgets['freq_locked'] = [self.builder.get_object('freq_locked_no'),self.builder.get_object('freq_locked_yes')]
        self.status_widgets['ref'] = [self.builder.get_object('ref_no'),self.builder.get_object('ref_yes')]
        self.status_widgets['ref_locked'] = [self.builder.get_object('ref_locked_no'),self.builder.get_object('ref_locked_yes')]
        
        
        
        # Generate a unique channel name (unique to the device instance,
        # it does not need to be unique to BLACS)
        channel = 'DDS 0'
        # Get the connection table entry object
        conn_table_entry = self.settings['connection_table'].find_child(self.settings['device_name'],'dds 0')
        # Get the name of the channel
        # If no name exists, it MUST be set to '-'
        name = conn_table_entry.name if conn_table_entry else '-'
        
        # Set the label to reflect the connected channels name:
        self.builder.get_object('channel_0_label').set_text(channel + ' - ' + name)
        
        # get the widgets for the changed values detection (push/pull to/from device)
        for age in ['old','new']:
            self.changed_widgets['ch_0_%s_freq'%age] = self.builder.get_object('%s_freq'%age)
            self.changed_widgets['ch_0_%s_freq_unit'%age] = self.builder.get_object('%s_freq_unit'%age)
            self.changed_widgets['ch_0_%s_gate'%age] = self.builder.get_object('%s_gate'%age)    
        calib = None
        calib_params = {}
        
        # find the calibration details for this subchannel
        # TODO: Also get their min/max values
        if conn_table_entry:
            if (conn_table_entry.name+'_freq') in conn_table_entry.child_list:
                sub_chnl_entry = conn_table_entry.child_list[conn_table_entry.name+'_freq']
                if sub_chnl_entry != "None":
                    calib = sub_chnl_entry.unit_conversion_class
                    calib_params = eval(sub_chnl_entry.unit_conversion_params)
        
        # Get the widgets from the glade file
        spinbutton = self.builder.get_object('freq_chnl_0')
        unit_selection = self.builder.get_object('freq_unit_chnl_0')
        
        
        # Make output object:
        freq_object = AO(name+'_freq', 
                                  channel+'_freq', 
                                  spinbutton, 
                                  unit_selection, 
                                  calib, 
                                  calib_params, 
                                  self.base_units['freq'], 
                                  self.program_static, 
                                  self.base_min['freq'], 
                                  self.base_max['freq'], 
                                  self.base_step['freq'])
        # Set default values:
        freq_object.update(settings)
        
        
        # Get the widgets for the gate
        gate_togglebutton = self.builder.get_object('active_chnl_0')        
        # Make the gate DO object            
        gate = DO('','Enable', gate_togglebutton, self.program_static)            
        gate.update(settings)
        
        
        
        # Make DO objects for "other options":
        ref_output_toggle = self.builder.get_object('outref')
        self.ref_output = DO('', 'Output reference', ref_output_toggle, self.program_static)            
        self.ref_output.update(settings)
        
        blanking_toggle = self.builder.get_object('blanking')
        self.blanking = DO('', 'Blanking', blanking_toggle, self.program_static)            
        self.blanking.update(settings)
        
        lock_recovery_toggle = self.builder.get_object('lockrecovery')
        self.lock_recovery = DO('', 'Lock Recovery', lock_recovery_toggle, self.program_static)            
        self.lock_recovery.update(settings)
        
        # Store outputs keyed by widget, so that we can look them up in gtk callbacks:
        self.outputs_by_widget = {}
        self.outputs_by_widget[spinbutton.get_adjustment()] = 'freq', freq_object
        self.outputs_by_widget[gate.action] = 'gate', gate
        self.outputs_by_widget[self.ref_output.action] = 'ref_output', self.ref_output
        self.outputs_by_widget[self.blanking.action] = 'blanking', self.blanking
        self.outputs_by_widget[self.lock_recovery.action] = 'lock_recovery', self.lock_recovery
        
        print self.outputs_by_widget
        
        self.dds_outputs = [DDS(freq_object,None,None,gate)]   
        
        # Insert our GUI into the viewport provided by BLACS:    
        self.viewport.add(self.toplevel)
        
        # add the status check timeout
        self.statemachine_timeout_add(10000,self.status_monitor)
        
        # Initialise the device
        self.initialise()
        
        
        
    @define_state
    def initialise(self):
        self.queue_work('initialise', self.com_port, 115200)
        self.do_after('leave_status_monitor')
    
    @define_state
    def status_monitor(self):
        # may as well check status even during buffered mode, in case temp gets high or freq unlocks or something
        self.queue_work('get_current_values')        
        self.do_after('leave_status_monitor')
        
            
    def leave_status_monitor(self,_results=None):
        # If a static_update is already queued up, ignore this as it's soon to be obsolete!
        if self.queued_static_updates > 0:
            self.changed_widgets['changed_vbox'].hide()            
            self.main_view.set_sensitive(True)
            return
    
        # If results are None, then ignore because an exception was raised in the worker process
        if not _results:
            return
    
        self.new_values = _results
        # if we're in static mode, check that the widgets match the output
        if self.static_mode == True:
            fpv = self.get_front_panel_state()
            # Do the values match the front panel?
            changed = False
            
            if _results['freq'] != fpv['freq'] or _results['gate'] != fpv['gate']:
                # freeze the front panel
                self.main_view.set_sensitive(False)
                
                # show changed vbox
                self.changed_widgets['changed_vbox'].show()
                self.changed_widgets['ch_0_vbox'].show()
                self.changed_widgets['ch_0_label'].set_text(self.builder.get_object("channel_0_label").get_text())
                changed = True
                
                # populate the labels with the values
                for age in ['old','new']:
                    self.changed_widgets['ch_0_%s_freq'%age].set_text(str(_results['freq'] if age == 'new' else fpv['freq']))
                    self.changed_widgets['ch_0_%s_freq_unit'%age].set_text(self.base_units['freq'])
                    self.changed_widgets['ch_0_%s_gate'%age].set_text(str(_results['gate'] if age == 'new' else fpv['gate']))                  
            else:                
                self.changed_widgets['ch_0_vbox'].hide()
                    
            if not changed:
                self.changed_widgets['changed_vbox'].hide()            
                self.main_view.set_sensitive(True)
        # but if we are in buffered mode, don't complain about the front panel, we'll sort that out at the end of the run!
        else:
            self.changed_widgets['changed_vbox'].hide()            
            self.main_view.set_sensitive(True)
    
        #now let's update other widgets, like the temperature and lock status:
        self.status_widgets['temperature'].set_text(str(_results['temperature']))
        if _results['temperature'] > 55:
            raise Exception('WARNING: Temperature is too high!')
        self.status_widgets['freq_locked'][_results['freqlock']].show()
        self.status_widgets['freq_locked'][int(not _results['freqlock'])].hide()
        
        self.status_widgets['ref'][_results['ref']].show()
        self.status_widgets['ref'][int(not _results['ref'])].hide()
        
        self.status_widgets['ref_locked'][_results['reflock']].show()
        self.status_widgets['ref_locked'][int(not _results['reflock'])].hide()
        
    @define_state
    def continue_after_change(self,widget=None):
        values = self.new_values
        fpv = self.get_front_panel_state()
        # do we want to use the front panel values (only applies to channels we showed changed values for)?
        if not self.changed_widgets['ch_0_pull_radio'].get_active() and self.changed_widgets['ch_0_vbox'].get_visible():
            values['freq'] = fpv['freq']
            values['gate'] = fpv['gate']
                
            # actually make it program.
            # we explicitly do this because setting the widget to the value it is already set to, will never trigger a program call, 
            # since we deliberately ignore such calls to limit possible recursion due to programming errors
            self.program_channel('freq', fpv['freq'])
            self.program_channel('gate', fpv['gate'])
                
                            
        self.main_view.set_sensitive(True)
        self.changed_widgets['changed_vbox'].hide()     
        self.set_front_panel_state(values,program=True)
    
        
    @define_state
    def destroy(self):
        self.queue_work('close_connection')
        self.do_after('leave_destroy')
    
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
    
    def get_front_panel_state(self):
        return {"freq":self.dds_outputs[0].freq.value,
        "gate":int(self.dds_outputs[0].gate.state),
        "ref_output":int(self.ref_output.state),
        "blanking":int(self.blanking.state),
        "lock_recovery":int(self.lock_recovery.state)}
    
    def set_front_panel_state(self, values, program=False):
        """Updates the gui without reprogramming the hardware"""
        dds = self.dds_outputs[0]
        if 'freq' in values:
            dds.freq.set_value(values['freq'],program)
        if 'gate' in values:
            dds.gate.set_state(values['gate'],program)
        if 'ref_output' in values:
            self.ref_output.set_state(values['ref_output'],program)
        if 'blanking' in values:
            self.blanking.set_state(values['blanking'],program)
        if 'lock_recovery' in values:
            self.lock_recovery.set_state(values['lock_recovery'],program)
    #@define_state
    def program_static(self,widget):
        # Skip if in buffered mode:
        if self.static_mode:
            
            type, output = self.outputs_by_widget[widget]
            
            if type == 'freq':
                value = output.value
            else:
                value = output.state
            
            self.queued_static_updates += 1
            self.program_channel(type,value)
            
    @define_state
    def program_channel(self,type,value):
        self.queue_work('program_static', type, value)
        self.do_after('leave_program_static',type)
            
    def leave_program_static(self,type,_results):
        # update the front panel value to what it actually is in the device
        if self.queued_static_updates < 2:
            self.queued_static_updates -= 1
            if self.queued_static_updates < 0:
                self.queued_static_updates = 0
            self.set_front_panel_state({type:_results})
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False 
        self.queue_work('program_buffered',self.settings['device_name'],h5file,self.get_front_panel_state())
        self.do_after('leave_program_buffered',notify_queue)        
    
    def leave_program_buffered(self,notify_queue,_results):
        
        # These are the final values that the quicksyn will be in
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
        # Tell the queue manager once we're done:
        self.do_after('leave_transition_to_static',notify_queue)
        # Update the gui to reflect the current hardware values:
        if not abort:
            # The final results don't say anything about the checkboxes;
            # turn them on:
            #for i in range(4):
                #self.final_values['en%d'%i] = True
            self.set_front_panel_state(self.final_values)
        self.static_mode=True
    
    def leave_transition_to_static(self,notify_queue,_results):    
        # Tell the queue manager that we're done:
        if notify_queue is not None:
            notify_queue.put(self.device_name)
            
        self.set_front_panel_state(_results)
            
    
        
    def get_child(self,type,channel):
        """Allows virtual devices to obtain this tab's output objects"""
        if type == "DDS":
            if channel in range(self.num_DDS):
                return self.dds_outputs[channel]
        return None
        
        
class PhaseMatrixQuickSynWorker(Worker):
    def init(self):
        global serial; import serial
        global h5py; import h5_lock, h5py
        global time; import time
        
        
    def initialise(self,port,baud_rate):
        self.connection = serial.Serial(port, baudrate = baud_rate, timeout=0.1)
        self.connection.readlines()
        
        #check to see if the reference is set to external. If not, make it so! (should we ask the user about this?)
        self.connection.write('ROSC:SOUR?\r')
        response = self.connection.readline()
        if response == 'INT\n':
            #ref was set to internal, let's change it to ext
            self.connection.write('ROSC:SOUR EXT\r')
        
        
        
        return self.get_current_values()
        
    def get_current_values(self):
        # Get the currently output values:
        
        results = {}
        line = ''
        count = 0
        self.connection.write('FREQ?\r')
        line = self.connection.readline()
        
        if line == '':
            raise Exception("Device didn't say what its frequncy was :(")
        # Convert mHz to Hz:
        results['freq'] = float(line)/1000
        
        # wait a little while first, it doesn't like being asked things too quickly!
        time.sleep(0.05)
        self.connection.write('STAT?\r')
        line = self.connection.readline()
        if line == '':
            raise Exception("Device didn't say what its status was :(")
        time.sleep(0.05)    
            
        
        #get the status and convert to binary, and take off the '0b' header:
        status = bin(int(line,16))[2:]
        # if the status is less than 8 bits long, pad the start with zeros!
        while len(status)<8:
            status = '0'+status
        # byte 0 is the 1 for an external ref, 0 for no external ref
        results['ref'] = int(status[-1])
        # byte 1 is high for rf unlocked, low for rf locked. This is silly, let's reverse it!
        results['freqlock'] = int(not int(status[-2]))
        # byte 2 is the high for ref unlocked, low for ref locked. Again, let's swap this!
        results['reflock'] = int(not int(status[-3]))
        # byte 3 tells us if the output is on or off
        results['gate'] = int(status[-4])
        
        # byte 4 will go high if there is a voltage error.
        #In this case, we probably just want to raise an exception to get the user's attention
        if int(status[-5]):
            self.logger.critical('Device is reporting voltage error')
            raise Exception('Voltage error')
        # byte 5 tells us if the internal reference is being output
        results['ref_output'] = int(status[-6])
        # byte 6 tells us if blanking is on (i.e. turning off output while it changes frequency)
        results['blanking'] = int(status[-7])
        # byte 7 tells us if lock recovery is on,
        
        results['lock_recovery'] = int(status[-8])
        
        # now let's check it's temperature!
        self.connection.write('DIAG:MEAS? 21\r')
        results['temperature'] = float(self.connection.readline())
        
        
        return results
        
    def program_static(self,type,value):
        
        if type == 'freq':
            #program in millihertz:
            value = value*1e3
            command = 'FREQ %i\r'%value
            self.connection.write(command)
            
        elif type == 'gate':
            command = 'OUTP:STAT %i\r'%value
            self.connection.write(command)
            
        elif type == 'ref_output':
            command = 'OUTP:ROSC %i\r'%value
            self.connection.write(command)
            
        elif type == 'blanking':
            command = 'OUTP:BLAN %i\r'%value
            self.connection.write(command)
            
        elif type == 'lock_recovery':
            command = 'FREQ:LRSTAT %i\r'%value
            self.connection.write(command)
        
        else:
            raise TypeError(type)
        
        time.sleep(0.05)
        return self.get_current_values()[type]
       
    def program_buffered(self,device_name,h5file,initial_values):
        # Store the initial values in case we have to abort and restore them:
        self.initial_values = initial_values
        # Store the final values to for use during transition_to_static:
        self.final_values = {}
        with h5py.File(h5file) as hdf5_file:
            group = hdf5_file['/devices/'+device_name]
            # If there are values to set the unbuffered outputs to, set them now:
            if 'STATIC_DATA' in group:
                data = group['STATIC_DATA'][0]
                
                self.connection.write('FREQ %i\r'%(data['freq0']))
                time.sleep(0.05)
                # At present, we are forcing the output to be enabled always,
                # as StaticDigitalOut of the PhaseMatrix doesn't have a pseudoclock parent
                # self.connection.write('OUTP:STAT %i'%(data['gate0']))
                self.connection.write('OUTP:STAT 1')
                
                
                # Save these values into final_values so the GUI can
                # be updated at the end of the run to reflect them:
                self.final_values['freq'] = data['freq0']/1e3
                self.final_values['gate'] = 1
                
            return self.final_values
            
    def transition_to_static(self,abort = False):
        
        if abort:
            # If we're aborting the run, reset to original value
            values = self.initial_values
            self.program_static('freq',values['freq'])
            self.program_static('gate',values['gate'])
        
        # If we're not aborting the run, stick with buffered value. Nothing to do really!
        # return the current values in the device
        return self.get_current_values()
                     
    def close_connection(self):
        self.connection.close()
        
