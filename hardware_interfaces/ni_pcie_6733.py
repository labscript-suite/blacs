from hardware_interfaces.output_types.DO import *
from hardware_interfaces.output_types.AO import *

import gobject
import pygtk
import gtk

import Queue
import multiprocessing
import threading
import logging
import numpy
import time
import pylab
import math
import h5py
import excepthook

from tab_base_classes import Tab, Worker, define_state

class ni_pcie_6733(Tab):

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
        self.settings = settings
        Tab.__init__(self,NiPCIe6363Worker,notebook,settings)
        
        self.init_done = False
        self.static_mode = False
        self.destroy_complete = False
        
        #capabilities
        # can I abstract this away? Do I need to?
        self.num_DO = 0
        self.num_AO = 8
        self.num_RF = 0
        self.num_AI = 0
        
        self.max_ao_voltage = 10.0
        self.min_ao_voltage = -10.0
               
        # input storage
        self.ai_callback_list = []
        for i in range(0,self.num_AI):
            self.ai_callback_list.append([])
        
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/NI_6733.glade')
        self.toplevel = self.builder.get_object('toplevel')
        
        self.digital_outs = []
        self.digital_widgets = []
        for i in range(0,self.num_DO):
            # store widget objects
            self.digital_widgets.append(self.builder.get_object("do_toggle_"+str(i+1)))
		
            #programatically change labels!
            temp = self.builder.get_object("do_hardware_label_"+str(i+1))
            temp2 = self.builder.get_object("do_real_label_"+str(i+1))
            if i < 32:
                temp.set_text("DO P0:"+str(i))
                channel = "port0/line"+str(i)
            elif i < 40:
                temp.set_text("DO P1:"+str(i-32)+" (PFI "+str(i-32)+")")
                channel = "port1/line"+str(i-32)
            else:
                temp.set_text("DO P2:"+str(i-40)+" (PFI "+str(i-32)+")")
                channel = "port2/line"+str(i-40)
            
            channel_name = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
            if channel_name is not None:
                name = channel_name.name
            else:
                name = "-"
            
            temp2.set_text(name)
            
            # Create DO object
            # channel is currently being set to i in the DO. It should probably be a NI channel 
            # identifier
            self.digital_outs.append(DO(self,self.static_update,self.program_static,i,temp.get_text(),name))
        
        self.analog_outs = []
        self.analog_widgets = []
        for i in range(0,self.num_AO):
            channel_name = self.settings["connection_table"].find_child(self.settings["device_name"],"ao"+str(i))
            if channel_name is not None:
                name = channel_name.name
            else:
                name = "-"
                
            # store widget objects
            self.analog_widgets.append(self.builder.get_object("AO_value_"+str(i+1)))
            
            self.builder.get_object("AO_label_a"+str(i+1)).set_text("AO"+str(i))            
            self.builder.get_object("AO_label_b"+str(i+1)).set_text(name)            
            
            self.analog_outs.append(AO(self,self.static_update,self.program_static,i,"AO"+str(i),name,[self.min_ao_voltage,self.max_ao_voltage]))
            
        # Need to connect signals!
        self.builder.connect_signals(self)        
        self.toplevel = self.builder.get_object('toplevel')
        self.toplevel.hide()
        self.viewport.add(self.toplevel)
        
        self.initialise_device()
        
    
    # ** This method should be common to all hardware interfaces **
    #
    # This method cleans up the class before the program exits. In this case, we close the worker thread!
    #
    @define_state
    def destroy(self):

        self.init_done = False
        
        self.write_queue.put(["shutdown"])
        self.result_queue.put([None,None,None,None,'shutdown'])
                
        self.queue_work('close_device')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
     
    @define_state
    def initialise_device(self):
        self.queue_work('initialise',self.settings["device_name"],[self.min_ao_voltage,self.max_ao_voltage])
        self.do_after('leave_initialise_device')
        
    def leave_initialise_device(self,_results):        
        self.static_mode = True
        self.init_done = True
        self.toplevel.show()
    
    def get_front_panel_state(self):
        dict = {}

        for i in range(self.num_DO):
            dict["DO"+str(i)] = self.digital_outs[i].state
            
        for i in range(self.num_AO):
            dict["AO"+str(i)] = self.analog_outs[i].value
            
        return dict
    
    #
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    #
    # Static update 
    # Should not program change during experimental run
    #
    @define_state
    def program_static(self,output):
        if not self.init_done or not self.static_mode:
            return
        
        # create dictionary
        ao_values = {}
        for i in range(self.num_AO):
            ao_values[str(i)] = self.analog_outs[i].value
            
        do_values = {}
        for i in range(self.num_DO):
            do_values[str(i)] = self.digital_outs[i].state
            
        self.queue_work('program_static',ao_values,do_values)
        
    
    @define_state
    def static_update(self,output):    
        if not self.init_done or not self.static_mode:
            return    
        # update the GUI too!
        # Select the output array to search from
        search_array = None
        if isinstance(output,DO):
            search_array = self.digital_outs
        elif isinstance(output,AO):
            search_array = self.analog_outs
            
        # search for the output that has been updated, so we can get the right widget to update
        channel = None
        for i in range(0,len(search_array)):
            if output == search_array[i]:
                channel = i
                break
                
        # Now update the widget!
        if isinstance(output,DO):
            if self.digital_widgets[channel].get_active() != output.state:
                self.digital_widgets[channel].set_active(output.state)
        elif isinstance(output,AO):
            if self.analog_widgets[channel].get_text() != str(output.value):
                self.analog_widgets[channel].set_text(str(output.value))
            

    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Program experimental sequence
    #
    # Needs to handle seemless transition from static to experiment sequence
    #
    def transition_to_buffered(self,h5file):
        self.transitioned_to_buffered = False
        # Queue transition in state machine
        self.program_buffered(h5file) 
    
    @define_state
    def program_buffered(self,h5file):
        # disable static update
        self.static_mode = False               
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered')
    
    def leave_program_buffered(self,_results):
        if _results != None:
            self.transitioned_to_buffered = True
        
    @define_state
    def abort_buffered(self):        
        self.queue_work('abort_buffered')
        self.static_mode = True
        
    @define_state        
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is queuing up updates.
        #reenable static updates
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static')
        
    def leave_transition_to_static(self,_results):    
        # This needs to be put somewhere else...When I fix up updating the GUI values
        self.static_mode = True
    
