import gtk

import Queue
import subproc_utils
import threading
import logging
import numpy
import time
import os
import h5_lock, h5py
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
    
    def __init__(self,BLACS,notebook,settings,restart=False):
        self.settings = settings
        self.device_name = self.settings['device_name']
        self.MAX_name = self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection
        
        # All the arguments that the acquisition worker will require:
        acq_args = [self.device_name, self.MAX_name]
        
        Tab.__init__(self,BLACS,NiPCIe6363Worker,notebook,settings,workerargs={'acq_args':acq_args})
        
        self.static_mode = False
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'NI_6363.glade'))
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
        
    @define_state
    def destroy(self):
        # self.result_queue.put([None,None,None,None,'shutdown'])
        self.queue_work('close_device')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
     
    @define_state
    def initialise_device(self):
        self.queue_work('initialise',self.device_name, self.MAX_name, [self.min_ao_voltage,self.max_ao_voltage])
        self.do_after('leave_initialise_device')
        
    def leave_initialise_device(self,_results):        
        self.static_mode = True
        self.init_done = True
        self.toplevel.show()
    
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
        if _results is None:
            # The worker process failed and may be in an inconsistent state,
            # better raise a fatal exception so that it cannot continue without a restart:
            raise Exception('Transition to buffered failed')
        # The final values of the run, to update the GUI with at the
        # end of the run:
        self.final_analog_values, self.final_digital_values = _results
        # Tell the queue manager that we're done:
        notify_queue.put(self.device_name)
        
    @define_state
    def abort_buffered(self):
        self.static_mode = True
        self.queue_work('transition_to_static',abort=True)
        self.do_after('leave_transition_to_static',None)
        
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
        if _results is None:
            # The worker process failed and may be in an inconsistent state,
            # better raise a fatal exception so that it cannot continue without a restart:
            raise Exception('Transition to static failed')
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

        self.acquisition_worker = AcquisitionWorker()
        self.wait_monitor_worker = WaitMonitorWorker()
        self.to_acq_child, self.from_acq_child = self.acquisition_worker.start(self.acq_args)
        self.to_wait_child, self.from_wait_child = self.wait_monitor_worker.start(self.acq_args)

        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
    
    def initialise(self, device_name, MAX_name, limits):
        # Create AO task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        
        # Create DO task:
        self.do_task = Task()
        self.do_read = int32()
        self.do_data = numpy.zeros(48,dtype=numpy.uint8)
        
        self.device_name = device_name
        self.MAX_name = MAX_name
        self.limits = limits
        self.setup_static_channels()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.MAX_name+"/ao"+str(i),"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
        #setup DO ports
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line8:15","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line16:23","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line24:31","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port1/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port2/line0:7","",DAQmx_Val_ChanForAllLines)  
        
        # Start!  
        self.ao_task.StartTask()  
        self.do_task.StartTask()  
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        # Kill the acquisition and wait monitor subprocesses:
        self.to_acq_child.put(["shutdown", None])
        result, message = self.from_acq_child.get()
        if result == 'error':
            raise Exception(message)
        self.to_wait_child.put(["shutdown", None])
        result, message = self.from_wait_child.get()
        if result == 'error':
            raise Exception(message)
            
    def program_static(self,analog_values,digital_states):
        self.ao_data[:] = analog_values
        self.do_data[:] = digital_states
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
        self.do_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,self.do_data,byref(self.do_read),None)
    
    def program_buffered(self,h5file):
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
                do_bitfield = numpy.array(h5_data,dtype=numpy.uint32)
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
        # Tell the child processes to transition to buffered:
        self.to_acq_child.put(["transition to buffered",h5file,self.device_name])
        result, message = self.from_acq_child.get()
        if result == 'error':
            raise Exception(message)
        self.to_wait_child.put(["transition to buffered",(h5file,self.device_name)])
        result, message = self.from_wait_child.get()
        if result == 'error':
            raise Exception(message)
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
        # Tell both children to transition to static:    
        self.to_acq_child.put(["transition to static",(self.device_name,abort)])
        self.to_wait_child.put(["transition to static",(self.device_name,abort)])
        result,message = self.from_acq_child.get()
        if result == 'error':
            raise Exception(message)
        result,message = self.from_wait_child.get()
        if result == 'error':
            raise Exception(message)
        # Indicate success to the parent:
        return True
        
