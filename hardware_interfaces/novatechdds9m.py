from hardware_interfaces.output_types.RF import *
import gobject
import pygtk
import gtk
import serial

from tab_base_classes import Tab, Worker, define_state

class novatechdds9m(Tab):

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
        Tab.__init__(self,NovatechDDS9mWorker,notebook,settings)
        self.init_done = False
        self.static_mode = True
        self.destroy_complete = False
        
        # Capabilities
        self.num_RF = 4
        self.freq_min = 0.0000001   # In MHz
        self.freq_max = 170.0       # In MHz
        self.amp_min = 0            # In Vpp
        self.amp_max = 1023         # In Vpp
        self.phase_min = 0          # In Degrees
        self.phase_max = 360        # In Degrees
		
        self.settings = settings
		
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/novatechdds9m.glade')
        
        self.builder.get_object('title').set_text(self.settings["device_name"]+" - Port: "+self.settings["COM"])
        
        # Need to connect signals!
        self.builder.connect_signals(self)
        
        self.rf_widgets = []
        self.rf_outputs = []
        self.amp_toggles = []
        for i in range(0,self.num_RF):
            w1 = self.builder.get_object("frequency_adj_"+str(i))
            w2 = self.builder.get_object("amplitude_adj_"+str(i))
            w3 = self.builder.get_object("phase_adj_"+str(i))
                    
            self.rf_widgets.append([w1,w2,w3])
            self.amp_toggles.append(self.builder.get_object("amp_switch_"+str(i)))
            hardware_name = "Channel "+str(i)
            channel_name = self.settings["connection_table"].find_child(self.settings["device_name"],"channel "+str(i))
            if channel_name is not None:
                real_name = " - "+channel_name.name
            else:
                real_name = ""

            self.builder.get_object("channel_"+str(i)+"_label").set_text(hardware_name + real_name)

            # Make RF objects
            self.rf_outputs.append(RF(self,self.static_update,self.program_static,i,hardware_name,real_name,[self.freq_min,self.freq_max,self.amp_min,self.amp_max,self.phase_min,self.phase_max]))
           
        self.toplevel = self.builder.get_object('toplevel')
        self.toplevel.hide()
        self.viewport.add(self.toplevel)
        # These two functions are queued up in the statemachine.
        # Once complete, the toplevel object is shown.
        self.initialise_connection()
        self.set_defaults()        
        #notebook.append_page(self.tab,gtk.Label(self.settings["device_name"]))  
        #notebook.set_tab_reorderable(self.tab,True)
        
        # These will queue up the GTK event callbacks. We want these to queue up after the initialise and set defaults
        
	
    @define_state
    def destroy(self):
        self.queue_work('close_connection')
        self.do_after('leave_destroy')
    
    def leave_destroy(self,_results):
        self.destroy_complete = True
        
	
    @define_state
    def set_defaults(self):
        self.queue_work('read_current_values')
        self.do_after('leave_set_defaults')       
    
    def leave_set_defaults(self,_results):
        for i in range(0,self.num_RF):
            settings = _results[i].split()
            f = float(int(settings[0],16))/10**7
            p = int(settings[1],16)*360/16384.0
            a = int(settings[2],16)
            self.rf_outputs[i].update_value(f,a,p)
            self.rf_widgets[i][0].set_value(f)
            self.rf_widgets[i][1].set_value(a)
            self.rf_widgets[i][2].set_value(p)
        
        
        # Complete the init method!
        self.toplevel.show()
        self.init_done = True 
        self.static_mode = True  
    
    
    @define_state
    def initialise_connection(self):
        self.queue_work('initialise_connection', self.settings["COM"], 115200)
    
    @define_state
    def static_update(self,output):
        if not self.init_done or not self.static_mode:
            return        
        # convert numbers to correct representation
        
        output.phase = (int((output.phase/360)*16384)/16384.0)*360
        
                
        #find channel
        channel = None
        for i in range(0,self.num_RF):
            if output == self.rf_outputs[i]:
                channel = i
                break
    
        if channel is None:
            #return error
            pass        
            
        # Update GUI
        if self.rf_widgets[channel][0].get_value() != output.freq:            
            self.rf_widgets[channel][0].set_value(output.freq)
        
        if self.rf_widgets[channel][1].get_value() != output.amp:
            self.rf_widgets[channel][1].set_value(output.amp)
                
        if self.rf_widgets[channel][2].get_value() != output.phase:
            self.rf_widgets[channel][2].set_value(output.phase)
    
    @define_state
    def program_static(self,output):    
        if not self.init_done or not self.static_mode:
            return
            
        #find channel
        channel = None
        for i in range(0,self.num_RF):
            if output == self.rf_outputs[i]:
                channel = i
                break
    
        if channel is None:
            #return error
            return     
        
        self.queue_work('program_static',channel,output.freq,output.amp,output.phase)
        
        
        
    def get_child(self,type,channel):
        if type == "RF":
            if channel >= 0 and channel < self.num_RF:
                return self.rf_outputs[channel]
        
        return None
    
    def transition_to_buffered(self,h5file):        
        # disable static update
        self.transitioned_to_buffered = False
        # Queue transition in state machine
        self.program_buffered(h5file)
        
    @define_state
    def program_buffered(self,h5file):
        self.static_mode = False 
        
        initial_values = {"freq0":self.rf_outputs[0].freq, "amp0":self.rf_outputs[0].amp, "phase0":self.rf_outputs[0].phase,
                          "freq1":self.rf_outputs[1].freq, "amp1":self.rf_outputs[1].amp, "phase1":self.rf_outputs[1].phase,
                          "freq2":self.rf_outputs[2].freq, "amp2":self.rf_outputs[2].amp, "phase2":self.rf_outputs[2].phase,
                          "freq3":self.rf_outputs[3].freq, "amp3":self.rf_outputs[3].amp, "phase3":self.rf_outputs[3].phase}
                          
        self.queue_work('program_buffered',self.settings['device_name'],h5file,initial_values)
        self.do_after('leave_program_buffered')        
    
    def leave_program_buffered(self,_results):
        self.transitioned_to_buffered = True    
    
    def abort_buffered(self):
        self.transition_to_static()
    
    @define_state    
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is sending out updates.         
                       
        #turn buffered mode off, output values in buffer to ensure it outputs what it says in que
        self.queue_work('transition_to_static')
        #update the panel to reflect the current state of the novatech
        # static_mode=True is set in the set_defaults state
        self.set_defaults()

    @define_state
    def on_value_change(self,widget):
        if not self.init_done:
            return
      
        update_channel = None
        for i in range(0,self.num_RF):
            for j in range(0,3):
                if widget == self.rf_widgets[i][j]:
                    update_channel = i
                    break
            if widget == self.amp_toggles[i]:
                update_channel = i
                break
            if update_channel is not None:
                break
        
        if update_channel is None:
            print 'something went wrong'
            print type(widget)
            return
        if self.amp_toggles[i].get_active():    
            self.rf_outputs[update_channel].update_value(self.rf_widgets[update_channel][0].get_value(),self.rf_widgets[update_channel][1].get_value(),self.rf_widgets[update_channel][2].get_value())
        else:
            self.queue_work('program_static',update_channel,self.rf_widgets[update_channel][0].get_value(),0,self.rf_widgets[update_channel][2].get_value())
        
