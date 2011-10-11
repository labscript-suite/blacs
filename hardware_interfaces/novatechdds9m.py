from hardware_interfaces.output_types.RF import *
import gobject
import pygtk
import gtk
import serial
from hardware_programming import novatech as novatech_programming
class novatechdds9m(object):

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
		
        self.init_done = False
        self.static_mode = True
        # Capabilities
        self.num_RF = 4
				
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
        for i in range(0,self.num_RF):
            w1 = self.builder.get_object("freq_chnl_"+str(i))
            w2 = self.builder.get_object("amp_chnl_"+str(i))
            w3 = self.builder.get_object("phase_chnl_"+str(i))
                    
            self.rf_widgets.append([w1,w2,w3])

            hardware_name = "Channel "+str(i)
            real_name = "blah"

            self.builder.get_object("channel_"+str(i)+"_label").set_text(hardware_name + " - " + real_name)

            # Make RF objects
            self.rf_outputs.append(RF(self,self.static_update,i,hardware_name,real_name,[0.0000001,170.0,0.0,1.0,0,360]))
            
                
        
        try:    
            self.connection = serial.Serial(self.settings["COM"], baudrate = 19200, timeout=0.1)

            self.connection.write('i a\r\n')
            self.connection.readline()
            self.connection.write('m 0\r\n')
            self.connection.readline()
            self.connection.write('e d\r\n')
            self.connection.readline()
                                       
        except:
            print "help, I'm broken!?"
            
        
        self.set_defaults()
        self.tab = self.builder.get_object('toplevel')
        notebook.append_page(self.tab,gtk.Label(self.settings["device_name"]))  

		
    def set_defaults(self):
        try:
            self.connection.write('QUE\r\n')
            values = self.connection.readlines()
            for i in range(0,self.num_RF):
                settings = values[i].split()
                f = float(int(settings[0],16))/10**7
                p = int(settings[1],16)*360/16384.0
                a = int(settings[2],16)/1024.0
                self.rf_outputs[i].update_value(f,a,p)
        except:
            pass
            
        self.init_done = True
    
    def static_update(self,output):
        
        # convert numbers to correct representation
        output.amp = int(output.amp*1024)/1024.0
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
        
        if not self.init_done or not self.static_mode:
            return
        # program hardware
        try:            
            self.connection.write('F%d %f\r\n'%(channel,output.freq))
            self.connection.readline(),        
        except:
            print "channel"+str(channel)+" broken f"
            
        try:
            self.connection.write('V%d %u\r\n'%(channel,output.amp*1024))
            self.connection.readline(),        
        except:
            print "channel"+str(channel)+" broken a"
            
        try:
            self.connection.write('P%d %u\r\n'%(channel,output.phase*16384/360))
            self.connection.readline(),            
        except:
            print "channel"+str(channel)+" broken p"
        
        
        
    def get_child(self,type,channel):
        if type == "RF":
            if channel >= 0 and channel < self.num_RF:
                return self.rf_outputs[channel]
        
        return None
    
    def transition_to_buffered(self,h5file):        
        # disable static update
        self.static_mode = False
        
       
        initial_values = {"freq0":self.rf_outputs[0].freq, "amp0":self.rf_outputs[0].amp, "phase0":self.rf_outputs[0].phase,
                          "freq1":self.rf_outputs[1].freq, "amp1":self.rf_outputs[1].amp, "phase1":self.rf_outputs[1].phase,
                          "freq2":self.rf_outputs[2].freq, "amp2":self.rf_outputs[2].amp, "phase2":self.rf_outputs[2].phase,
                          "freq3":self.rf_outputs[3].freq, "amp3":self.rf_outputs[3].amp, "phase3":self.rf_outputs[3].phase}
        novatech_programming.program_from_h5_file(self.connection,self.settings['device_name'],h5file,initial_values)
        
        
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is sending out updates.
        self.static_mode = True       
        
       
        
                
        #turn buffered mode off, output values in buffer to ensure it outputs what it says in que
        self.connection.write('m o\r\n')
        self.connection.readline()
        self.connection.write('I a\r\n')
        self.connection.readline()
        self.connection.write('I p\r\n')
        self.connection.readline()
        #update the panel to reflect the current state of the novatech
        self.set_defaults()

    def on_value_change(self,widget):
        if not self.init_done:
            return
      
        update_channel = None
        for i in range(0,self.num_RF):
            for j in range(0,3):
                if widget == self.rf_widgets[i][j]:
                    update_channel = i
                    break
            if update_channel is not None:
                break
                
        self.rf_outputs[update_channel].update_value(self.rf_widgets[update_channel][0].get_value(),self.rf_widgets[update_channel][1].get_value(),self.rf_widgets[update_channel][2].get_value())
        
        
            