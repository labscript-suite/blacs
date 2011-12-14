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

class ni_pcie_6363(Tab):

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
        # Queues that need to be passed to the worker process, which in turn passes them to the acquisition process: AI worker thread
        self.write_queue = multiprocessing.Queue()
        self.read_queue = multiprocessing.Queue()
        self.result_queue = multiprocessing.Queue()
        
        acq_args = [self.settings['device_name'], self.write_queue, self.read_queue, self.result_queue]
        
        Tab.__init__(self,NiPCIe6363Worker,notebook,settings,workerargs={'acq_args':acq_args})
        
        self.init_done = False
        self.static_mode = False
        self.destroy_complete = False
        
        #capabilities
        # can I abstract this away? Do I need to?
        self.num_DO = 48
        self.num_AO = 4
        self.num_RF = 0
        self.num_AI = 32
        
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
        self.builder.add_from_file('hardware_interfaces/NI_6363.glade')
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
        
        # Start acquisition thread which distributes newly acquired data to registered methods
        self.get_data_thread = threading.Thread(target = self.get_acquisition_data)
        self.get_data_thread.daemon = True
        self.get_data_thread.start()
        
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
    
    def get_acquisition_data(self):
        # This function is called in a separate thread. It collects acquisition data 
        # from the acquisition subprocess, and calls the callbacks that have requested data."""
        logger = logging.getLogger('BLACS.%s.get_data_thread'%self.settings['device_name'])   
        logger.info('Starting')
        # read subprocess queue. Send data to relevant callback functions
        while True:
            logger.debug('Waiting for data')
            time, rate, samples, channels, data = self.result_queue.get()
            if data == 'shutdown':
                logger.info('Quitting')
                break
            logger.debug('Got some data')
            div = 1/rate
            times = numpy.arange(time,time+samples*div,div)
            #TODO will need to split up the array here. (single channel is assumed -- will need to extend for multiple channels)
            xy = numpy.vstack((data,times))
            with gtk.gdk.lock:
                logger.debug('Calling callbacks')
                #TODO Will need to loop over the array to call every callback:
                self.ai_callback_list[0][0][0](0,xy,rate)

                
    def get_front_panel_state(self):
        dict = {}

        for i in range(self.num_DO):
            dict["DO"+str(i)] = self.digital_outs[i].state
            
        for i in range(self.num_AO):
            dict["AO"+str(i)] = self.analog_outs[i].value
            
        return dict
    
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
            
            self.write_queue.put(["add channel","ni_pcie_6363_0/ai"+str(channel),str(rate)])
            
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
        self.write_queue.put(["transition to buffered",h5file,self.settings["device_name"]])
        
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered')
        
    
    def leave_program_buffered(self,_results):
        if _results != None:
            self.transitioned_to_buffered = True
        
    @define_state
    def abort_buffered(self):        
        self.write_queue.put(["transition to static",self.settings["device_name"]])
        self.queue_work('abort_buffered')
        self.static_mode = True
        
    @define_state        
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is queuing up updates.
        self.write_queue.put(["transition to static",self.settings["device_name"]])
        #reenable static updates
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static')
        
    def leave_transition_to_static(self,_results):    
        # This needs to be put somewhere else...When I fix up updating the GUI values
        self.static_mode = True
    
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
    @define_state
    def on_digital_toggled(self,widget):
        # find widget. Send callback
        for i in range(0,self.num_DO):
            if self.digital_widgets[i] == widget:
                self.digital_outs[i].update_value(widget.get_active())
                return
    @define_state
    def on_analog_change(self,widget):
        for i in range(0,self.num_AO):
            if self.analog_widgets[i] == widget:
                self.analog_outs[i].update_value(widget.get_text())

    
