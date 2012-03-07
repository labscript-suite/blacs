import gtk

import Queue
import multiprocessing
import threading
import logging
import numpy
import time
import h5py
import excepthook

from tab_base_classes import Tab, Worker, define_state
from output_classes import AO, DO, DDS

class ni_pcie_6363(Tab):
    num_DO = 48
    num_AO = 4
    num_RF = 0
    num_AI = 32
    max_ao_voltage = 10.0
    min_ao_voltage = -10.0
    ao_voltage_step = 0.1
    
    def __init__(self,notebook,settings,restart=False):
        self.settings = settings
        self.device_name = self.settings['device_name']
        
        # Queues that need to be passed to the worker process, which in
        # turn passes them to the acquisition process: AI worker thread
        self.write_queue = multiprocessing.Queue()
        self.read_queue = multiprocessing.Queue()
        self.result_queue = multiprocessing.Queue()
        
        # All the arguments that the acquisition worker will require:
        acq_args = [self.settings['device_name'], self.write_queue, self.read_queue, self.result_queue]
        
        Tab.__init__(self,NiPCIe6363Worker,notebook,settings,workerargs={'acq_args':acq_args})
        
        self.static_mode = False
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/NI_6363.glade')
        self.builder.connect_signals(self)
        self.toplevel = self.builder.get_object('toplevel')
        
        self.digital_outs = []
        self.digital_outs_by_channel = {}
        for i in range(self.num_DO):
            # get the widget:
            toggle_button = self.builder.get_object("do_toggle_%d"%(i+1))
		
            #programatically change labels!
            channel_label= self.builder.get_object("do_hardware_label_%d"%(i+1))
            name_label = self.builder.get_object("do_real_label_%d"%(i+1))
            
            if i < 32:
                channel_label.set_text("DO P0:"+str(i))
                channel = "port0/line"+str(i)
            elif i < 40:
                channel_label.set_text("DO P1:"+str(i-32)+" (PFI "+str(i-32)+")")
                channel = "port1/line"+str(i-32)
            else:
                channel_label.set_text("DO P2:"+str(i-40)+" (PFI "+str(i-32)+")")
                channel = "port2/line"+str(i-40)
            
            device = self.settings["connection_table"].find_child(self.settings["device_name"],channel)
            name = device.name if device else '-'
            
            name_label.set_text(name)
            
            output = DO(name, channel, toggle_button, self.program_static)
            output.update(settings)
            
            self.digital_outs.append(output)
            self.digital_outs_by_channel[channel] = output

        self.analog_outs = []
        self.analog_outs_by_channel = {}
        for i in range(self.num_AO):
            # Get the widgets:
            spinbutton = self.builder.get_object("AO_value_%d"%(i+1))
            combobox = self.builder.get_object('ao_units_%d'%(i+1))
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
                calib = device.unit_conversion_class
                calib_params = eval(device.unit_conversion_params)
            
            output = AO(name, channel,spinbutton, combobox, calib, calib_params, def_calib_params, self.program_static, self.min_ao_voltage, self.max_ao_voltage, self.ao_voltage_step)
            output.update(settings)
            
            self.analog_outs.append(output)
            self.analog_outs_by_channel[channel] = output
                        
        self.viewport.add(self.toplevel)
        self.initialise_device()
        self.program_static()
        
        # Start acquisition thread which distributes newly acquired data to registered methods
        self.get_data_thread = threading.Thread(target = self.get_acquisition_data)
        self.get_data_thread.daemon = True
        self.get_data_thread.start()
        
    @define_state
    def destroy(self):
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
            #TODO will need to split up the array. (single channel is assumed -- will need to extend for multiple channels)
            with gtk.gdk.lock:
                logger.debug('Calling callbacks')
                #TODO
                
    def get_front_panel_state(self):
        state = {}
        for i in range(self.num_AO):
            state["AO"+str(i)] = self.analog_outs[i].value
        for i in range(self.num_AO):
            state["DO"+str(i)] = self.digital_outs[i].state
        return state

    @define_state
    def program_static(self,output=None):
        if self.static_mode:
            analog_values = [output.value for output in self.analog_outs]
            digital_states = [output.state for output in self.digital_outs]
            self.queue_work('program_static',analog_values, digital_states)

    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False               
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        # The final values of the run, to update the GUI with at the
        # end of the run:
        self.final_analog_values, self.final_digital_values = _results
        # Tell the queue manager that we're done:
        notify_queue.put(self.device_name)
        
    @define_state
    def abort_buffered(self):      
        self.queue_work('transition_to_static',abort=True)
        
    @define_state        
    def transition_to_static(self,notify_queue):
        self.static_mode = True
        self.queue_work('transition_to_static')
        self.do_after('leave_transition_to_static',notify_queue)
        # Update the GUI with the final values of the run:
        for channel, value in self.final_analog_values.items():
            self.analog_outs_by_channel[channel].set_value(value,program=False)
        for channel, state in self.final_digital_values.items():
            self.digital_outs_by_channel[channel].set_state(state,program=False)
            
    def leave_transition_to_static(self,notify_queue,_results):    
        # Tell the queue manager that we're done:
        if notify_queue is not None:
            notify_queue.put(self.device_name)
        
    def get_child(self,type,channel):
        if type == "AO":
            if channel in range(self.num_AO):
                return self.analog_outs[channel]
        if type == "DO":
            if channel in range(self.num_DO):
                return self.digital_outs[channel]
		
        # We don't have any of this type, or the channel number was invalid
        return None
    
    