# Worker class for AI input:
class AcquisitionWorker(subproc_utils.Process):
    def run(self, args):
        exec 'import traceback' in globals()
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()

        self.device_name, self.MAX_name = args
        
        from setup_logging import setup_logging
        setup_logging()
        self.logger = logging.getLogger('BLACS.%s.acquisition'%self.device_name)
        self.task_running = False
        self.daqlock = threading.Condition()
        # Channel details
        self.channels = []
        self.rate = 1000.
        self.samples_per_channel = 1000
        self.ai_start_delay = 25e-9
        self.h5_file = ""
        self.buffered_channels = []
        self.buffered_rate = 0
        self.buffered = False
        self.buffered_data = None
        self.buffered_data_list = []
        
        self.task = None
        self.abort = False
        
        # And event for knowing when the wait durations are known, so that we may use them
        # to chunk up acquisition data:
        self.wait_durations_analysed = subproc_utils.Event('wait_durations_analysed')
        
        self.daqmx_read_thread = threading.Thread(target=self.daqmx_read)
        self.daqmx_read_thread.daemon = True
        self.daqmx_read_thread.start()
        self.mainloop()
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.acquisition.mainloop'%self.device_name)  
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
                    self.transition_to_static(*cmd[1])
                elif cmd == "":
                    pass
                self.to_parent.put(['done',None])
            except:
                message = traceback.format_exc()
                logger.error('An exception happened:\n %s'%message)
                self.to_parent.put(['error', message])
        self.to_parent.put(['done',None])
        
    def daqmx_read(self):
        logger = logging.getLogger('BLACS.%s.acquisition.daqmxread'%self.device_name)
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
                        acquisition_timeout = 5
                        error = self.task.ReadAnalogF64(self.samples_per_channel,acquisition_timeout,DAQmx_Val_GroupByChannel,self.ai_data,self.samples_per_channel*len(chnl_list),byref(self.ai_read),None)
                        logger.debug('Reading complete')
                        if error < 0:
                            raise Exception(error)
                        if error > 0:
                            logger.warning(error)
                    except Exception as e:
                        logger.error('acquisition error: %s' %str(e))
                        if self.abort:
                            # If an abort is in progress, then we expect an exception here. Don't raise it.
                            logger.debug('ignoring error since an abort is in progress.')
                            # Ensure the next iteration of this while loop
                            # doesn't happen until the task is restarted.
                            # The thread calling self.stop_task() is
                            # also setting self.task_running = False
                            # right about now, but we don't want to rely
                            # on it doing so in time. Doing it here too
                            # avoids a race condition.
                            self.task_running = False
                            continue
                        else:
                            # Error was likely a timeout error...some other device might be bing slow 
                            # transitioning to buffered, so we haven't got our start trigger yet. 
                            # Keep trying until task_running is False:
                            continue
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
                    pass
                    # Todo: replace this with zmq pub plus a broker somewhere so things can subscribe to channels
                    # and get their data without caring what process it came from. For the sake of speed, this
                    # should use the numpy buffer interface and raw zmq messages, and not the existing event system
                    # that subproc_utils has.
                    # self.result_queue.put([self.t0,self.rate,self.ai_read.value,len(self.channels),self.ai_data])
                    # self.t0 = self.t0 + self.samples_per_channel/self.rate
        except:
            message = traceback.format_exc()
            logger.error('An exception happened:\n %s'%message)
            self.to_parent.put(['error', message])
            
    def setup_task(self):
        self.logger.debug('setup_task')
        #DAQmx Configure Code
        with self.daqlock:
            self.logger.debug('setup_task got daqlock')
            if self.task:
                self.task.ClearTask()##
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
            group =  hdf5_file['/devices/'+device_name]
            self.clock_terminal = group.attrs['clock_terminal']
            if 'analog_in_channels' in group.attrs:
                h5_chnls = group.attrs['analog_in_channels'].split(', ')
                self.buffered_rate = float(group.attrs['acquisition_rate'])
            else:
               self.logger.debug("no input channels")
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
    
    def transition_to_static(self,device_name,abort):
        self.logger.debug('transition_to_static')
        # Stop acquisition (this should really be done on a digital edge, but that is for later! Maybe use a Counter)
        # Set the abort flag so that the acquisition thread knows to expect an exception in the case of an abort:
        self.abort = abort
        self.stop_task()
        # Reset the abort flag so that unexpected exceptions are still raised:        
        self.abort = False
        self.logger.info('transitioning to static, task stopped')
        # save the data acquired to the h5 file
        if not abort:
            with h5py.File(self.h5_file,'a') as hdf5_file:
                data_group = hdf5_file['data']
                data_group.create_group(device_name)

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
                self.extract_measurements(device_name)
                self.logger.info('data written, time taken: %ss' % str(time.time()-start_time))
            
            self.buffered_data = None
            self.buffered_data_list = []
            
            # Send data to callback functions as requested (in one big chunk!)
            #self.result_queue.put([self.t0,self.rate,self.ai_read,len(self.channels),self.ai_data])
        
        # return to previous acquisition mode
        self.buffered = False
        self.setup_task()
        
    def extract_measurements(self, device_name):
        self.logger.debug('extract_measurements')
        with h5py.File(self.h5_file,'a') as hdf5_file:
            waits_in_use = len(hdf5_file['waits']) > 0
        if waits_in_use:
            # There were waits in this shot. We need to wait until the other process has
            # determined their durations before we proceed:
            self.wait_durations_analysed.wait(self.h5_file)
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
            for connection,label,start_time,end_time,wait_name,scale_factor,units in acquisitions:
                start_index = numpy.ceil(self.buffered_rate*(start_time-self.ai_start_delay))
                end_index = numpy.floor(self.buffered_rate*(end_time-self.ai_start_delay))
                # numpy.ceil does what we want above, but float errors can miss the equality
                if self.ai_start_delay + (start_index-1)/self.buffered_rate - start_time > -2e-16:
                    start_index -= 1
                # We actually want numpy.floor(x) to yield the largest integer < x (not <=) 
                if end_time - self.ai_start_delay - end_index/self.buffered_rate < 2e-16:
                    end_index -= 1
                acquisition_start_time = self.ai_start_delay + start_index/self.buffered_rate
                acquisition_end_time = self.ai_start_delay + end_index/self.buffered_rate
                times = numpy.linspace(acquisition_start_time, acquisition_end_time, 
                                       end_index-start_index+1,
                                       endpoint=True)
                values = self.buffered_data[connection][start_index:end_index+1]
                dtypes = [('t', numpy.float64),('values', numpy.float32)]
                data = numpy.empty(len(values),dtype=dtypes)
                data['t'] = times
                data['values'] = values
                measurements.create_dataset(label, data=data)
            
            
