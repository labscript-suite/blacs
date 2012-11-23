import gtk

import numpy
import excepthook

from tab_base_classes import Tab, Worker, define_state
from output_classes import AO, DO, DDS

class ni_pci_6733(Tab):
    # Capabilities
    num_DO = 0
    num_AO = 8
    num_RF = 0
    num_AI = 0
    max_ao_voltage = 10.0
    min_ao_voltage = -10.0
    ao_voltage_step = 0.1
    
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,NiPCI6733Worker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.MAX_name = self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection
        self.static_mode = True
        self.destroy_complete = False
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/NI_6733.glade')
        self.builder.connect_signals(self)   
        self.toplevel = self.builder.get_object('toplevel')
            
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
        self.init_done = False
        self.queue_work('close_device')
        self.do_after('leave_destroy')
        
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
     
    @define_state
    def initialise_device(self):
        self.queue_work('initialise', self.device_name, self.MAX_name,[self.min_ao_voltage,self.max_ao_voltage])
        
    def get_front_panel_state(self):
        state = {}
        for i in range(self.num_AO):
            state["AO"+str(i)] = self.analog_outs[i].value
        return state
    
    @define_state
    def program_static(self,output=None):
        if self.static_mode:
            self.queue_work('program_static',[output.value for output in self.analog_outs])

    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False      
        self.queue_work('program_buffered',h5file)
        self.do_after('leave_program_buffered',notify_queue)
    
    def leave_program_buffered(self,notify_queue,_results):
        # The final values of the run, to update the GUI with at the
        # end of the run:
        self.final_values = _results
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
        for channel, value in self.final_values.items():
            self.analog_outs_by_channel[channel].set_value(value,program=False)
        
    def leave_transition_to_static(self,notify_queue,_results):    
        # Tell the queue manager that we're done:
        if notify_queue is not None:
            notify_queue.put(self.device_name)

    def get_child(self,type,channel):
        if type == "AO":
            if channel >= 0 and channel < self.num_AO:
                return self.analog_outs[channel]
		
        # We don't have any of this type, or the channel number was invalid
        return None
    
    
class NiPCI6733Worker(Worker):

    num_AO = 8
    
    def init(self):
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        global pylab; import pylab
        global h5py; import h5_lock, h5py
        
    def initialise(self, device_name, MAX_name, limits):
        # Create task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num_AO,), dtype=numpy.float64)
        self.device_name = device_name
        self.MAX_name = MAX_name
        self.limits = limits
        self.setup_static_channels()            
        
        #DAQmx Start Code        
        self.ao_task.StartTask()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(self.num_AO): 
            self.ao_task.CreateAOVoltageChan(self.MAX_name+"/ao%d"%i,"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
    def close_device(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        
    def program_static(self,analog_data):
        self.ao_data[:] = analog_data
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
          
    def program_buffered(self,h5file):  
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/'][self.device_name]
            clock_terminal = group.attrs['clock_terminal']
            h5_data = group.get('ANALOG_OUTS')
            if h5_data:
                ao_channels = group.attrs['analog_out_channels']
                # We use all but the last sample (which is identical to the
                # second last sample) in order to ensure there is one more
                # clock tick than there are samples. The 6733 requires this
                # to determine that the task has completed.
                ao_data = pylab.array(h5_data,dtype=float64)[:-1,:]
                
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
                final_values = {channel: value for channel, value in zip(channel_list, ao_data[-1,:])}
                return final_values
            else:
                return {}
        
    def transition_to_static(self,abort=False):
        if not abort:
            # if aborting, don't call StopTask since this throws an
            # error if the task hasn't actually finished!
            self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.ao_task = Task()
        self.setup_static_channels()
        self.ao_task.StartTask()
        if abort:
            # Reprogram the initial states:
            self.program_static(self.ao_data)
        
        