#    def setup_buffered_trigger(self):
#        self.buffered_do_start_task = Task()
#        self.buffered_do_start_task.CreateDOChan("ni_pcie_6363_0/port2/line0","",DAQmx_Val_ChanPerLine)
#        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([1],dtype=pylab.uint8),None,None)
#    
#    def start_buffered(self):
#        
#        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([0],dtype=pylab.uint8),None,None)
#        self.buffered_do_start_task.StartTask()
#        time.sleep(0.1)
#        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([1],dtype=pylab.uint8),None,None)
#        
#        self.buffered_do_start_task.StopTask()
#        self.buffered_do_start_task.ClearTask()
        
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This returns the channel in the "type" (DO/AO) list
    # We should possibly extend this to get channel based on NI channel identifier, not an array index!
    def get_child(self,type,channel):
        if type == "DO":
            if channel >= 0 and channel < self.num_DO:
                return self.digital_outs[channel]
        elif type == "AO":
            if channel >= 0 and channel < self.num_AO:
                return self.analog_outs[channel]
		
        # We don't have any of this type, or the channel number was invalid
        return None
    
    ##########################
    # PyGTK Signal functions #
    ##########################
    @define_state
    def on_analog_change(self,widget):
        for i in range(0,self.num_AO):
            if self.analog_widgets[i] == widget:
                self.analog_outs[i].update_value(widget.get_text())

    
class NiPCIe6733Worker(Worker):
    def init(self):
        
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        
        global ni_programming; from hardware_programming import ni_pcie_6733 as ni_programming
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
        for i in range(0,self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.device_name+"/ao"+str(i),"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        
    def program_static(self,analog_outs,digital_outs):
        # Program a static change
        # write AO
        for i in range(0,self.num_AO):# The 4 is from self.num_AO
            self.ao_data[i] = analog_outs[str(i)]
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
          
    def program_buffered(self,h5file):        
        self.ao_task = ni_programming.program_buffered_output(h5file,self.device_name,self.ao_task,self.do_task)
        return True
    
    def abort_buffered(self):
        # This is almost Identical to transition_to_static, but doesn't call StopTask since this thorws an error if the task hasn't actually finished!
        self.ao_task.ClearTask()
        self.ao_task = Task()
        self.setup_static_channels()
        #update values on GUI
        self.ao_task.StartTask()
    
    def transition_to_static(self):
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.ao_task = Task()
        self.setup_static_channels()
        #update values on GUI
        self.ao_task.StartTask()
        
