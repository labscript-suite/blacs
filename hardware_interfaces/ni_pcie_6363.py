from hardware_interfaces.output_types.DO import *
from hardware_interfaces.output_types.AO import *

import gobject
import pygtk
import gtk

import Queue
import multiprocessing
import numpy
import time
import pylab
import math
import h5py

from PyDAQmx import Task
from PyDAQmx.DAQmxConstants import *
from PyDAQmx.DAQmxTypes import *

from hardware_programming import ni_pcie_6363 as ni_programming

class ni_pcie_6363(object):

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
    def __init__(self,settings):
        self.init_done = False
        #capabilities
        # can I abstract this away? Do I need to?
        self.num_DO = 48
        self.num_AO = 4
        self.num_RF = 0
        self.num_AI = 32
        
        self.settings = settings
        
        # input storage
        self.ai_callback_list = []
        for i in range(0,self.num_AI):
            self.ai_callback_list.append([])
        
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/NI_6363.glade')
        self.tab = self.builder.get_object('toplevel')
        
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
            elif i < 40:
                temp.set_text("DO P1:"+str(i-32)+" (PFI "+str(i-32)+")")
            else:
                temp.set_text("DO P2:"+str(i-40)+" (PFI "+str(i-32)+")")
            
            temp2.set_text("blah")
            
            # Create DO object
            # channel is currently being set to i in the DO. It should probably be a NI channel 
            # identifier
            self.digital_outs.append(DO(self,self.static_update,i,temp.get_text(),temp2.get_text()))
        
        self.analog_outs = []
        self.analog_widgets = []
        for i in range(0,self.num_AO):
            # store widget objects
            self.analog_widgets.append(self.builder.get_object("AO_value_"+str(i+1)))
            
            self.builder.get_object("AO_label_a"+str(i+1)).set_text("AO"+str(i))
            
            self.analog_outs.append(AO(self,self.static_update,i,"AO"+str(i),"blah",[-10.,10.]))
            
        # Need to connect signals!
        self.builder.connect_signals(self)
        
        # Set up AI/DI input manager. This subprocess will communicate with the main gtk thread via a queue or pipe (see subprocessing module)
        # Through the ni_pcie_6363 device, virtual devices will request data from a channel (or list of channels).
        # The request will return a queue object. The virtual device will call idle_add(callback_function) which results 
        #   in callback_function being called when nothing else is happening.
        # The callback function will access the afore mentioned queue, read whatever data is on it, and handle it appropriately.
        #
        # The subprocess will handle multiple requests for the same channel easily. It will block transfer 
        # to the queue (for speed reasons) during an experimental run. Data will be transfered to virtual devices at the end of the run.
        
        # need to handle DI/DO in some sort of clever way...
        
        # Start AI worker thread
        self.write_queue = multiprocessing.Queue()
        self.read_queue = multiprocessing.Queue()
        self.result_queue = multiprocessing.Queue()
        self.ai_worker = Worker(self.write_queue, self.read_queue, self.result_queue)
        self.ai_worker.start()
        
        
        # Add timeout callback which distributes newly acquired data to registered methods
        self.timeout = gtk.timeout_add(10,self.idle_function)
        
        
        # Create task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        self.do_task = Task()
        self.do_read = int32()
        self.do_data = numpy.zeros(48,dtype=numpy.uint8)
        self.buffered_do_start_task = None
        
        self.setup_static_channels()
            
        
        #DAQmx Start Code        
        self.ao_task.StartTask()  
        self.do_task.StartTask()  
        
        self.static_mode = True
        self.init_done = True
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method cleans up the class before the program exits. In this case, we close the worker thread!
    #
    def destroy(self):
        self.init_done = False
        
        gtk.timeout_remove(self.timeout)
        time.sleep(0.1)
        self.write_queue.put(["shutdown"])
        time.sleep(0.3)
        
        # clear all items in the queues
        while not self.read_queue.empty():
            self.read_queue.get_nowait()
        while not self.result_queue.empty():
            self.result_queue.get_nowait()
        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
    
    def setup_static_channels(self):
        #setup AO channels
        for i in range(0,self.num_AO):
            self.ao_task.CreateAOVoltageChan("ni_pcie_6363_0/ao"+str(i),"",-10,10,DAQmx_Val_Volts,None)
        
        #setup DO ports
        self.do_task.CreateDOChan("ni_pcie_6363_0/port0/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan("ni_pcie_6363_0/port0/line8:15","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan("ni_pcie_6363_0/port0/line16:23","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan("ni_pcie_6363_0/port0/line24:31","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan("ni_pcie_6363_0/port1/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan("ni_pcie_6363_0/port2/line0:7","",DAQmx_Val_ChanForAllLines)
        
    #
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, called every x milliseconds **
    # 
    #
    # "idle_function()"
    #
    # This function is called during idle time, and sends out the analog input data to the specified callback functions, during idle time.
    # It should only be used internally by this class!
    #
    def idle_function(self):
        # read subprocess queue. Send data to relevant callback functions
        while True:
            try:
                a = self.result_queue.get_nowait()
                time = a[0]
                rate = a[1]
                samples = a[2]
                channels = a[3]
                data = a[4]
                
                div = 1/rate
                times = numpy.arange(time,time+samples*div,div)
                # will need to split up the array here. Will do this later
                
                xy = numpy.vstack((data,times))
                
                self.ai_callback_list[0][0][0](0,xy,rate)
                
            except Queue.Empty:
                #print 'Queue is Empty'
                break
                
        # This is VERY important. If the function doesn't return true, it won't be called again during idle time
        return True
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    #
    # "request_analog_input(channel,rate,callback)"
    #
    # This function takes 3 arguments
    # 1. "channel": The AI channel you want to aquire data from
    # 2. "rate": The MINIMUM rate you want to aquire data at. Note, you may get data at a faster rate!
    # 3. "callback": The function you would like your data to be passed to once it is aquired. This function should
    #   be of the form callback(channel,data,rate), where data is a 2D numpy array
    #
    # This function returns True, if the task was successfully started, or False if it was not.
    #
    def request_analog_input(self,channel,rate,callback):
        if channel >= 0 and channel < self.num_AI:
            self.ai_callback_list[channel].append([callback,rate])
        
            # communicate with subprocess. Request data from channel be included in the queue. Up aquisition rate if necessary
            
            self.write_queue.put(["add channel","ni_pcie_6363_0/ai"+str(channel),"10000"])
            
            return True
        else:
            return False
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This is the digital analogue of the "analog" function above!
    # It will be filled out when we work out how to handle switching channels between DO and DI!
    # Also need to add a stop DI method
    def request_digital_input(self,channel,rate,callback):
        pass
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    #
    # "stop_analog_input(channel,callback)"
    #
    # This function takes two arguments.
    # 1. "Channel": the AI channel to stop
    # 2. "callback": the callback function you wish to remove for the specified "channel"
    #
    # This function returns True on success, or False on failure
    #
    def stop_analog_input(self,channel,callback):
        # Is the channel valid?
        if channel < 0 or channel >= self.num_AI:
            return False
        
        # find the callback entry
        item = None
        for i in self.ai_callback_list[channel]:
            if i[0] == callback:
                item = i
                break
        
        # if only callback for that channel, communicate with subprocess, stop acquisition
        if len(self.ai_callback_list[channel]) == 1:
            # wait for confirmation from subprocess
        
            # call idle function to send out last data
            self.idle_function()
        
        # get this information before removing from list        
        max_rate,exists_twice = self.max_ai_rate()   
        
        # remove from callback list.
        self.ai_callback_list[channel].remove(item)
             
        if not exists_twice and max_rate == item[1]:
            # the callback we are deleting has the fastest request rate, and is the only channel with this high rate
            # we need to lower the request rate now
               
            # find now highest rate 
            new_rate,e = self.max_ai_rate()
       
    
    #
    # "max_ai_rate()": This function returns two parameters
    #
    # 1. "rate": this is the fastest aquisition rate of any AI channel
    # 2. "exists_twice": If the value in 1. is requested by more than one callback function, this will be True
    #
    def max_ai_rate(self):
        rate = 0
        exists_twice = False
        for i in range(0,self.num_AI):
            for j in range(0,len(self.ai_callback_list[i])):
                if rate < ai_callback_list[i][j][1]:
                    rate = ai_callback_list[i][j][1]
                    exists_twice = False
                elif rate == ai_callback_list[i][j][1]:
                    exists_twice = True
        return rate,exists_twice
           
    #
    # ** This method should be in all hardware_interfaces, but it does not need to be named the same **
    # ** This method is an internal method, registered as a callback with each AO/DO/RF channel **
    #
    # Static update 
    # Should not program change during experimental run
    #
    def static_update(self,output):
        if not self.init_done or not self.static_mode:
            return
        # Program a static change
        # write AO
        for i in range(0,self.num_AO):
            self.ao_data[i] = self.analog_outs[i].value
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
          
        # write DO        
        for i in range(0,self.num_DO):
            if self.digital_outs[i].state == True:
                self.do_data[i] = 1
            else:
                self.do_data[i] = 0
        
        self.do_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,self.do_data,byref(self.do_read),None)
        
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
        # disable static update
        self.static_mode = False
        
        # Program hardware
        #self.ao_task.StopTask()
        #self.do_task.StopTask()
        
        self.write_queue.put(["transition to buffered",h5file,self.settings["device_name"]])
        
        
        
        self.ao_task, self.do_task = ni_programming.program_buffered_output(h5file,self.settings["device_name"],self.ao_task,self.do_task)
        
        print type(self.ao_task)
        
        # Return Ready status   
        print 'returned from programming'
        
            
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is queuing up updates.
        self.write_queue.put(["transition to static",self.settings["device_name"]])
        #reenable static updates
        self.static_mode = True
        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        
        self.ao_task = Task()
        self.do_task = Task()
        
        self.setup_static_channels()
        
        #update values on GUI
        #setup AO channels
        #for i in range(0,self.num_AO):
        #    self.ao_task.CreateAOVoltageChan("ni_pcie_6363_0/ao"+str(i),"",-10,10,DAQmx_Val_Volts,None)
        
        self.ao_task.StartTask()
        self.do_task.StartTask()
        pass
    
    def setup_buffered_trigger(self):
        self.buffered_do_start_task = Task()
        self.buffered_do_start_task.CreateDOChan("ni_pcie_6363_0/port2/line0","",DAQmx_Val_ChanPerLine)
        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([1],dtype=pylab.uint8),None,None)
    
    def start_buffered(self):
        
        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([0],dtype=pylab.uint8),None,None)
        self.buffered_do_start_task.StartTask()
        time.sleep(0.1)
        self.buffered_do_start_task.WriteDigitalLines(1,True,10.0,DAQmx_Val_GroupByScanNumber,pylab.array([1],dtype=pylab.uint8),None,None)
        
        self.buffered_do_start_task.StopTask()
        self.buffered_do_start_task.ClearTask()
        
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
    
    def on_digital_toggled(self,widget):
        # find widget. Send callback
        for i in range(0,self.num_DO):
            if self.digital_widgets[i] == widget:
                self.digital_outs[i].update_value(widget.get_active())
                return
    
    def on_analog_change(self,widget):
        for i in range(0,self.num_AO):
            if self.analog_widgets[i] == widget:
                self.analog_outs[i].update_value(widget.get_text())
                
