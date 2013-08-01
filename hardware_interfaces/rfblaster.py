import gtk

import os

from numpy import *
from output_classes import AO, DO, DDS
from tab_base_classes import Tab, Worker, define_state

class rfblaster(Tab):
    # Capabilities
    num_DDS = 2
    
    base_units = {'freq':'Hz',        'amp':'%', 'phase':'Degrees'}
    base_min =   {'freq':500000,         'amp':0.0,   'phase':0}
    base_max =   {'freq':350000000.0, 'amp':99.99389648,   'phase':360}
    base_step =  {'freq':1000000,           'amp':1.0,  'phase':1}
    
        
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,RFBlasterWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.address = "http://" + str(self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection) + ":8080"
        self.static_mode = True
        self.static_updates_queued = 0
        self.finished_buffered = True
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'rfblaster.glade'))
        self.builder.connect_signals(self)
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text('%s - %s'%(self.settings['device_name'],self.address))
        self.changed_view = self.builder.get_object('changed_vbox')
        self.resolve_changes = self.builder.get_object('resolve_changes')
        self.main_view = self.builder.get_object('main_vbox')
        self.dds_outputs = []
        #self.changed_outputs = {'f':[],'a':[],'p':[]}
        # Get the widgets needed for showing the prompt to push/pull values to/from the Novatech
        self.changed_widgets = {'changed_vbox':self.builder.get_object('changed_vbox')}   
        #self.radio_widgets = {}
        
        for i in range(self.num_DDS):
            # Generate a unique channel name (unique to the device instance,
            # it does not need to be unique to BLACS)
            channel = 'DDS %d'%i
            # Get the connection table entry object
            conn_table_entry = self.settings['connection_table'].find_child(self.settings['device_name'],'dds %d'%i)
            # Get the name of the channel
            # If no name exists, it MUST be set to '-'
            name = conn_table_entry.name if conn_table_entry else '-'
            
            # Set the label to reflect the connected channels name:
            self.builder.get_object('channel_%d_label'%i).set_text(channel + ' - ' + name)
            gate_checkbutton = self.builder.get_object("amp_switch_%d"%i)
            
            # get the widgets for the changed values detection (push/pull to/from device)
            self.changed_widgets['ch_%d_vbox'%i] = self.builder.get_object('changed_vbox_ch_%d'%i)
            self.changed_widgets['ch_%d_label'%i] = self.builder.get_object('new_ch_label_%d'%i)
            self.changed_widgets['ch_%d_push_radio'%i] = self.builder.get_object('radiobutton_push_BLACS_%d'%i)
            self.changed_widgets['ch_%d_pull_radio'%i] = self.builder.get_object('radiobutton_pull_remote_%d'%i)
            #self.changed_outputs['f'].append(self.builder.get_object('new_freq_%d'%i))
            #self.changed_outputs['a'].append(self.builder.get_object('new_amp_%d'%i))
            #self.changed_outputs['p'].append(self.builder.get_object('new_phase_%d'%i))
            
            # Save the radio widgets for when values on the RfBlaster change without the tabs knowledge
            #self.radio_widgets['%d_push_BLACS'%i] = self.builder.get_object('radiobutton_push_BLACS_%d'%i)
            #self.radio_widgets['%d_pull_remote'%i] = self.builder.get_object('radiobutton_pull_remote_%d'%i)
            
            # Loop over freq,amp,phase and create AO objects for each
            ao_objects = {}
            sub_chnl_list = ['freq','amp','phase']
            for sub_chnl in sub_chnl_list:
                # get the widgets for the changed values detection (push/pull to/from device)
                for age in ['old','new']:
                    self.changed_widgets['ch_%d_%s_%s'%(i,age,sub_chnl)] = self.builder.get_object('%s_%s_%d'%(age,sub_chnl,i))
                    self.changed_widgets['ch_%d_%s_%s_unit'%(i,age,sub_chnl)] = self.builder.get_object('%s_%s_unit_%d'%(age,sub_chnl,i))
                    
                calib = None
                calib_params = {}
                
                # find the calibration details for this subchannel
                # TODO: Also get their min/max values
                if conn_table_entry:
                    if (conn_table_entry.name+'_'+sub_chnl) in conn_table_entry.child_list:
                        sub_chnl_entry = conn_table_entry.child_list[conn_table_entry.name+'_'+sub_chnl]
                        if sub_chnl_entry != "None":
                            calib = sub_chnl_entry.unit_conversion_class
                            calib_params = eval(sub_chnl_entry.unit_conversion_params)
                
                # Get the widgets from the glade file
                spinbutton = self.builder.get_object(sub_chnl+'_chnl_%d'%i)
                unit_selection = self.builder.get_object(sub_chnl+'_unit_chnl_%d'%i)
                        
                # Make output object:
                ao_objects[sub_chnl] = AO(name+'_'+sub_chnl, 
                                          channel+'_'+sub_chnl, 
                                          spinbutton, 
                                          unit_selection, 
                                          calib, 
                                          calib_params, 
                                          self.base_units[sub_chnl], 
                                          self.program_static, 
                                          self.base_min[sub_chnl], 
                                          self.base_max[sub_chnl], 
                                          self.base_step[sub_chnl])
                # Set default values:
                ao_objects[sub_chnl].update(settings)                
            
            # Get the widgets for the gate
            #gate_togglebutton = self.builder.get_object('active_chnl_%d'%i)        
            # Make the gate DO object            
            gate = DO(name+'_gate', channel+'_gate', gate_checkbutton, self.program_static)
            gate.update(settings)
                    
            # Construct the DDS object and store for later access:
            self.dds_outputs.append(DDS(ao_objects['freq'],ao_objects['amp'],ao_objects['phase'],gate))
            
        self.statemachine_timeout_add(30000,self.status_monitor)
        
        # Insert our GUI into the viewport provided by BLACS:
        self.viewport.add(self.toplevel)
        
        #self.last_programmed_values = self.get_front_panel_state()
        
        # Initialise the RFblaster:
        self.initialise_rfblaster()
        
        # Program the hardware with the initial values of everything:
        self.program_static()  

    @define_state
    def initialise_rfblaster(self):
        self.queue_work('initialise_rfblaster',self.device_name,self.address,self.num_DDS)
        
    @define_state
    def destroy(self):        
        self.destroy_complete = True
        self.close_tab()
    
    
        
    def get_front_panel_state(self):
        f = zeros(self.num_DDS)
        a = zeros(self.num_DDS)
        p = zeros(self.num_DDS)
        e = zeros(self.num_DDS)
        for i in range(self.num_DDS):
            f[i]=self.dds_outputs[i].freq.value
            a[i]=self.dds_outputs[i].amp.value
            p[i]=self.dds_outputs[i].phase.value
            e[i]=self.dds_outputs[i].gate.state
        return {'f':f,'a':a,'p':p,'e':e}
    
    
    @define_state
    def status_monitor(self):
        if self.static_updates_queued == 0 and self.static_mode == True:
            
            # If we've just come out of buffered mode, and haven't reprogrammed the device since,
            # then we should compare the web values with the values they had when we programmed
            # the buffered sequence. This is a bit of a hack, and misses occasions where someone
            # goes onto the webpage and just hits "Set device" without changing any numbers, but
            # will warn the user about any other interfering events on the website
            if self.finished_buffered == True:
                front_panel = self.post_buffered_web_vals
            else:
                front_panel = self.get_front_panel_state()
                #front_panel = self.last_programmed_values
            
            self.queue_work('compare_web_values',front_panel)
            self.do_after('status_monitor_leave')
        else:
            self.main_view.set_sensitive(True)
            self.changed_widgets['changed_vbox'].hide()
        
    def status_monitor_leave(self,_results):
        changed,self.new_values = _results
        
        fpv = self.get_front_panel_state()
        # Do the values match the front panel?
        show_changed = False
        for i in range(self.num_DDS):
            # The changed array has an entry for f,a,p (0,1,2) where each entry is an array of True/False for each channel
            if changed[0][i] or changed[1][i] or changed[2][i]:
                # freeze the front panel
                self.main_view.set_sensitive(False)
                
                # show changed vbox
                self.changed_widgets['changed_vbox'].show()
                self.changed_widgets['ch_%d_vbox'%i].show()
                self.changed_widgets['ch_%d_label'%i].set_text(self.builder.get_object("channel_%d_label"%i).get_text())
                show_changed = True
                
                # populate the labels with the values
                list1 = ['new','old']
                list2 = ['freq','amp','phase']
                list3 = ['f','a','p']
                
                for name in list1:
                    for subchnl,subchnl2 in zip(list2,list3):
                        new_name = name+'_'+subchnl
                        self.changed_widgets['ch_%d_'%i+new_name].set_text(str(self.new_values[subchnl2][i] if name == 'new' else fpv[subchnl2][i]))
                        self.changed_widgets['ch_%d_'%i+new_name+'_unit'].set_text(self.base_units[subchnl])                       
                                
            else:                
                self.changed_widgets['ch_%d_vbox'%i].hide()
                
        if not show_changed:
            self.changed_widgets['changed_vbox'].hide()            
            self.main_view.set_sensitive(True)
        
        # if changed:
            # #Time to warn the user that someone's been playing with the webserver!
            # self.main_view.set_sensitive(False)
            # self.changed_view.set_visible(True)
            # [widget.set_text(str(value)) for widget,value in zip(self.changed_outputs['f'],self.new_values['f'])]
            # [widget.set_text(str(value)) for widget,value in zip(self.changed_outputs['a'],self.new_values['a'])]
            # [widget.set_text(str(value)) for widget,value in zip(self.changed_outputs['p'],self.new_values['p'])]
        # else:
            # self.main_view.set_sensitive(True)
            # self.changed_view.set_visible(False)
    
    @define_state
    def continue_after_change(self,widget=None):
        self.static_mode = True   
        do_program = False
        for i, dds in enumerate(self.dds_outputs):
            # do we want to use the remote values?
            if self.changed_widgets['ch_%d_pull_radio'%i].get_active() and self.changed_widgets['ch_%d_vbox'%i].get_visible():
                dds.freq.set_value(self.new_values['f'][i],program=False)
                dds.amp.set_value(self.new_values['a'][i],program=False)
                dds.phase.set_value(self.new_values['p'][i],program=False)
                dds.gate.set_state(True,program=False)
            elif self.changed_widgets['ch_%d_vbox'%i].get_visible():
                # we are using front panel values, so program!
                do_program = True
                
        self.main_view.set_sensitive(True)
        self.changed_widgets['changed_vbox'].hide() 
        if do_program:
            self.queue_work('program_static',self.get_front_panel_state())
            self.do_after('leave_program_static')
        
        
    
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    # Static update of hardware (unbuffered)
    
    def program_static(self,widget=None):
        # Don't allow events to pile up; only two allowed in the queue at a time.
        # self.get_front_panel_state() is only called when program_static_state() runs, and so
        # the effect of clicking many times quickly is that only the first and last updates happen.
        # This is usually what you want, if you click n times, the result is that the last click you
        # made is the one which is programmed.
        if self.static_updates_queued < 2:
            self.static_updates_queued += 1
            self.program_static_state()
    
    @define_state
    def program_static_state(self,widget=None):
        # Skip if in buffered mode:
        if self.static_mode:
            self.queue_work('program_static',self.get_front_panel_state())
        self.do_after('leave_program_static')
        
    def leave_program_static(self,_results):
        actual_values = _results
        self.finished_buffered = False
        self.static_updates_queued -= 1
        if self.static_updates_queued <0:
            self.static_updates_queued = 0
        if self.static_updates_queued == 0:
            for i, dds in enumerate(self.dds_outputs):
                dds.freq.set_value(actual_values['f'][i],program=False)#Front panel needs Hz
                if dds.gate.state:
                    dds.amp.set_value(actual_values['a'][i],program=False)
                dds.phase.set_value(actual_values['p'][i],program=False)
        
        
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False 
        initial_values = self.get_front_panel_state()
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        # These are the final values that the rfblaster will be in
        # at the end of the run. Store them so that we can use them
        # in transition_to_static:
        self.final_values,self.post_buffered_web_vals = _results
        
        # Notify the queue manager thread that we've finished
        # transitioning to buffered:
        notify_queue.put(self.device_name)
       
    @define_state
    def abort_buffered(self):
        # Might want to transition to static here...
        self.static_mode = True
        self.queue_work('abort_buffered')
        
        
    @define_state
    def transition_to_static(self,notify_queue):
        self.static_mode = True
        self.finished_buffered = True
        if notify_queue is not None:
            notify_queue.put(self.device_name)
        #self.queue_work('program_static',self.final_values)
        #self.do_after('leave_transition_to_static',notify_queue)
        # Update the GUI with the final values of the run:
        for i, dds in enumerate(self.dds_outputs):
           dds.freq.set_value(self.final_values['f'][i],program=False)#Front panel needs Hz
           dds.amp.set_value(self.final_values['a'][i],program=False)
           dds.phase.set_value(self.final_values['p'][i],program=False)
           dds.gate.set_state(self.final_values['e'][i],program=False)
    #def leave_transition_to_static(self,notify_queue,_results):    
        # Tell the queue manager that we're done:
     #   if notify_queue is not None:
      #      notify_queue.put(self.device_name)
       # self.leave_program_static(_results)


            
    def get_child(self,type,channel):
        """Allows virtual devices to obtain this tab's output objects"""
        if type == 'DDS':
            if channel in range(self.num_DDS):
                return self.dds_outputs[channel]
        return None
        
    