class NiPCIe6363Worker(Worker):
    num_DO = 48
    num_AO = 4
    num_AI = 32 
    num_buffered_DO = 32
        
    def init(self):
        # Start the data acquisition subprocess:
        self.acquisition_worker = Worker2(args=self.acq_args)
        ignore, self.to_child, self.from_child, ignore = self.acq_args
        self.acquisition_worker.daemon = True
        self.acquisition_worker.start()
        
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
    
    def initialise(self, device_name, limits):
        # Create AO task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        
        # Create DO task:
        self.do_task = Task()
        self.do_read = int32()
        self.do_data = numpy.zeros(48,dtype=numpy.uint8)
        
        self.device_name = device_name
        self.limits = limits
        self.setup_static_channels()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.device_name+"/ao"+str(i),"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
        #setup DO ports
        self.do_task.CreateDOChan(self.device_name+"/port0/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line8:15","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line16:23","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port0/line24:31","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port1/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.device_name+"/port2/line0:7","",DAQmx_Val_ChanForAllLines)  
        
        # Start!  
        self.ao_task.StartTask()  
        self.do_task.StartTask()  
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        # Kill the acquisition subprocess:
        self.to_child.put(["shutdown"])
        result, message = self.from_child.get()
        if result == 'error':
            raise Exception(message)
            
    def program_static(self,analog_values,digital_states):
        self.ao_data[:] = analog_values
        self.do_data[:] = digital_states
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
        self.do_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,self.do_data,byref(self.do_read),None)
    
    def program_buffered(self,h5file):        
        self.to_child.put(["transition to buffered",h5file,self.device_name])
        result, message = self.from_child.get()
        if result == 'error':
            raise Exception(message)
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/'][self.device_name]
            clock_terminal = group.attrs['clock_terminal']
            h5_data = group.get('ANALOG_OUTS')
            if h5_data:
                ao_channels = group.attrs['analog_out_channels']
                ao_data = numpy.array(h5_data,dtype=float64)
                
                self.ao_task.StopTask()
                self.ao_task.ClearTask()
                self.ao_task = Task()
                ao_read = int32()

                self.ao_task.CreateAOVoltageChan(ao_channels,"",-10.0,10.0,DAQmx_Val_Volts,None)
                self.ao_task.CfgSampClkTiming(clock_terminal,1000000,DAQmx_Val_Rising,DAQmx_Val_FiniteSamps, ao_data.shape[0])
                
                self.ao_task.WriteAnalogF64(ao_data.shape[0],False,10.0,DAQmx_Val_GroupByScanNumber, ao_data,ao_read,None)
                self.ao_task.StartTask()   
                
                # Final values here are a dictionary of values, keyed by channel:
                channel_list = [channel.split('/')[1] for channel in ao_channels.split(', ')]
                final_analog_values = {channel: value for channel, value in zip(channel_list, ao_data[-1,:])}
            else:
                final_analog_values = {}
            h5_data = group.get('DIGITAL_OUTS')
            if h5_data:
                self.buffered_digital = True
                do_channels = group.attrs['digital_lines']
                do_bitfield = numpy.array(h5_data,dtype=int32)
                # Expand each bitfield int into self.num_buffered_DO
                # (32) individual ones and zeros:
                do_write_data = numpy.zeros((do_bitfield.shape[0],self.num_buffered_DO),dtype=numpy.uint8)
                for i in range(self.num_buffered_DO):
                    do_write_data[:,i] = (do_bitfield & (1 << i)) >> i
                    
                self.do_task.StopTask()
                self.do_task.ClearTask()
                self.do_task = Task()
                self.do_read = int32()
        
                self.do_task.CreateDOChan(do_channels,"",DAQmx_Val_ChanPerLine)
                self.do_task.CfgSampClkTiming(clock_terminal,1000000,DAQmx_Val_Rising,DAQmx_Val_FiniteSamps,do_bitfield.shape[0])
                self.do_task.WriteDigitalLines(do_bitfield.shape[0],False,10.0,DAQmx_Val_GroupByScanNumber,do_write_data,self.do_read,None)
                self.do_task.StartTask()
                final_digital_values = {'port0/line%d'%i: do_write_data[-1,i] for i in range(self.num_buffered_DO)}
            else:
                self.buffered_digital = False
                # We still have to stop the task to make the 
                # clock flag available for buffered analog output:
                self.do_task.StopTask()
                self.do_task.ClearTask()
                final_digital_values = {}
            
            return final_analog_values, final_digital_values
            
    def transition_to_static(self,abort=False):
        if not abort:
            # if aborting, don't call StopTask since this throws an
            # error if the task hasn't actually finished!
            self.ao_task.StopTask()
            if self.buffered_digital:
                # only stop the digital task if there actually was one:
                self.do_task.StopTask()
        self.ao_task.ClearTask()
        if self.buffered_digital:
            # only clear the digital task if there actually was one:
            self.do_task.ClearTask()
        self.ao_task = Task()
        self.do_task = Task()
        self.setup_static_channels()
        if abort:
            # Reprogram the initial states:
            self.program_static(self.ao_data, self.do_data)
            
        self.to_child.put(["transition to static",self.device_name])
        result,message = self.from_child.get()
        if result == 'error':
            raise Exception(message)
        
