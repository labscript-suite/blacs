from time import time

from BLACS.tab_base_classes import Worker, define_state
from BLACS.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  
from BLACS.device_base_class import DeviceTab

class ni_pcie_6363(DeviceTab):
    def initialise_GUI(self):
        # Capabilities
        num_AO = 4
        num = {'AO':4, 'DO':32, 'PFI':16}
        
        base_units = {'AO':'V'}
        base_min = {'AO':-10.0}
        base_max = {'AO':10.0}
        base_step = {'AO':0.1}
        base_decimals = {'AO':3}
        
        # Create the AO output objects
        ao_prop = {}
        for i in range(num['AO']):
            ao_prop['ao%d'%i] = {'base_unit':base_units['AO'],
                                 'min':base_min['AO'],
                                 'max':base_max['AO'],
                                 'step':base_step['AO'],
                                 'decimals':base_decimals['AO']
                                }
        
        do_prop = {}
        for i in range(num['DO']):
            do_prop['port0/line%d'%i] = {}
            
        pfi_prop = {}
        for i in range(num['PFI']):
            pfi_prop['PFI %d'%i] = {}
        
        
        # Create the output objects    
        self.create_analog_outputs(ao_prop)        
        # Create widgets for analog outputs only
        dds_widgets,ao_widgets,do_widgets = self.auto_create_widgets()
        
        # now create the digital output objects
        self.create_digital_outputs(do_prop)
        self.create_digital_outputs(pfi_prop)
        # manually create the digital output widgets so they are grouped separately
        do_widgets = self.create_digital_widgets(do_prop)
        pfi_widgets = self.create_digital_widgets(pfi_prop)
        
        def do_sort(channel):
            flag = channel.replace('port0/line','')
            flag = int(flag)
            return '%02d'%(flag)
            
        def pfi_sort(channel):
            flag = channel.replace('PFI ','')
            flag = int(flag)
            return '%02d'%(flag)
        
        # and auto place the widgets in the UI
        self.auto_place_widgets(("Analog Outputs",ao_widgets),("Digital Outputs",do_widgets,do_sort),("PFI Outputs",pfi_widgets,pfi_sort))
        
        # Store the Measurement and Automation Explorer (MAX) name
        self.MAX_name = str(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
        
        # Create and set the primary worker
        self.create_worker("main_worker",NiPCIe6363Worker,{'MAX_name':self.MAX_name, 'limits': [base_min['AO'],base_max['AO']], 'num':num})
        self.primary_worker = "main_worker"

        # Set the capabilities of this device
        self.supports_remote_value_check(False)
        self.supports_smart_programming(False) 
    

class NiPCIe6363Worker(Worker):
    def init(self):
        exec 'from PyDAQmx import Task' in globals()
        exec 'from PyDAQmx.DAQmxConstants import *' in globals()
        exec 'from PyDAQmx.DAQmxTypes import *' in globals()
        global pylab; import pylab
        global h5py; import h5_lock, h5py
        
    def initialise(self):    
        # Create task
        self.ao_task = Task()
        self.ao_read = int32()
        self.ao_data = numpy.zeros((self.num['AO'],), dtype=numpy.float64)
        
        # Create DO task:
        self.do_task = Task()
        self.do_read = int32()
        self.do_data = numpy.zeros(self.num['DO']+self.num['PFI'],dtype=numpy.uint8)
        
        self.setup_static_channels()            
        
        #DAQmx Start Code        
        self.ao_task.StartTask() 
        self.do_task.StartTask()  
        
    def setup_static_channels(self):
        #setup AO channels
        for i in range(self.num['AO']): 
            self.ao_task.CreateAOVoltageChan(self.MAX_name+"/ao%d"%i,"",self.limits[0],self.limits[1],DAQmx_Val_Volts,None)
        
        #setup DO ports
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line8:15","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line16:23","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port0/line24:31","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port1/line0:7","",DAQmx_Val_ChanForAllLines)
        self.do_task.CreateDOChan(self.MAX_name+"/port2/line0:7","",DAQmx_Val_ChanForAllLines)  
                
    def shutdown(self):        
        self.ao_task.StopTask()
        self.ao_task.ClearTask()
        self.do_task.StopTask()
        self.do_task.ClearTask()
        
    def program_manual(self,front_panel_values):
        for i in range(self.num['AO']):
            self.ao_data[i] = front_panel_values['ao%d'%i]
        self.ao_task.WriteAnalogF64(1,True,1,DAQmx_Val_GroupByChannel,self.ao_data,byref(self.ao_read),None)
        
        for i in range(self.num['DO']):
            self.do_data[i] = front_panel_values['port0/line%d'%i]
            
        for i in range(self.num['PFI']):
            self.do_data[i+self.num['DO']] = front_panel_values['PFI %d'%i]
        self.do_task.WriteDigitalLines(1,True,1,DAQmx_Val_GroupByChannel,self.do_data,byref(self.do_read),None)
    
        
    def transition_to_buffered(self,device_name,h5file,initial_values,fresh):
        # Store the initial values in case we have to abort and restore them:
        self.initial_values = initial_values
            
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/'][device_name]
            clock_terminal = group.attrs['clock_terminal']
            h5_data = group.get('ANALOG_OUTS')
            if h5_data:
                self.buffered_using_analog = True
                ao_channels = group.attrs['analog_out_channels']
                # We use all but the last sample (which is identical to the
                # second last sample) in order to ensure there is one more
                # clock tick than there are samples. The 6733 requires this
                # to determine that the task has completed.
                ao_data = pylab.array(h5_data,dtype=float64)[:-1,:]
            else:
                self.buffered_using_analog = False
                
            h5_data = group.get('DIGITAL_OUTS')
            if h5_data:
                self.buffered_using_digital = True
                do_channels = group.attrs['digital_lines']
                do_bitfield = numpy.array(h5_data,dtype=numpy.uint32)
            else:
                self.buffered_using_digital = False
                
                
        
        final_values = {}
        if self.buffered_using_analog:
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
            for channel, value in zip(channel_list, ao_data[-1,:]):
                final_values[channel] = value
        else:
            # we should probabaly still stop the task (this makes it easier to setup the task later)
            self.ao_task.StopTask()
            self.ao_task.ClearTask()
                
        if self.buffered_using_digital:
            # Expand each bitfield int into self.num['DO']
            # (32) individual ones and zeros:
            do_write_data = numpy.zeros((do_bitfield.shape[0],self.num['DO']),dtype=numpy.uint8)
            for i in range(self.num['DO']):
                do_write_data[:,i] = (do_bitfield & (1 << i)) >> i
                
            self.do_task.StopTask()
            self.do_task.ClearTask()
            self.do_task = Task()
            self.do_read = int32()
    
            self.do_task.CreateDOChan(do_channels,"",DAQmx_Val_ChanPerLine)
            self.do_task.CfgSampClkTiming(clock_terminal,1000000,DAQmx_Val_Rising,DAQmx_Val_FiniteSamps,do_bitfield.shape[0])
            self.do_task.WriteDigitalLines(do_bitfield.shape[0],False,10.0,DAQmx_Val_GroupByScanNumber,do_write_data,self.do_read,None)
            self.do_task.StartTask()
            
            for i in range(self.num['DO']):
                final_values['port0/line%d'%i] = do_write_data[-1,i]
        else:
            # We still have to stop the task to make the 
            # clock flag available for buffered analog output, or the wait monitor:
            self.do_task.StopTask()
            self.do_task.ClearTask()
            
        return final_values
        
    def transition_to_manual(self,abort=False):
        # if aborting, don't call StopTask since this throws an
        # error if the task hasn't actually finished!
        if self.buffered_using_analog:
            if not abort:
                self.ao_task.StopTask()
            self.ao_task.ClearTask()
        if self.buffered_using_digital:
            if not abort:
                self.do_task.StopTask()
            self.do_task.ClearTask()
                
        self.ao_task = Task()
        self.do_task = Task()
        self.setup_static_channels()
        self.ao_task.StartTask()
        self.do_task.StartTask()
        if abort:
            # Reprogram the initial states:
            self.program_manual(self.initial_values)
            
        return True
        
    def abort_transition_to_buffered(self):
        # TODO: untested
        return self.transition_to_manual(True)
        
    def abort_buffered(self):
        # TODO: untested
        return self.transition_to_manual(True)    

        
if __name__ == '__main__':
    from PySide.QtCore import *
    from PySide.QtGui import *
    import sys,os
    from qtutils.widgets.dragdroptab import DragDropTabWidget
    from BLACS.connections import ConnectionTable
    
    
    class MyWindow(QWidget):
        
        def __init__(self,*args,**kwargs):
            QWidget.__init__(self,*args,**kwargs)
            self.are_we_closed = False
        
        def closeEvent(self,event):
            if not self.are_we_closed:        
                event.ignore()
                self.my_tab.destroy()
                self.are_we_closed = True
                QTimer.singleShot(1000,self.close)
            else:
                if not self.my_tab.destroy_complete: 
                    QTimer.singleShot(1000,self.close)                    
                else:
                    event.accept()
    
        def add_my_tab(self,tab):
            self.my_tab = tab
    
    app = QApplication(sys.argv)
    window = MyWindow()
    layout = QVBoxLayout(window)
    notebook = DragDropTabWidget()
    layout.addWidget(notebook)
    connection_table = ConnectionTable(os.path.join(os.path.dirname(os.path.realpath(__file__)),r'../example_connection_table.h5'))
    tab1 = ni_pci_6733(notebook,settings = {'device_name': 'ni_pci_6733_0', 'connection_table':connection_table})
    window.add_my_tab(tab1)
    window.show()
    def run():
        app.exec_()
        
    sys.exit(run())