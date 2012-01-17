import gobject
import pygtk
import gtk

import numpy
import h5py
import excepthook

from tab_base_classes import Tab, Worker, define_state
from output_classes import AO, DO, RF, DDS

class ni_pci_6733(Tab):
    # Capabilities
    self.num_DO = 0
    self.num_AO = 8
    self.num_RF = 0
    self.num_AI = 0
    
    self.max_ao_voltage = 10.0
    self.min_ao_voltage = -10.0
    self.ao_voltage_step = 0.1
    
    def __init__(self,notebook,settings,restart=False):
        Tab.__init__(self,NiPCI6733Worker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.static_mode = True
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/NI_6733.glade')
        self.builder.connect_signals(self)   
        
        self.toplevel = self.builder.get_object('toplevel')
        
#        self.digital_outputs = []
#        for i in range(self.num_DO):
#            # get the widget:
#            toggle_button = self.builder.get_object("do_toggle_%d"%(i+1))
#		
#            #programatically change labels!
#            channel_label= self.builder.get_object("do_hardware_label_%d"%(i+1))
#            name_label = self.builder.get_object("do_real_label_%d"%(i+1))
#            
#            if i < 32:
#                channel_label.set_text("DO P0:"+str(i))
#                NIchannel = "port0/line"+str(i)
#            elif i < 40:
#                channel_label.set_text("DO P1:"+str(i-32)+" (PFI "+str(i-32)+")")
#                NIchannel = "port1/line"+str(i-32)
#            else:
#                channel_label.set_text("DO P2:"+str(i-40)+" (PFI "+str(i-32)+")")
#                NIchannel = "port2/line"+str(i-40)
#            
#            device = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
#            name = device.name if device else '-'
#            
#            name_label.set_text(name)
#            
#            output = DO(name, NIchannel, toggle_button, self.program_static)
#            self.digital_outs.append(output)
            
        self.analog_outputs = []
        for i in range(self.num_AO):
            # Get the widget:
            spinbutton = self.builder.get_object("AO_value_%d"%(i+1))
            channel = "ao"+str(i)
            device = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
            name = device.name if device else '-'
                
            # store widget objects
            self.builder.get_object("AO_label_a"+str(i+1)).set_text("AO"+str(i))            
            self.builder.get_object("AO_label_b"+str(i+1)).set_text(name)            
            
            # Setup unit calibration:
            calib = None
            calib_params = {}
            def_calib_params = "V"
            if device:
                # get the AO from the connection table, find its calibration details
                calib = device.calibration_class
                calib_params = eval(device.calibration_parameters)
            
            output = AO(name, channel,spinbutton, combobox, calib, calib_params, def_calub_params, self.program_static, self.min_ao_voltage, self.max_ao_voltage, self.ao_voltage_step)
            self.analog_outputs.append(output)
            
        self.viewport.add(self.toplevel)
        self.initialise_device()
    
    @define_state
    def destroy(self):
        self.init_done = False
        self.queue_work('close_device')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
     
    @define_state
    def initialise_device(self):
        self.queue_work('initialise',self.settings["device_name"],[self.min_ao_voltage,self.max_ao_voltage])
        
    def get_front_panel_state(self):
        state = {}
        for i in range(self.num_AO):
            state["AO"+str(i)] = self.analog_outputs[i].value
        return state
    
    @define_state
    def program_static(self,output):
        if self.static_mode:
            self.queue_work('program_static',[ouput.value for output in self.analog_outputs])

    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False      
        # The initial values, to program back in in case of an abort:
        self.initial_values = [ouput.value for output in self.analog_outputs]         
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        # Tell the queue manager that we're done:
        notify_queue.put(self.device_name)
        
    @define_state
    def abort_buffered(self):        
        self.queue_work('abort_buffered')
        self.do_after('leave_transition_to_static',notify_queue=None)
        
    @define_state        
    def transition_to_static(self,notify_queue):
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static',notify_queue)
        
    def leave_transition_to_static(self,notify_queue,_results):    
        self.static_mode = True
        # Tell the queue manager that we're done:
        if notify_queue is not None:
            notify_queue.put(self.device_name)
    
    def get_child(self,type,channel):
        if type == "DO":
            if channel >= 0 and channel < self.num_DO:
                return self.digital_outs[channel]
        elif type == "AO":
            if channel >= 0 and channel < self.num_AO:
                return self.analog_outs[channel]
		
        # We don't have any of this type, or the channel number was invalid
        return None
    
    
class NiPCI6733Worker(Worker):
    def init(self):
        
        exec 'from PyDAQmx import Task, DAQmxConnectTerms, DAQmxDisconnectTerms' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        
        global ni_programming; from hardware_programming import ni_pci_6733 as ni_programming
        self.num_DO = 0
        self.num_AO = 8
        self.num_RF = 0
        self.num_AI = 0     
    
    def initialise(self, device_name, limits):
        # Create task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        self.device_name = device_name
        self.limits = limits
        self.setup_static_channels()            
        
        #DAQmx Start Code        
        self.ao_task.StartTask()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.device_name+"/ao%d"%i,"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        
    def program_static(self,analog_data):
        self.ao_data[:] = analog_data
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
          
    def program_buffered(self,h5file):        
        self.ao_task = ni_programming.program_buffered_output(h5file,self.device_name,self.ao_task)
        # require final values here to be returned
        
    def transition_to_static(self,abort=False):
        if not abort:
            # if aborting, don't call StopTask since this thorws an
            # error if the task hasn't actually finished!
            self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.ao_task = Task()
        self.setup_static_channels()
        self.ao_task.StartTask()
        