# Worker class for AI input:
class Worker2(multiprocessing.Process):
    def run(self):
        exec 'import traceback' in globals()
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        
        self.name, self.from_parent, self.to_parent, self.result_queue = self._args
        self.logger = logging.getLogger('BLACS.%s.acquisition'%self.name)
        self.task_running = False
        self.daqlock = threading.Condition()
        # Channel details
        self.channels = []
        self.rate = 1000.
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
            cmd = self.from_parent.get()
            logger.debug('Got a command: %s' % cmd[0])
            # Process the command
            try:
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
                self.to_parent.put(['done',None])
            except:
                message = traceback.format_exc()
                logger.error('An exception happened:\n %s'%message)
                self.to_parent.put(['error', message])
        self.to_parent.put(['done',None])
        
    def daqmx_read(self):
        logger = logging.getLogger('BLACS.%s.acquisition.daqmxread'%self.name)
        logger.info('Starting')
        #first_read = True
        try:
            while True:
                with self.daqlock:
                    logger.debug('Got daqlock')
                    while not self.task_running:
                        logger.debug('Task isn\'t running. Releasing daqlock and waiting to reacquire it.')
                        self.daqlock.wait()
                    logger.debug('Reading data from analogue inputs')
                    if self.buffered:
                        chnl_list = self.buffered_channels
                    else:
                        chnl_list = self.channels
                    try:
                        error = "Task did not return an error, but it should have"
                        error = self.task.ReadAnalogF64(self.samples_per_channel,5,DAQmx_Val_GroupByChannel,self.ai_data,self.samples_per_channel*len(chnl_list),byref(self.ai_read),None)
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
        except:
            message = traceback.format_exc()
            logger.error('An exception happened:\n %s'%message)
            self.to_parent.put(['error', message])
            
    def setup_task(self):
        self.logger.debug('setup_task')
        #DAQmx Configure Code
        with self.daqlock:
            self.logger.debug('setup_task got daqlock')
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
            try:
                self.task = Task()
            except Exception as e:
                self.logger.error(str(e))
            self.ai_read = int32()
            self.ai_data = numpy.zeros((self.samples_per_channel*len(chnl_list),), dtype=numpy.float64)   
            
            for chnl in chnl_list:
                self.task.CreateAIVoltageChan(chnl,"",DAQmx_Val_RSE,-10.0,10.0,DAQmx_Val_Volts,None)
                
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
        self.logger.debug('finished setup_task')
        
    def stop_task(self):
        self.logger.debug('stop_task')
        with self.daqlock:
            self.logger.debug('stop_task got daqlock')
            if self.task_running:
                self.task_running = False
                self.task.StopTask()
                self.task.ClearTask()
            self.daqlock.notify()
        self.logger.debug('finished stop_task')
        
    def transition_to_buffered(self,h5file,device_name):
        self.logger.debug('transition_to_buffered')
        # stop current task
        self.stop_task()
        
        self.buffered_data_list = []
        
        # Save h5file path (for storing data later!)
        self.h5_file = h5file
        # read channels, acquisition rate, etc from H5 file
        h5_chnls = []
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                group =  hdf5_file['/devices/'+device_name]
                self.clock_terminal = group.attrs['clock_terminal']
                h5_chnls = group.attrs['analog_in_channels'].split(', ')
                self.buffered_rate = float(group.attrs['acquisition_rate'])
            except:
                self.logger.error("couldn't get the channel list from h5 file. Skipping...")
        
        # combine static channels with h5 channels (using a set to avoid duplicates)
        self.buffered_channels = set(h5_chnls)
        self.buffered_channels.update(self.channels)
        # Now make it a sorted list:
        self.buffered_channels = sorted(list(self.buffered_channels))
        
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
            try:
                data_group = hdf5_file['data']
            except KeyError:
                # If the data group doesn't exist, then the run must've been aborted. Nothing to do here:
                return
            ni_group = data_group.create_group(device_name)

            dtypes = [(chan.split('/')[-1],numpy.float32) for chan in sorted(self.buffered_channels)]

            start_time = time.time()
            if self.buffered_data_list:
                self.buffered_data = numpy.zeros(len(self.buffered_data_list)*1000,dtype=dtypes)
                for i, data in enumerate(self.buffered_data_list):
                    data.shape = (len(self.buffered_channels),self.ai_read.value)              
                    for j, (chan, dtype) in enumerate(dtypes):
                        self.buffered_data[chan][i*1000:(i*1000)+1000] = data[j,:]
                    if i % 100 == 0:
                        self.logger.debug( str(i/100) + " time: "+str(time.time()-start_time))
                ni_group.create_dataset('analog_data', data = self.buffered_data)
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
                acquisitions = hdf5_file['/devices/'+device_name+'/ACQUISITIONS']
            except:
                # No acquisitions!
                return
            try:
                measurements = hdf5_file['/data/traces']
            except:
                # Group doesn't exist yet, create it:
                measurements = hdf5_file.create_group('/data/traces')
            raw_data = hdf5_file['/data/'+device_name+'/analog_data']
            for connection,label,start_time,end_time,scale_factor,units in acquisitions:
                start_index = numpy.floor(self.buffered_rate*start_time)
                end_index = numpy.ceil(self.buffered_rate*end_time)
                times = numpy.linspace(start_time,end_time,
                                       (end_time - start_time)*self.buffered_rate,
                                       endpoint=False)
                values = raw_data[connection][start_index:end_index]
                dtypes = [('t', numpy.float32),('values', numpy.float32)]
                data = numpy.empty(len(values),dtype=dtypes)
                data['t'] = times
                data['values'] = values
                measurements.create_dataset(label, data=data)
            
            
            
            
            
            