class NiPCIe6363Worker(Worker):
    def init(self):
        self.acquisition_worker = Worker2(args=self.acq_args)
        self.acquisition_worker.daemon = True
        self.acquisition_worker.start()
        
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        
        global ni_programming; from hardware_programming import ni_pcie_6363 as ni_programming
        self.num_DO = 48
        self.num_AO = 4
        self.num_RF = 0
        self.num_AI = 32        
    
    def initialise(self, device_name, limits):
        # Create task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        self.do_task = Task()
        self.do_read = int32()
        self.do_data = numpy.zeros(48,dtype=numpy.uint8)
        self.device_name = device_name
        self.buffered_do_start_task = None
        self.limits = limits
        self.setup_static_channels()            
        
        #DAQmx Start Code        
        self.ao_task.StartTask()  
        self.do_task.StartTask()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(0,self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.device_name+"/ao"+str(i),"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
        #setup DO ports
        self.do_task.CreateDOChan(self.device_name+"/port0/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line8:15","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line16:23","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line24:31","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port1/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port2/line0:7","",DAQmx_Val_ChanForAllLines)    
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        
    def program_static(self,analog_outs,digital_outs):
        # Program a static change
        # write AO
        for i in range(0,self.num_AO):# The 4 is from self.num_AO
            self.ao_data[i] = analog_outs[str(i)]
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
          
        # write DO        
        for i in range(0,self.num_DO): #The 48 is from self.num_DO
            if digital_outs[str(i)] == True:
                self.do_data[i] = 1
            else:
                self.do_data[i] = 0
        
        self.do_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,self.do_data,byref(self.do_read),None)
    
    def program_buffered(self,h5file):        
        self.ao_task, self.do_task = ni_programming.program_buffered_output(h5file,self.device_name,self.ao_task,self.do_task)
        
        return True
    
    def abort_buffered(self):
        # This is almost Identical to transition_to_static, but doesn't call StopTask since this thorws an error if the task hasn't actually finished!
        self.ao_task.ClearTask()
        self.do_task.ClearTask()
        
        self.ao_task = Task()
        self.do_task = Task()
        
        self.setup_static_channels()
        
        #update values on GUI
        self.ao_task.StartTask()
        self.do_task.StartTask()
    
    def transition_to_static(self):
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        
        self.ao_task = Task()
        self.do_task = Task()
        
        self.setup_static_channels()
        
        #update values on GUI
        self.ao_task.StartTask()
        self.do_task.StartTask()
    