class NovatechDDS9mWorker(Worker):
    def init(self):
        global serial; import serial
        global novatech_programming; from hardware_programming import novatech as novatech_programming
        self.connection = None
    
    def initialise_connection(self,port,baud_rate):
        self.connection = serial.Serial(port, baudrate = baud_rate, timeout=0.1)                
        
        self.connection.write('e d\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "e d"')
        
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')                                           
        
        return True
        
    def read_current_values(self):
        self.connection.write('QUE\r\n')
        return self.connection.readlines()
    
    def program_static(self,channel,freq,amp,phase):
        # program hardware                   
        self.connection.write('F%d %f\r\n'%(channel,freq))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: '+'F%d %f\r\n'%(channel,freq))         

        self.connection.write('V%d %u\r\n'%(channel,amp))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: '+'V%d %u\r\n'%(channel,amp))          

        self.connection.write('P%d %u\r\n'%(channel,phase*16384/360))
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: '+'P%d %u\r\n'%(channel,phase*16384/360))              
    
    def program_buffered(self,device_name,h5file,initial_values):    
        novatech_programming.program_from_h5_file(self.connection,device_name,h5file,initial_values)
    
    def transition_to_static(self):        
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        self.connection.write('I p\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I p"')
            
    def close_connection(self):
        self.connection.close()
                