# Worker class for monitoring of waits:
class WaitMonitorWorker(subproc_utils.Process):
    def run(self, args):
        exec 'import traceback' in globals()
        exec 'import ctypes' in globals()
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        
        self.device_name, self.MAX_name = args
        
        from setup_logging import setup_logging
        setup_logging()
        self.logger = logging.getLogger('BLACS.%s.wait_monitor'%self.device_name)
        self.task_running = False
        self.daqlock = threading.Lock() # not sure if needed, access should be serialised already
        self.h5_file = None
        self.task = None
        self.abort = False
        self.all_waits_finished = subproc_utils.Event('all_waits_finished',type='post')
        self.wait_durations_analysed = subproc_utils.Event('wait_durations_analysed',type='post')
        self.mainloop()
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.wait_monitor.mainloop'%self.device_name)  
        logger.info('Starting')
        while True:
            logger.debug('Waiting for instructions')
            signal, data = self.from_parent.get()
            logger.debug('Got a command: %s' % signal)
            # Process the command
            try:
                if signal == "shutdown":
                    logger.info('Shutdown requested, stopping task')
                    if self.task_running:
                        self.stop_task()                  
                    break
                elif signal == "transition to buffered":
                    h5_file, device_name = data
                    self.transition_to_buffered(h5_file, device_name)
                elif signal == "transition to static":
                    device_name, abort = data
                    self.transition_to_static(device_name, abort)
                self.to_parent.put(['done',None])
            except:
                message = traceback.format_exc()
                logger.error('An exception happened:\n %s'%message)
                self.to_parent.put(['error', message])
        self.to_parent.put(['done',None])
    
    def read_one_half_period(self, timeout, readarray = numpy.empty(1)):
        try:
            with self.daqlock:
                self.acquisition_task.ReadCounterF64(1, timeout, readarray, len(readarray), ctypes.c_long(1), None)
                self.half_periods.append(readarray[0])
            return readarray[0]
        except Exception:
            if self.abort:
                raise
            # otherwise, it's a timeout:
            return None
    
    def wait_for_edge(self, timeout=None):
        if timeout is None:
            while True:
                half_period = self.read_one_half_period(1)
                if half_period is not None:
                    return half_period
        else:
            return self.read_one_half_period(timeout)
                
    def daqmx_read(self):
        logger = logging.getLogger('BLACS.%s.wait_monitor.read_thread'%self.device_name)
        logger.info('Starting')
        try:
            # Wait for the end of the first pulse indicating the start of the experiment:
            current_time = pulse_width = self.wait_for_edge()
            # alright, we're now a short way into the experiment.
            for wait in self.wait_table:
                # How long until this wait should time out?
                timeout = wait['time'] + wait['timeout'] - current_time
                timeout = max(timeout, 0) # ensure non-negative
                # Wait that long for the next pulse:
                half_period = self.wait_for_edge(timeout)
                # Did the wait finish of its own accord?
                if half_period is not None:
                    # It did, we are now at the end of that wait:
                    current_time = wait['time']
                    # Wait for the end of the pulse:
                    current_time += self.wait_for_edge()
                else:
                    # It timed out. Better trigger the clock to resume!.
                    self.send_resume_trigger(pulse_width)
                    # Wait for it to respond to that:
                    self.wait_for_edge()
                    # Alright, *now* we're at the end of the wait.
                    current_time = wait['time']
                    # And wait for the end of the pulse:
                    current_time += self.wait_for_edge()

            # Inform any interested parties that waits have all finished:
            self.all_waits_finished.post(self.h5_file)
        except Exception:
            if self.abort:
                return
            else:
                raise
    
    def send_resume_trigger(self, pulse_width):
        written = int32()
        # go high:
        self.timeout_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,numpy.ones(1, dtype=numpy.uint8),byref(written),None)
        assert written.value == 1
        # Wait however long we observed the first pulse of the experiment to be:
        time.sleep(pulse_width)
        # go low:
        self.timeout_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,numpy.zeros(1, dtype=numpy.uint8),byref(written),None)
        assert written.value == 1
        
    def stop_task(self):
        self.logger.debug('stop_task')
        with self.daqlock:
            self.logger.debug('stop_task got daqlock')
            if self.task_running:
                self.task_running = False
                self.acquisition_task.StopTask()
                self.acquisition_task.ClearTask()
                self.timeout_task.StopTask()
                self.timeout_task.ClearTask()
        self.logger.debug('finished stop_task')
        
    def transition_to_buffered(self,h5file,device_name):
        self.logger.debug('transition_to_buffered')
        # Save h5file path (for storing data later!)
        self.h5_file = h5file
        self.logger.debug('setup_task')
        with h5py.File(h5file, 'r') as hdf5_file:
            dataset = hdf5_file['waits']
            if len(dataset) == 0:
                # There are no waits. Do nothing.
                self.logger.debug('There are no waits, not transitioning to buffered')
                self.waits_in_use = False
                return
            self.waits_in_use = True
            acquisition_device = dataset.attrs['wait_monitor_acquisition_device']
            acquisition_connection = dataset.attrs['wait_monitor_acquisition_connection']
            timeout_device = dataset.attrs['wait_monitor_timeout_device']
            timeout_connection = dataset.attrs['wait_monitor_timeout_connection']
            self.wait_table = dataset[:]
        # Only do anything if we are in fact the wait_monitor device:
        if timeout_device == device_name or acquisition_device == device_name:
            if not timeout_device == device_name and acquisition_device == device_name:
                raise NotImplementedError("ni-PCIe-6363 worker must be both the wait monitor timeout device and acquisition device." +
                                          "Being only one could be implemented if there's a need for it, but it isn't at the moment")
            
            # The counter acquisition task:
            self.acquisition_task = Task()
            acquisition_chan = '/'.join([self.MAX_name,acquisition_connection])
            self.acquisition_task.CreateCISemiPeriodChan(acquisition_chan, '', 100e-9, 200, DAQmx_Val_Seconds, "")    
            self.acquisition_task.CfgImplicitTiming(DAQmx_Val_ContSamps, 1000)
            self.acquisition_task.StartTask()
            # The timeout task:
            self.timeout_task = Task()
            timeout_chan = '/'.join([self.MAX_name,timeout_connection])
            self.timeout_task.CreateDOChan(timeout_chan,"",DAQmx_Val_ChanForAllLines)
            self.task_running = True
                
            # An array to store the results of counter acquisition:
            self.half_periods = []
            self.read_thread = threading.Thread(target=self.daqmx_read)
            # Not a daemon thread, as it implements wait timeouts - we need it to stay alive if other things die.
            self.read_thread.start()
            self.logger.debug('finished transition to buffered')
    
    def transition_to_static(self,device_name,abort):
        self.logger.debug('transition_to_static')
        self.abort = abort
        self.stop_task()
        # Reset the abort flag so that unexpected exceptions are still raised:        
        self.abort = False
        self.logger.info('transitioning to static, task stopped')
        # save the data acquired to the h5 file
        if not abort:
            if self.waits_in_use:
                # Let's work out how long the waits were. The absolute times of each edge on the wait
                # monitor were:
                edge_times = numpy.cumsum(self.half_periods)
                # Now there was also a rising edge at t=0 that we didn't measure:
                edge_times = numpy.insert(edge_times,0,0)
                # Ok, and the even-indexed ones of these were rising edges.
                rising_edge_times = edge_times[::2]
                # Now what were the times between rising edges?
                periods = numpy.diff(rising_edge_times)
                # How does this compare to how long we expected there to be between the start
                # of the experiment and the first wait, and then between each pair of waits?
                # The difference will give us the waits' durations.
                resume_times = self.wait_table['time']
                # Again, include the start of the experiment, t=0:
                resume_times =  numpy.insert(resume_times,0,0)
                run_periods = numpy.diff(resume_times)
                wait_durations = periods - run_periods
                waits_timed_out = wait_durations > self.wait_table['timeout']
            with h5py.File(self.h5_file,'a') as hdf5_file:
                # Work out how long the waits were, save em, post an event saying so 
                dtypes = [('label','a256'),('time',float),('timeout',float),('duration',float),('timed_out',bool)]
                data = numpy.empty(len(self.wait_table), dtype=dtypes)
                if self.waits_in_use:
                    data['label'] = self.wait_table['label']
                    data['time'] = self.wait_table['time']
                    data['timeout'] = self.wait_table['timeout']
                    data['duration'] = wait_durations
                    data['timed_out'] = waits_timed_out
                hdf5_file.create_dataset('/data/waits', data=data)
            self.wait_durations_analysed.post(self.h5_file)
            