#########################################
#                                       #
#       Worker class for AI input       #
#                                       #
#########################################
class Worker2(multiprocessing.Process):
    def run(self):
        self.name, self.read_queue, self.write_queue, self.result_queue = self._args
        self.logger = logging.getLogger('BLACS.%s.acquisition'%self.name)
        self.task_running = False
        self.daqlock = threading.Condition()
        # Channel details
        self.channels = []
        self.rate = 1.
        self.samples_per_channel = 1000
        self.h5_file = ""
        self.buffered_channels = []
        self.buffered_rate = 0
        self.buffered = False
        self.buffered_data = None
        self.buffered_data_list = []
        
        self.task = None
        
        self.daqmx_read_thread = threading.Thread(target=self.daqmx_read)
        self.daqmx_read_thread.daemon = True
        self.daqmx_read_thread.start()
        self.mainloop()
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.acquisition.mainloop'%self.name)  
        logger.info('Starting')
        while True:
            logger.debug('Waiting for instructions')
            cmd = self.read_queue.get()
            logger.debug('Got a command: %s' % cmd[0])
            # Process the command
            if cmd[0] == "add channel":
                logger.debug('Adding a channel')
                #TODO we should check to make sure the channel isn't already added!
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
                logger.info('Shutdown requested, stopping task')
                if self.task_running:
                    self.stop_task()                  
                break
            elif cmd[0] == "transition to buffered":
                self.transition_to_buffered(cmd[1],cmd[2])
            elif cmd[0] == "transition to static":
                self.transition_to_static(cmd[1])
            elif cmd == "":
                pass         
    
    def daqmx_read(self):
        logger = logging.getLogger('BLACS.%s.acquisition.daqmxread'%self.name)
        logger.info('Starting')
        while True:
            with self.daqlock:
                logger.debug('Got daqlock')
                while not self.task_running:
                    logger.debug('Task isn\'t running. Releasing daqlock and waiting to reacquire it.')
                    self.daqlock.wait()
                # Let the notifying function have the lock back until it releases it and returns to the mainloop:
                self.daqlock.notify()
                logger.debug('Reading data from analogue inputs')
                if self.buffered:
                    chnl_list = self.buffered_channels
                else:
                    chnl_list = self.channels
                try:
                    error = "Task did not return an error, but it should have"
                    error = self.task.ReadAnalogF64(self.samples_per_channel,-1,DAQmx_Val_GroupByChannel,self.ai_data,self.samples_per_channel*len(chnl_list),byref(self.ai_read),None)
                    logger.debug('Reading complete')
                    if error < 0:
                        raise Exception(error)
                    if error > 0:
                        logger.warning(error)
                except Exception as e:
                    logger.error('acquisition error: %s' %str(e))
                    raise e
                        
            # send the data to the queue
            if self.buffered:
                # rearrange ai_data into correct form
                data = numpy.copy(self.ai_data)
                self.buffered_data_list.append(data)
                
                #if len(chnl_list) > 1:
                #    data.shape = (len(chnl_list),self.ai_read.value)              
                #    data = data.transpose()
                #self.buffered_data = numpy.append(self.buffered_data,data,axis=0)
            else:
                self.result_queue.put([self.t0,self.rate,self.ai_read.value,len(self.channels),self.ai_data])
                self.t0 = self.t0 + self.samples_per_channel/self.rate
        
    def setup_task(self):
        self.logger.debug('setup_task')
        #DAQmx Configure Code
        with self.daqlock:
            if self.buffered:
                chnl_list = self.buffered_channels
                rate = self.buffered_rate
            else:
                chnl_list = self.channels
                rate = self.rate
                
            if len(chnl_list) < 1:
                return
                
            if rate < 1000:
                self.samples_per_channel = int(rate)
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
                self.task.CfgDigEdgeStartTrig(self.clock_terminal,DAQmx_Val_Rising)
            
            #DAQmx Start Code
            self.task.StartTask()
            # TODO: Need to do something about the time for buffered acquisition. Should be related to when it starts (approx)
            # How do we detect that?
            self.t0 = time.time() - time.timezone
            self.task_running = True
            self.daqlock.notify()
    
    def stop_task(self):
        self.logger.debug('stop_task')
        with self.daqlock:
            if self.task_running:
                self.task_running = False
                self.task.StopTask()
                self.task.ClearTask()
            self.daqlock.notify()
        
    def transition_to_buffered(self,h5file,device_name):
        self.logger.debug('transition_to_buffered')
        # stop current task
        self.stop_task()
        
        self.buffered_channels = []
        self.buffered_data_list = []
        
        # Save h5file path (for storing data later!)
        self.h5_file = h5file
        # read channels, acquisition rate, etc from H5 file
        h5_chnls = ""
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                group =  hdf5_file['/devices/'+device_name]
                self.clock_terminal = group.attrs['clock_terminal']
                h5_chnls = group.attrs['analog_in_channels']
                self.buffered_rate = float(group.attrs['acquisition_rate'])
            except:
                self.logger.error("couldn't get the channel list from h5 file. Skipping...")
        
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
        if len(self.buffered_channels) == 1:
            self.buffered_data = numpy.zeros((1,),dtype=numpy.float64)
        else:
            self.buffered_data = numpy.zeros((1,len(self.buffered_channels)),dtype=numpy.float64)
        
        self.setup_task()     
    
    def transition_to_static(self,device_name):
        self.logger.debug('transition_to_static')
        # Stop acquisition (this should really be done on a digital edge, but that is for later! Maybe use a Counter)
        self.stop_task()        
        self.logger.info('transitioning to static, task stopped')
        # save the data acquired to the h5 file
        with h5py.File(self.h5_file,'a') as hdf5_file:
            data_group = hdf5_file['/data']
            ni_group = data_group.create_group(device_name)
            dtypes = [(chan.split('/')[-1],numpy.float32) for chan in sorted(self.buffered_channels)]
            start_time = time.time()
            self.buffered_data = numpy.zeros(len(self.buffered_data_list)*1000,dtype=dtypes)
            for i, data in enumerate(self.buffered_data_list):
                data.shape = (len(self.buffered_channels),self.ai_read.value)              
                data = data.transpose()
                for j, (chan, dtype) in enumerate(dtypes):
                    self.buffered_data[chan][i*1000:(i*1000)+1000] = data[j,:]
                if i % 100 == 0:
                    self.logger.debug( str(i/100) + " time: "+str(time.time()-start_time) )
            ni_group.create_dataset('analog_data', data=self.buffered_data)
            self.logger.info('data written, time taken: %ss' % str(time.time()-start_time))
        
        self.buffered_data = None
        self.buffered_data_list = []
        
        # Send data to callback functions as requested (in one big chunk!)
        #self.result_queue.put([self.t0,self.rate,self.ai_read,len(self.channels),self.ai_data])
        
        # return to previous acquisition mode
        self.buffered = False
        self.setup_task()
        self.extract_measurements(device_name)
        
    def extract_measurements(self, device_name):
        self.logger.debug('extract_measurements')
        with h5py.File(self.h5_file,'a') as hdf5_file:
            try:
                acquisitions = hdf5_file['/devices/'+device_name+'ACQUISITIONS']
            except:
                # No acquisitions!
                return
            measurements = hdf5_file['/data/'+device_name].create_group('measurements')
            raw_data = hdf5_file['/data/'+device_name+'analog_data']
            for connection,label,start_time,end_time,scale_factor,units in acquisitions:
                start_index = numpy.floor(self.buffered_rate*start_time)
                end_index = numpy.ceil(self.buffered_rate*end_time)
                times = numpy.linspace(start_time,end_time,
                                       (end_time - start_time)*self.buffered_rate,
                                       endpoint=False)
                values = raw_data[connection][start_index:end_index]
                dtypes = [('t', numpy.float32),('values', numpy.float32)]
                data = numpy.empty(len(data),dtype=dtypes)
                data['t'] = times
                data['values'] = values
                measurements.create_group(label, data=data)
            
            
            
            
            
            
