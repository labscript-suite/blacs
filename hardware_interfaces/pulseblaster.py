from BLACS.tab_base_classes import Worker, define_state
from BLACS.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  

from BLACS.device_base_class import DeviceTab

class pulseblaster(DeviceTab):
    
    def initialise_GUI(self):
        # Capabilities
        self.base_units     = {'freq':'Hz',        'amp':'Vpp', 'phase':'Degrees'}
        self.base_min       = {'freq':0.3,         'amp':0.0,   'phase':0}
        self.base_max       = {'freq':150000000.0, 'amp':1.0,   'phase':360}
        self.base_step      = {'freq':1000000,     'amp':0.01,  'phase':1}
        self.base_decimals  = {'freq':1,           'amp':3,     'phase':3}
        self.num_DDS = 2
        self.num_DO = 12
        
        dds_prop = {}
        for i in range(self.num_DDS): # 2 is the number of DDS outputs on this device
            dds_prop['dds %d'%i] = {}
            for subchnl in ['freq', 'amp', 'phase']:
                dds_prop['dds %d'%i][subchnl] = {'base_unit':self.base_units[subchnl],
                                                 'min':self.base_min[subchnl],
                                                 'max':self.base_max[subchnl],
                                                 'step':self.base_step[subchnl],
                                                 'decimals':self.base_decimals[subchnl]
                                                }
            dds_prop['dds %d'%i]['gate'] = {}
        
        do_prop = {}
        for i in range(self.num_DO): # 12 is the maximum number of flags on this device (some only have 4 though)
            do_prop['flag %d'%i] = {}
        
        # Create the output objects    
        self.create_dds_outputs(dds_prop)        
        self.create_digital_outputs(do_prop)        
        # Create widgets for output objects
        dds_widgets,ao_widgets,do_widgets = self.auto_create_widgets()
        
        # Define the sort function for the digital outputs
        def sort(channel):
            flag = channel.replace('flag ','')
            flag = int(flag)
            return '%02d'%(flag)
        
        # and auto place the widgets in the UI
        self.auto_place_widgets(("DDS Outputs",dds_widgets),("Flags",do_widgets,sort))
        
        # Store the board number to be used
        self.board_number = int(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
        
        # Create and set the primary worker
        self.create_worker("main_worker",PulseblasterWorker,{'board_number':self.board_number})
        self.primary_worker = "main_worker"
        
        # Set the capabilities of this device
        self.supports_smart_programming(True) 
        
        ####
        #### TODO: FIX
        ####
        # Status monitor timout
        self.statemachine_timeout_add(2000, self.status_monitor)
        
        # Default values for status prior to the status monitor first running:
        self.status = {'stopped':False,'reset':False,'running':False, 'waiting':False}
        
        # Get status widgets
        # self.status_widgets = {'stopped_yes':self.builder.get_object('stopped_yes'),
                               # 'stopped_no':self.builder.get_object('stopped_no'),
                               # 'reset_yes':self.builder.get_object('reset_yes'),
                               # 'reset_no':self.builder.get_object('reset_no'),
                               # 'running_yes':self.builder.get_object('running_yes'),
                               # 'running_no':self.builder.get_object('running_no'),
                               # 'waiting_yes':self.builder.get_object('waiting_yes'),
                               # 'waiting_no':self.builder.get_object('waiting_no')}
        
        

   
    
    # This function gets the status of the Pulseblaster from the spinapi,
    # and updates the front panel widgets!
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def status_monitor(self,notify_queue=None):
        # When called with a queue, this function writes to the queue
        # when the pulseblaster is waiting. This indicates the end of
        # an experimental run.
        self.status, waits_pending = yield(self.queue_work(self._primary_worker,'check_status'))
        
        if notify_queue is not None and self.status['waiting'] and not waits_pending:
            # Experiment is over. Tell the queue manager about it, then
            # set the status checking timeout back to every 2 seconds
            # with no queue.
            notify_queue.put('done')
            self.statemachine_timeout_remove(self.status_monitor)
            self.statemachine_timeout_add(2000,self.status_monitor)
        
        # TODO: Update widgets
        # a = ['stopped','reset','running','waiting']
        # for name in a:
            # if self.status[name] == True:
                # self.status_widgets[name+'_no'].hide()
                # self.status_widgets[name+'_yes'].show()
            # else:                
                # self.status_widgets[name+'_no'].show()
                # self.status_widgets[name+'_yes'].hide()
        
    
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def start(self,widget=None):
        yield(self.queue_work(self._primary_worker,'pb_start'))
        self.status_monitor()
        
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def stop(self,widget=None):
        yield(self.queue_work(self._primary_worker,'pb_stop'))
        self.status_monitor()
        
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def reset(self,widget=None):
        yield(self.queue_work(self._primary_worker,'pb_reset'))
        self.status_monitor()
    
    @define_state(MODE_BUFFERED,True)  
    def start_run(self, notify_queue):
        """Starts the Pulseblaster, notifying the queue manager when
        the run is over"""
        self.statemachine_timeout_remove(self.status_monitor)
        self.start()
        self.statemachine_timeout_add(1,self.status_monitor,notify_queue)
        
class PulseblasterWorker(Worker):
    def initialise(self):
        exec 'from spinapi import *' in globals()
        global h5py; import h5_lock, h5py
        global subproc_utils; import subproc_utils
        
        self.pb_start = pb_start
        self.pb_stop = pb_stop
        self.pb_reset = pb_reset
        self.pb_close = pb_close
        self.pb_read_status = pb_read_status
        self.smart_cache = {'amps0':None,'freqs0':None,'phases0':None,
                            'amps1':None,'freqs1':None,'phases1':None,
                            'pulse_program':None,'ready_to_go':False,
                            'initial_values':None}
                            
        # An event for checking when all waits (if any) have completed, so that
        # we can tell the difference between a wait and the end of an experiment.
        # The wait monitor device is expected to post such events, which we'll wait on:
        self.all_waits_finished = subproc_utils.Event('all_waits_finished')
        self.waits_pending = False
    
        pb_select_board(self.board_number)
        pb_init()
        pb_core_clock(75)
        self.initialised = True

    def program_manual(self,values):
        # Program the DDS registers:
        for i in range(2):
            pb_select_dds(i)
            # Program the frequency, amplitude and phase into their
            # zeroth registers:
            program_amp_regs(values['dds %d'%i]['amp'])
            program_freq_regs(values['dds %d'%i]['freq']/10.0**6) # method expects MHz
            program_phase_regs(values['dds %d'%i]['phase'])

        # create flags string
        # NOTE: The spinapi can take a string or integer for flags.
                # If it is a string: 
                #     flag: 0          12
                #          '101100011111'
                #
                # If it is a binary number:
                #     flag:12          0
                #         0b111110001101
                #
                # Be warned!
        flags = ''
        for i in range(12):
            if values['flag %d'%i]:
                flags += '1'
            else:
                flags += '0'
            
        # Write the first two lines of the pulse program:
        pb_start_programming(PULSE_PROGRAM)
        # Line zero is a wait:
        pb_inst_dds2(0,0,0,values['dds 0']['gate'],0,0,0,0,values['dds 1']['gate'],0,flags, WAIT, 0, 100)
        # Line one is a brach to line 0:
        pb_inst_dds2(0,0,0,values['dds 0']['gate'],0,0,0,0,values['dds 1']['gate'],0,flags, BRANCH, 0, 100)
        pb_stop_programming()
        
        # Now we're waiting on line zero, so when we start() we'll go to
        # line one, then brach back to zero, completing the static update:
        pb_start()
        
        # The pulse program now has a branch in line one, and so can't proceed to the pulse program
        # without a reprogramming of the first two lines:
        self.smart_cache['ready_to_go'] = False
        
        # TODO: return coerced/quantised values
        return {}
        
    def transition_to_buffered(self,device_name,h5file,initial_values,fresh):
        self.h5file = h5file
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices/%s'%device_name]
            # Program the DDS registers:
            ampregs = []
            freqregs = []
            phaseregs = []
            for i in range(2):
                amps = group['DDS%d/AMP_REGS'%i][:]
                freqs = group['DDS%d/FREQ_REGS'%i][:]
                phases = group['DDS%d/PHASE_REGS'%i][:]
                
                amps[0] = initial_values['dds %d'%i]['amp']
                freqs[0] = initial_values['dds %d'%i]['freq']/10.0**6 # had better be in MHz!
                phases[0] = initial_values['dds %d'%i]['phase']
                
                pb_select_dds(i)
                # Only reprogram each thing if there's been a change:
                if fresh or len(amps) != len(self.smart_cache['amps%d'%i]) or (amps != self.smart_cache['amps%d'%i]).any():   
                    self.smart_cache['amps%d'%i] = amps
                    program_amp_regs(*amps)
                if fresh or len(freqs) != len(self.smart_cache['freqs%d'%i]) or (freqs != self.smart_cache['freqs%d'%i]).any():
                    self.smart_cache['freqs%d'%i] = freqs
                    program_freq_regs(*freqs)
                if fresh or len(phases) != len(self.smart_cache['phases%d'%i]) or (phases != self.smart_cache['phases%d'%i]).any():      
                    self.smart_cache['phases%d'%i] = phases
                    program_phase_regs(*phases)
                
                ampregs.append(amps)
                freqregs.append(freqs)
                phaseregs.append(phases)
                
            # Now for the pulse program:
            pulse_program = group['PULSE_PROGRAM'][2:]
            
            #Let's get the final state of the pulseblaster. z's are the args we don't need:
            freqreg0,phasereg0,ampreg0,en0,z,freqreg1,phasereg1,ampreg1,en1,z,flags,z,z,z = pulse_program[-1]
            finalfreq0 = freqregs[0][freqreg0]*10.0**6 # Front panel expects frequency in Hz
            finalfreq1 = freqregs[1][freqreg1]*10.0**6 # Front panel expects frequency in Hz
            finalamp0 = ampregs[0][ampreg0]
            finalamp1 = ampregs[1][ampreg1]
            finalphase0 = phaseregs[0][phasereg0]
            finalphase1 = phaseregs[1][phasereg1]

            if fresh or (self.smart_cache['initial_values'] != initial_values) or \
            (len(self.smart_cache['pulse_program']) != len(pulse_program)) or \
            (self.smart_cache['pulse_program'] != pulse_program).any() or \
            not self.smart_cache['ready_to_go']:
            
                self.smart_cache['ready_to_go'] = True
                self.smart_cache['initial_values'] = initial_values
                pb_start_programming(PULSE_PROGRAM)
                # Line zero is a wait on the final state of the program:
                pb_inst_dds2(freqreg0,phasereg0,ampreg0,en0,0,freqreg1,phasereg1,ampreg1,en1,0,flags,WAIT,0,100)
                
                # create initial flags string
                # NOTE: The spinapi can take a string or integer for flags.
                # If it is a string: 
                #     flag: 0          12
                #          '101100011111'
                #
                # If it is a binary number:
                #     flag:12          0
                #         0b111110001101
                #
                # Be warned!
                initial_flags = ''
                for i in range(12):
                    if initial_values['flag %d'%i]:
                        initial_flags += '1'
                    else:
                        initial_flags += '0'
                # Line one is a continue with the current front panel values:
                pb_inst_dds2(0,0,0,initial_values['dds 0']['gate'],0,0,0,0,initial_values['dds 1']['gate'],0,initial_flags, CONTINUE, 0, 100)
                # Now the rest of the program:
                if fresh or len(self.smart_cache['pulse_program']) != len(pulse_program) or \
                (self.smart_cache['pulse_program'] != pulse_program).any():
                    self.smart_cache['pulse_program'] = pulse_program
                    for args in pulse_program:
                        pb_inst_dds2(*args)
                pb_stop_programming()
            
            # Are there waits in use in this experiment? The monitor waiting for the end of
            # the experiment will need to know:
            self.waits_pending =  bool(len(hdf5_file['waits']))
            
            # Now we build a dictionary of the final state to send back to the GUI:
            return_values = {'dds 0':{'freq':finalfreq0, 'amp':finalamp0, 'phase':finalphase0, 'gate':en0},
                             'dds 1':{'freq':finalfreq1, 'amp':finalamp1, 'phase':finalphase1, 'gate':en1},
                            }
            # Since we are converting from an integer to a binary string, we need to reverse the string! (see notes above when we create flags variables)
            return_flags = bin(flags)[2:].rjust(12,'0')[::-1]
            for i in range(12):
                return_values['flag %d'%i] = return_flags[i]
                
            return return_values
            
    def check_status(self):
        if not hasattr(self, 'initialised'):
            # Return Dummy status
            return {'stopped':False,'reset':False,'running':False, 'waiting':False}, False
        
        if self.waits_pending:
            try:
                self.all_waits_finished.wait(self.h5file, timeout=0)
                self.waits_pending = False
            except subproc_utils.TimeoutError:
                pass
        return pb_read_status(), self.waits_pending

    def transition_to_manual(self):
        status, waits_pending = self.check_status()
        if status['waiting'] and not waits_pending:
            return True
        else:
            return False
     
    def abort_buffered(self):
        #TODO: Implement this
        pass
        
    def abort_transition_to_buffered(self):
        #TODO: implement this
        pass
        
    def shutdown(self):
        #TODO: implement this
        pass
        
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
    tab1 = pulseblaster(notebook,settings = {'device_name': 'pulseblaster_0', 'connection_table':connection_table})
    window.add_my_tab(tab1)
    window.show()
    def run():
        app.exec_()
        
    sys.exit(run())