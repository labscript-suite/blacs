from time import time

from BLACS.tab_base_classes import Worker, define_state
from BLACS.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  
from BLACS.device_base_class import DeviceTab
from PySide.QtUiTools import QUiLoader
import os

class phasematrixquicksyn(DeviceTab):
    def initialise_GUI(self):
        # Create DDS Output objects
        dds_prop = {'dds 0':{'freq':{'base_unit':   'Hz',
                                     'min':         0.5e9,
                                     'max':         10e9,
                                     'step':        1e6,
                                     'decimals':    3},
                             'gate':{}
                                 }
                                 }

       
        # Create the output objects    
        self.create_dds_outputs(dds_prop)        
        # Create widgets for output objects
        dds_widgets,ao_widgets,do_widgets = self.auto_create_widgets()
        # and auto place the widgets in the UI
        self.auto_place_widgets(("DDS Outputs",dds_widgets))
        
        self.status_ui = QUiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'phasematrixquicksyn.ui'))
        self.get_tab_layout().addWidget(self.status_ui)
        self.status_ui.ref_button.clicked.connect(self.update_reference_out)
        self.status_ui.blanking_button.clicked.connect(self.update_blanking)
        self.status_ui.lock_recovery_button.clicked.connect(self.update_lock_recovery)
        
        
        # Store the COM port to be used
        self.address = str(self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection)
        
        # Create and set the primary worker
        self.create_worker("main_worker",QuickSynWorker,{'address':self.address})
        self.primary_worker = "main_worker"

        # Set the capabilities of this device
        self.supports_remote_value_check(True)
        self.supports_smart_programming(False) 
        self.statemachine_timeout_add(2000, self.status_monitor)
        
        
        

    
    # This function gets the status of the phasematrix,
    # and updates the front panel widgets!
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def status_monitor(self):
        # When called with a queue, this function writes to the queue
        # when the pulseblaster is waiting. This indicates the end of
        # an experimental run.
        self.status = yield(self.queue_work(self._primary_worker,'check_status'))
        #TODO: update some widgets to reflect the current state
        self.status_ui.temperature_label.setText(str(self.status['temperature']))
        
        if self.status['freqlock']:
            self.status_ui.freq_lock_label.setText('locked')
        else:
            self.status_ui.freq_lock_label.setText('unlocked')
            
        if self.status['reflock'] and self.status['ref']:
            self.status_ui.ref_lock_label.setText('locked')
        elif self.status['ref']:
            self.status_ui.ref_lock_label.setText('unlocked')
        else:
            self.status_ui.ref_lock_label.setText('disconnected')
            
            
        self.status_ui.ref_button.setChecked(self.status['ref_output'])
        self.status_ui.blanking_button.setChecked(self.status['blanking'])
        self.status_ui.lock_recovery_button.setChecked(self.status['lock_recovery'])
        
        
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True,True)
    def update_reference_out(self):
        value = self.status_ui.ref_button.isChecked()
        yield(self.queue_work(self._primary_worker,'update_reference_out',value))
        
    
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True,True)
    def update_blanking(self):
        value = self.status_ui.blanking_button.isChecked()
        yield(self.queue_work(self._primary_worker,'update_blanking',value))
        
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True,True)
    def update_lock_recovery(self):
        value = self.status_ui.lock_recovery_button.isChecked()
        print value
        yield(self.queue_work(self._primary_worker,'update_lock_recovery',value))
       