#########################################
#                                       #
#       Worker class for AI input       #
#                                       #
#########################################
class Worker(multiprocessing.Process):

    def __init__(self,read_queue,write_queue,result_queue):
        # base class initialization
        multiprocessing.Process.__init__(self)
 
        # Job management stuff
        self.read_queue = read_queue
        self.write_queue = write_queue
        self.result_queue = result_queue
        self.kill_received = False
        self.task_running = False
        
        # Channel details
        self.channels = []
        self.rate = 1.
        self.samples_per_channel = 1000
        self.h5_file = ""
        self.buffered_channels = []
        self.buffered_rate = 0
        self.buffered = False
        self.buffered_data = None
      
    def run(self):
        while not self.kill_received:
 
            # Is there any communication from the main process?
            try:
                cmd = self.read_queue.get_nowait()
                
                # Process the command
                if cmd[0] == "add channel":
                    # we should check to make sure the channel isn't already added!
                    
                    self.channels.append([cmd[1]])
                    
                    # update the rate
                    if self.rate < float(cmd[2]):
                        self.rate = float(cmd[2])
                    
                    if self.task_running:
                        self.stop_task()
                    self.setup_task()
                elif cmd[0] == "remove channel":
                    pass
                elif cmd[0] == "shutdown":
                    if self.task_running:
                        self.stop_task()
                    self.kill_received = True                    
                    break
                elif cmd[0] == "transition to buffered":
                    self.transition_to_buffered(cmd[1],cmd[2])
                elif cmd[0] == "transition to static":
                    self.transition_to_static(cmd[1])
                elif cmd == "":
                    pass                    
                
            except Queue.Empty:
                pass
 
            #DAQmx Read Code
            if self.task_running and not self.kill_received:
                if self.buffered:
                    chnl_list = self.buffered_channels
                else:
                    chnl_list = self.channels
                try:                    
                    error = self.task.ReadAnalogF64(self.samples_per_channel,10.0,DAQmx_Val_GroupByChannel,self.ai_data,self.samples_per_channel*len(chnl_list),byref(self.ai_read),None)
                except:
                    print 'acquisition error'
                    
                
                            
                # send the data to the queue
                if self.buffered:
                    # rearrange ai_data into correct form
                    data = numpy.copy(self.ai_data)
                    data.shape = (len(chnl_list),self.ai_read.value)              
                    data = data.transpose()
                    self.buffered_data = numpy.append(self.buffered_data,data,axis=0)
                else:
                    self.result_queue.put([self.t0,self.rate,self.ai_read.value,len(self.channels),self.ai_data])
                    self.t0 = self.t0 + self.samples_per_channel/self.rate
        
        
        
    def setup_task(self):
        #DAQmx Configure Code
        if self.buffered:
            chnl_list = self.buffered_channels
            rate = self.buffered_rate
        else:
            chnl_list = self.channels
            rate = self.rate
            
        if rate < 1000:
            self.samples_per_channel = rate
        else:
            self.samples_per_channel = 1000
        
        self.task = Task()
        self.ai_read = int32()
        self.ai_data = numpy.zeros((self.samples_per_channel*len(chnl_list),), dtype=numpy.float64)   
        
        for chnl in chnl_list:
            self.task.CreateAIVoltageChan(chnl[0],"",DAQmx_Val_RSE,-10.0,10.0,DAQmx_Val_Volts,None)
            
        self.task.CfgSampClkTiming("",rate,DAQmx_Val_Rising,DAQmx_Val_ContSamps,1000)
                
        if self.buffered:
            #set up start on digital trigger
            pass
        
        #DAQmx Start Code
        self.task.StartTask()
        # TODO: Need to do something about the time for buffered acquisition. Should be related to when it starts (approx)
        # How do we detect that?
        self.t0 = time.time() - time.timezone
        self.task_running = True
    
    def stop_task(self):
        self.task_running = False
        self.task.StopTask()
        self.task.ClearTask()
        
    def transition_to_buffered(self,h5file,device_name):
        # stop current task
        self.stop_task()
        
        self.buffered_channels = []
        
        # Save h5file path (for storing data later!)
        self.h5_file = h5file
        # read channels, acquisition rate, etc from H5 file
        h5_chnls = ""
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                h5_chnls = hdf5_file['/devices/'+device_name].attrs['analog_in_channels']
                self.buffered_rate = float(hdf5_file['/devices/'+device_name].attrs['acquisition_rate'])
            except:
                print "couldn't get the channel list from h5 file. Skipping..."
        
        
        # combine static channels with h5 channels
        h5_chnls = h5_chnls.split(', ')
        for i in range(len(h5_chnls)):
            if not h5_chnls[i] == '':
                self.buffered_channels.append([h5_chnls[i]])
        
        for i in range(len(self.channels)):
            if not self.channels[i] in self.buffered_channels:
                self.buffered_channels.append(self.channels[i])
        
        # setup task (rate should be from h5 file)
        # Possibly should detect and lower rate if too high, as h5 file doesn't know about other acquisition channels?
        
        if self.buffered_rate <= 0:
            self.buffered_rate = self.rate
        
        self.buffered = True
        self.buffered_data = numpy.zeros((1,len(self.buffered_channels)),dtype=numpy.float64)
        self.setup_task()     
    
    def transition_to_static(self,device_name):
        # Stop acquisition (this should really be done on a digital edge, but that is for later! Maybe use a Counter)
        self.stop_task()        
        'transitioning to static, task stopped'
        # save the data acquired to the h5 file
        with h5py.File(self.h5_file,'a') as hdf5_file:
            try:
                data_group = hdf5_file['/'].create_group('data')
                ni_group = data_group.create_group(device_name)
                ds =  ni_group.create_dataset('analog_data', data=self.buffered_data[-(self.buffered_data.shape[0]-1):,:])
                
            except Exception as e:
                print str(e)
                print 'failed at writing data'
        
        
        # Send data to callback functions as requested (in one big chunk!)
        #self.result_queue.put([self.t0,self.rate,self.ai_read,len(self.channels),self.ai_data])
        
        # return to previous acquisition mode
        self.buffered = False
        self.setup_task()
        