class RFBlasterWorker(Worker):
    def init(self):
        exec 'from multipart_form import *' in globals()
        exec 'from numpy import *' in globals()
        global h5py; import h5_lock, h5py
        global urllib2; import urllib2
        global re; import re
        self.timeout = 30 #How long do we wait until we assume that the RFBlaster is dead? (in seconds)
    
    def initialise_rfblaster(self, device_name,address,num_DDS):
        self.address = address
        self.device_name = device_name
        self.num_DDS = num_DDS
        # See if the RFBlaster answers
        urllib2.urlopen(address,timeout=self.timeout)
        

    def program_static(self,values):
        
        form = MultiPartForm()
        for i in range(self.num_DDS):
            # Program the frequency, amplitude and phase
            form.add_field("a_ch%d_in"%i,str(values['a'][i]*values['e'][i]))
            form.add_field("f_ch%d_in"%i,str(values['f'][i]*1e-6)) # method expects MHz
            form.add_field("p_ch%d_in"%i,str(values['p'][i]))
            
        form.add_field("set_dds","Set device")
        # Build the request
        req = urllib2.Request(self.address)
        #raise Exception(form_values)
        body = str(form)
        req.add_header('Content-type', form.get_content_type())
        req.add_header('Content-length', len(body))
        req.add_data(body)
        response = str(urllib2.urlopen(req,timeout=self.timeout).readlines())
        webvalues = self.get_web_values(response)
        return webvalues
        
    def program_buffered(self,h5file):
    
        self.logger.debug('opening h5 file')
        with h5py.File(h5file,'r') as hdf5_file:
            self.logger.debug('h5 file opened')
            group = hdf5_file['devices'][self.device_name]
            #Strip out the binary files and submit to the webserver
            form = MultiPartForm()
            finalfreq = zeros(self.num_DDS)
            finalamp = zeros(self.num_DDS)
            finalphase = zeros(self.num_DDS)
            for i in range(self.num_DDS):
                data = group['BINARY_CODE/DDS%d'%i].value
                form.add_file_content("pulse_ch%d"%i,"output_ch%d.bin"%i,data)
                finalfreq[i]=group['TABLE_DATA']["freq%d"%i][-1]
                finalamp[i]=group['TABLE_DATA']["amp%d"%i][-1]*100
                finalphase[i]=group['TABLE_DATA']["phase%d"%i][-1]
            form.add_field("upload_and_run","Upload and start")
            req = urllib2.Request(self.address)

            body = str(form)
            req.add_header('Content-type', form.get_content_type())
            req.add_header('Content-length', len(body))
            req.add_data(body)
            post_buffered_web_vals = self.get_web_values(str(urllib2.urlopen(req,timeout = self.timeout).readlines()))
            #Find the final value from the human-readable part of the h5 file to use for
            #the front panel values at the end
            
            
            # Now we build a dictionary of the final state to send back to the GUI:
            self.final_values = {"f":finalfreq,"a":finalamp,"p":finalphase,"e": ones(self.num_DDS)} #note, GUI wants Hz
            self.logger.debug('h5 file closed')
            return self.final_values, post_buffered_web_vals
            
    def abort_buffered(self):
        form = MultiPartForm()
        #tell the rfblaster to stop
        form.add_field("halt","Halt execution")
        req = urllib2.Request(self.address)
        body = str(form)
        req.add_header('Content-type', form.get_content_type())
        req.add_header('Content-length', len(body))
        req.add_data(body)
        urllib2.urlopen(req,timeout=self.timeout)
        
        
    def get_web_values(self,page):
        
        #prepare regular expressions for finding the values:
        search = re.compile(r'name="([fap])_ch(\d+?)_in"\s*?value="([0-9.]+?)"')
        
        webvalues = re.findall(search,page)
        newvals = {'f':zeros(self.num_DDS),'a':zeros(self.num_DDS),'p':zeros(self.num_DDS),'e':ones(self.num_DDS)}
        for register,channel,value in webvalues:
            newvals[register][int(channel)] = float(value)
        newvals['f'] = array([val*1e6 for val in newvals['f']])
        return newvals
    
    def compare_web_values(self,front_panel):
        #read the webserver page to see what values it puts in the form
        page = str(urllib2.urlopen(self.address,timeout=self.timeout).readlines())
        webvalues = self.get_web_values(page)
        front_panel['a'] = array([val*enable for val,enable in zip(front_panel['a'],front_panel['e'])])
        #raise Exception((webvalues,front_panel))
        changed = array([(a==b) for a,b in [(webvalues[key],front_panel[key]) for key in ['f','a','p']]])
        for i,row in enumerate(changed):
            for j,element in enumerate(row):
                changed[i][j] = not element
        
        return changed,webvalues
        