class QuickSynWorker(Worker):
    def initialise(self):
        global serial; import serial
        global h5py; import h5_lock, h5py
        global time; import time
    
        baud_rate=115200
        port = self.address
        self.connection = serial.Serial(port, baudrate = baud_rate, timeout=0.1)
        self.connection.readlines()
        
        #check to see if the reference is set to external. If not, make it so! (should we ask the user about this?)
        self.connection.write('ROSC:SOUR?\r')
        response = self.connection.readline()
        if response == 'INT\n':
            #ref was set to internal, let's change it to ext
            self.connection.write('ROSC:SOUR EXT\r')
    
    def check_remote_values(self):
        # Get the currently output values:

        results = {'dds 0':{}}
        line = ''
        count = 0


        self.connection.write('FREQ?\r')
        line = self.connection.readline()

        if line == '':
            #try again
            line = self.connection.readline()
            if line == '':
                raise Exception("Device didn't say what its frequncy was :(")
            
        # Convert mHz to Hz:
        results['dds 0']['freq'] = float(line)/1000

        # wait a little while first, it doesn't like being asked things too quickly!
        time.sleep(0.05)
        self.connection.write('OUTP:STAT?\r')
        line = self.connection.readline()
        if line == '':
            raise Exception("Device didn't say what its status was :(")
        time.sleep(0.05)    
            

        #get the gate status
        results['dds 0']['gate'] = 0 if line == 'OFF\n' else 1


        return results
    
    def check_status(self):
        if not hasattr(self,'connection'):
            # dummy status:
            return {'ref':0, 'freqlock':0, 'reflock':0, 'ref_output':0, 'blanking':0, 'lock_recovery':0, 'temperature':0}
            
        results = {}
        line = ''
        self.connection.write('STAT?\r')
        line = self.connection.readline()
        if line == '':
            raise Exception("Device didn't say what its status was :(")
        time.sleep(0.05)    
            
        
        #get the status and convert to binary, and take off the '0b' header:
        status = bin(int(line,16))[2:]
        # if the status is less than 8 bits long, pad the start with zeros!
        while len(status)<8:
            status = '0'+status
        # byte 0 is the 1 for an external ref, 0 for no external ref
        results['ref'] = int(status[-1])
        # byte 1 is high for rf unlocked, low for rf locked. This is silly, let's reverse it!
        results['freqlock'] = int(not int(status[-2]))
        # byte 2 is the high for ref unlocked, low for ref locked. Again, let's swap this!
        results['reflock'] = int(not int(status[-3]))
        # byte 3 tells us if the output is on or off,  we don't care since the check values function deals with this
        
        
        # byte 4 will go high if there is a voltage error.
        #In this case, we probably just want to raise an exception to get the user's attention
        if int(status[-5]):
            self.logger.critical('Device is reporting voltage error')
            raise Exception('Voltage error')
        # byte 5 tells us if the internal reference is being output
        results['ref_output'] = int(status[-6])
        # byte 6 tells us if blanking is on (i.e. turning off output while it changes frequency)
        results['blanking'] = int(status[-7])
        # byte 7 tells us if lock recovery is on,
        
        results['lock_recovery'] = int(status[-8])
        
        # now let's check it's temperature!
        self.connection.write('DIAG:MEAS? 21\r')
        results['temperature'] = float(self.connection.readline())
        
        # check if the temperature is bad, if it is, raise an exception. Hopefully one day this will be sent to syslog,
        #at which point we'll add some extra magic to segregate into warning and critical temperatures.
        
        if results['temperature'] > 50.0:
            raise Exception('WARNING: Temperature is too high! Temperature is %s'%results['temperature'])
            return results
        
        return results
    
    def program_manual(self,front_panel_values):
        freq = front_panel_values['dds 0']['freq']
        #program in millihertz:
        freq*=1e3
        command = 'FREQ %i\r'%freq
        self.connection.write(command)
        
        # add some sleep time here since the phasematrix gets grumpy
        time.sleep(0.05)
        
        
        gate = front_panel_values['dds 0']['gate']
        command = 'OUTP:STAT %i\r'%gate
        self.connection.write(command)
        
        return self.check_remote_values()
        
        
    def update_reference_out(self,value):
        pass
        
    def update_blanking(self,value):
        pass
        
    def update_lock_recovery(self,value):
        pass
    
    def transition_to_buffered(self,device_name,h5file,initial_values,fresh):
        # Store the initial values in case we have to abort and restore them:
        self.initial_values = initial_values
        # Store the final values to for use during transition_to_static:
        self.final_values = {}
        with h5py.File(h5file) as hdf5_file:
            group = hdf5_file['/devices/'+device_name]
            # If there are values to set the unbuffered outputs to, set them now:
            if 'STATIC_DATA' in group:
                data = group['STATIC_DATA'][:][0]
                
        self.connection.write('FREQ %i\r'%(data['freq0']))
        time.sleep(0.05)
        self.connection.write('OUTP:STAT 1')#%i'%(data['gate0']))
        
        
        # Save these values into final_values so the GUI can
        # be updated at the end of the run to reflect them:
        final_values = {'dds 0':{}}
        
        final_values['dds 0']['freq'] = data['freq0']/1e3
        final_values['dds 0']['gate'] = 1#data['gate0']
                
        return final_values
        
    def abort_transition_to_buffered(self):
        return self.transition_to_manual(True)
        
    def abort_buffered(self):
        return self.transition_to_manual(True)
    

    
    def transition_to_manual(self,abort = False):
        if abort:
            # If we're aborting the run, reset to original value
            self.program_manual(self.initial_values)
        # If we're not aborting the run, stick with buffered value. Nothing to do really!
        # return the current values in the device
        return True
        
    def shutdown(self):
        self.connection.close()

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
    tab1 = phasematrixquicksyn(notebook,settings = {'device_name': 'phasematrix_0', 'connection_table':connection_table})
    window.add_my_tab(tab1)
    window.show()
    def run():
        app.exec_()
        
    sys.exit(run())
