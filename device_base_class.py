import logging
import sys
import time

from PySide.QtCore import *
from PySide.QtGui import *
from PySide.QtUiTools import QUiLoader

from tab_base_classes import Tab, Worker, define_state
from tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  
from hardware_interfaces.output_classes import AO, DO, DDS
from qtutils.widgets.toolpalette import ToolPaletteGroup


class DeviceTab(Tab):
    def __init__(self,notebook,settings,restart=False):
        Tab.__init__(self,notebook,settings,restart)
        self._connection_table = settings['connection_table']
        
        # Create the variables we need
        self._AO = {}
        self._DO = {}
        self._DDS = {}
        
        self._final_values = {}
        self._last_programmed_values = {}
        self._last_remote_values = {}
        self._primary_worker = None
        self._can_check_remote_values = False
        self._changed_radio_buttons = {}
        self.destroy_complete = False
        
        # Call the initialise GUI function
        self.initialise_GUI()        
        self.initialise_device()        
        self._last_programmed_values = self.get_front_panel_values()
        if self._can_check_remote_values:
            self.statemachine_timeout_add(30000,self.check_remote_values)
    
    def initialise_GUI(self):
        # Override this function
        # set the primary worker at this time
        pass
    
    @define_state(MODE_MANUAL,True)
    def initialise_device(self):
        yield(self.queue_work(self._primary_worker,'initialise'))
        
    @property
    def primary_worker(self):
        return self._primary_worker
        
    @primary_worker.setter
    def primary_worker(self,worker):
        self._primary_worker = worker
    
    def supports_remote_value_check(self,support):
        self._can_check_remote_values = bool(support)
    
    ############################################################
    # What do the properties dictionaries need to look like?   #
    ############################################################
    #
    # digital_properties = {'hardware_channel_reference':{}, 'do0':{}}
    #
    #
    # analog_properties = {'hardware_channel_reference':{'base_unit':'V',
    #                                                    'min':-10.0,
    #                                                    'max':10.0,
    #                                                    'step':0.01,
    #                                                    'decimals':3
    #                                                    },
    #                      'ao1':{'base_unit':'V',
    #                             'min':-10.0,
    #                             'max':10.0,
    #                             'step':0.01,
    #                             'decimals':3
    #                             },
    #                     }
    #
    #
    #    dds_properties = {'hardware_channel_reference':{'freq':{'base_unit':'Hz',
    #                                                            'min':-10.0,
    #                                                            'max':10.0,
    #                                                            'step':0.01,
    #                                                            'decimals':3
    #                                                            },
    #                                                     'amp':{'base_unit':'Vpp',
    #                                                            'min':0.0,
    #                                                            'max':1.0,
    #                                                            'step':0.1,
    #                                                            'decimals':3
    #                                                            },  
    #                                                   'phase':{'base_unit':'Degrees',
    #                                                            'min':0.0,
    #                                                            'max':360.0,
    #                                                            'step':1,
    #                                                            'decimals':2
    #                                                            },  
    #                                                    'gate':{},
    #                                                    },    
    #                      'dds1':{'freq':{'base_unit':'Hz',
    #                                      'min':-10.0,
    #                                      'max':10.0,
    #                                      'step':0.01,
    #                                      'decimals':3
    #                                      },
    #                               'amp':{'base_unit':'Vpp',
    #                                      'min':0.0,
    #                                      'max':1.0,
    #                                      'step':0.1,
    #                                      'decimals':3
    #                                      },  
    #                             'phase':{'base_unit':'Degrees',
    #                                      'min':0.0,
    #                                      'max':360.0,
    #                                      'step':1,
    #                                      'decimals':2
    #                                      }, 
    #                              'gate':{},
    #                             },
    #                     }
    #
    def create_digital_outputs(self,digital_properties):
        for hardware_name,properties in digital_properties.items():
            # Save the DO object
            self._DO[hardware_name] = self._create_DO_object(self.device_name,hardware_name,properties)
    
    def _create_DO_object(self,parent_device,hardware_name,properties):
        # Find the connection name
        device = self._connection_table.find_child(parent_device,hardware_name)
        connection_name = device.name if device else '-'
        
        # Instantiate the DO object
        return DO(hardware_name, connection_name, self.program_device, self.settings)
    
    def create_analog_outputs(self,analog_properties):
        for hardware_name,properties in analog_properties.items():                    
            # Create and save the AO object
            self._AO[hardware_name] = self._create_AO_object(self.device_name,hardware_name,properties)

    def _create_AO_object(self,parent_device,hardware_name,properties):
        # Find the connection name
        device = self._connection_table.find_child(parent_device,hardware_name)
        connection_name = device.name if device else '-'
        
        # Get the calibration details
        calib_class = None
        calib_params = {}
        if device:
            # get the AO from the connection table, find its calibration details
            calib_class = device.unit_conversion_class
            calib_params = eval(device.unit_conversion_params)
        
        # Instantiate the AO object
        return AO(hardware_name, connection_name, self.device_name, self.program_device, self.settings, calib_class, calib_params,
                properties['base_unit'], properties['min'], properties['max'], properties['step'], properties['decimals'])
            
    def create_dds_outputs(self,dds_properties):
        for hardware_name,properties in dds_properties.items():
            device = self._connection_table.find_child(self.device_name,hardware_name)
            connection_name = device.name if device else '-'
        
            subchnl_name_list = ['freq','amp','phase']
            sub_chnls = {}
            for subchnl in subchnl_name_list:
                if subchnl in properties:
                    # Create the AO object
                    sub_chnls[subchnl] = self._create_AO_object(hardware_name,hardware_name+'_'+subchnl,properties[subchnl])
            
            if 'gate' in properties:
                sub_chnls['gate'] = self._create_DO_object(hardware_name,hardware_name+'_gate',properties)
            
            self._DDS[hardware_name] = DDS(hardware_name,connection_name,sub_chnls)
        
    def create_digital_widgets(self,channel_properties):
        widgets = {}
        for hardware_name,properties in channel_properties.items():
            properties.setdefault('args',[])
            properties.setdefault('kwargs',{})
            if hardware_name in self._DO:
                widgets[hardware_name] = self._DO[hardware_name].create_widget(*properties['args'],**properties['kwargs'])
        
        return widgets
        
    def create_analog_widgets(self,channel_properties):
        widgets = {}
        for hardware_name,properties in channel_properties.items():
            properties.setdefault('display_name',None)
            properties.setdefault('horizontal_alignment',False)
            properties.setdefault('parent',None)
            if hardware_name in self._AO:
                widgets[hardware_name] = self._AO[hardware_name].create_widget(properties['display_name'],properties['horizontal_alignment'],properties['parent'])
        
        return widgets
        
    def create_dds_widgets(self,dds_properties):
        pass
    
    def auto_create_widgets(self):
        dds_properties = {}
        for channel,output in self._DDS.items():
            dds_properties[channel] = {}
        dds_widgets = self.create_dds_widgets(dds_properties)
        ao_properties = {}
        for channel,output in self._AO.items():
            ao_properties[channel] = {}
        ao_widgets = self.create_analog_widgets(ao_properties)
        do_properties = {}
        for channel,output in self._DO.items():
            do_properties[channel] = {}
        do_widgets = self.create_digital_widgets(do_properties)
        
        return dds_widgets,ao_widgets,do_widgets
    
    def auto_place_widgets(self,*args):
        widget = QWidget()
        toolpalettegroup = ToolPaletteGroup(widget)
        for arg in args:
            if type(arg) == type(()):
                # we have a name, use it!
                name = arg[0]
                widget_dict = arg[1]
            else:
                # ignore things that are not dictionaries or empty dictionaries
                if type(arg) != type({}) or len(arg.keys()) < 1:
                    continue
                if isinstance(self.get_channel(arg.keys()[0]),AO):
                    name = 'Analog Outputs'
                elif isinstance(self.get_channel(arg.keys()[0]),DO):
                    name = 'Digital Outputs'
                elif isinstance(self.get_channel(arg.keys()[0]),DDS):
                    name = 'DDS Outputs'
                else:
                    # If it isn't DO, DDS or AO, we should forget about them and move on to the next argument
                    continue
                widget_dict = arg
            # Create tool palette
            if toolpalettegroup.has_palette(name):
                toolpalette = toolpalettegroup.get_palette(name)
            else:
                toolpalette = toolpalettegroup.append_new_palette(name)
                
            for channel in sorted(widget_dict.keys()):
                toolpalette.addWidget(widget_dict[channel])
         
        # Add the widget containing the toolpalettegroup to the tab layout
        self.get_tab_layout().addWidget(widget)
        self.get_tab_layout().addItem(QSpacerItem(0,0,QSizePolicy.Minimum,QSizePolicy.MinimumExpanding))
                           
    def get_front_panel_values(self):
        return {channel:item.value for output in [self._AO,self._DO,self._DDS] for channel,item in output.items()}
    
    def get_channel(self,channel):
        if channel in self._AO:
            return self._AO[channel]
        elif channel in self._DO:
            return self._DO[channel]
        elif channel in self._DDS:
            return self._DDS[channel]
        else:
            return None
            
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)
    def destroy(self):
        yield(self.queue_work(self._primary_worker,'shutdown'))
        self.close_tab()
        self.destroy_complete = True
    
    # Only allow this to be called when we are in MODE_MANUAL and keep it queued up if we are not
    # When pulling out the state from the state queue, we check to see if there is an adjacent state that is more recent, and use that one
    # or whichever is the latest without encountering a different state).
    # This prevenets 'a million' calls to program_device from executing, potentially slowing down the system
    @define_state(MODE_MANUAL,True,delete_stale_states=True)
    def program_device(self):
        self._last_programmed_values = self.get_front_panel_values()
        
        # get rid of any "remote values changed" dialog
        self._changed_widget.hide()
        
        results = yield(self.queue_work(self._primary_worker,'program_manual',self._last_programmed_values))
        
        # If the worker process returns something, we assume it wants us to coerce the front panel values
        if results:
            for channel,remote_value in results.items():
                if channel not in self._last_programmed_values:
                    raise RuntimeError('The worker function program_manual for device %s is returning data for channel %s but the BLACS tab is not programmed to handle this channel'%(self.device_name,channel))
                
                output = self.get_channel(channel)
                if output is None:
                    raise RuntimeError('The channel %s on device %s is in the last programmed values, but is not in the AO, DO or DDS output store. Something has gone badly wrong!'%(channel,self.device_name))
                else:                    
                    # TODO: Only do this if the front panel values match what we asked to program (eg, the user hasn't changed the value since)
                    if output.value == self._last_programmed_values[channel]:
                        output.set_value(remote_value,program=False)
            
                        # Update the last_programmed_values            
                        self._last_programmed_values[channel] = remote_value
    
    @define_state(MODE_MANUAL,True)
    def check_remote_values(self):
        self._last_remote_values = yield(self.queue_work(self._primary_worker,'check_remote_values'))
        # compare to current front panel values and prompt the user if they don't match
        # We compare to the last_programmed values so that it doesn't get confused if the user has changed the value on the front panel
        # and the program_manual command is still queued up
        
        # If no results were returned, raise an exception so that we don't keep calling this function over and over again, 
        # filling up the text box with the same error, eventually consuming all CPU/memory of the PC
        if not self._last_remote_values or type(self._last_remote_values) != type({}):
            raise Exception('Failed to get remote values from device. Is it still connected?')
            
        # A variable to indicate if any of the channels have a changed value
        overall_changed = False
            
        # A place to store radio buttons in
        self._changed_radio_buttons = {}
            
        # We expect a dictionary of channel:value pairs
        for channel in sorted(self._last_remote_values):
            remote_value = self._last_remote_values[channel]
            if channel not in self._last_programmed_values:
                raise RuntimeError('The worker function check_remote_values for device %s is returning data for channel %s but the BLACS tab is not programmed to handle this channel'%(self.device_name,channel))
            
            # A variable to indicate if this channel has changed
            changed = False
            
            if channel in self._DDS:
                # This si a complicated case!
                #ui = QUiLoader().load('tab_value_changed_dds.ui')
                pass
            elif channel in self._DO:
                # This is an easy case!
                front_value = str(bool(int(self._last_programmed_values[channel])))
                remote_value = str(bool(int(remote_value)))
                if front_value != remote_value:
                    changed = True
                    ui = QUiLoader().load('tab_value_changed.ui')
                    ui.channel_label.setText(self._DO.name)
                    ui.front_value.setText(front_value)
                    ui.remote_value.setText(remote_value)
            elif channel in self._AO:
                # A intermediately complicated case!
                front_value = ("%."+str(self._AO[channel]._decimals)+"f")%self._last_programmed_values[channel]
                remote_value = ("%."+str(self._AO[channel]._decimals)+"f")%remote_value
                if front_value != remote_value:
                    changed = True
                    ui = QUiLoader().load('tab_value_changed.ui')
                    ui.channel_label.setText(self._AO.name)
                    ui.front_value.setText(front_value)
                    ui.remote_value.setText(remote_value)
            else:
                raise RuntimeError('device_base_class.py is not programmed to handle channel types other than DDS, AO and DO in check_remote_values')
                    
            if changed:
                overall_changed = True
            
                # Add the changed widget for this channel to a layout!
                self._ui.changed_layout.addWidget(ui)
                
                # save the radio buttons so that we can access their state later!
                self._changed_radio_buttons[channel] = ui.use_remote_values
                
        if overall_changed:
            # TODO: Disable all widgets for this device, including virtual device widgets...how do I do that?????
            # Probably need to add a disable/enable method to analog/digital/DDS widgets that disables the widget and is orthogonal to the lock/unlock system
            # Should probably set a tooltip on the widgets too explaining why they are disabled!
            # self._device_widget.setSensitive(False)
            # show the remote_values_change dialog
            self._changed_widget.show()
        
            # Add an "apply" button and link to on_resolve_value_inconsistency
            button = QButton("Apply")
            button.clicked.connect(self.on_resolve_value_inconsistency)
            self._ui.changed_layout.addWidget(button)
              
    def on_resolve_value_inconsistency(self):
        # get the values and update the device/front panel
        needs_programming = False
        for channel,radio in self._changed_radio_buttons.items():
            if radio.isChecked():
                output = self.get_channel(channel)
                if output is None:
                    raise RuntimeError('on_resolve_value_inconsistency is being asked to handle a channel that is not a DDS, AO or DO (channel: %s, device: %s)'%(channel,self.device_name))
                # The device already has this value, so no need to program it!
                output.set_value(self._last_remote_values[channel],program=False)
            else:
                # we only need to program the device if one or more channels is using the front panel value
                needs_programming = True
                
        if needs_programming:
            self.program_device()
            
        self._changed_widget.hide()
    
    @define_state(MODE_MANUAL,True)
    def transition_to_buffered(self,h5_file,notify_queue): 
        # Get rid of any "remote values changed" dialog
        self._changed_widget.hide()
    
        self.mode = MODE_TRANSITION_TO_BUFFERED
        # The final values of the run, to update the GUI with at the end of the run:
        self._final_values = yield(self.queue_work(self._primary_worker,'transition_to_buffered',h5_file,self.get_front_panel_values(),self._force_full_buffered_reprogram))
        
        # If we get None back, then the worker process did not finish properly
        if self._final_values is None:
            notify_queue.put([self.device_name,'fail'])
            self.abort_transition_to_buffered()
        else:
            # Tell the queue manager that we're done:
            self.mode = MODE_BUFFERED
            notify_queue.put([self.device_name,'success'])
       
    @define_state(MODE_TRANSITION_TO_BUFFERED,False)
    def abort_transition_to_buffered(self):
        abort_success = yield(self.queue_work(self._primary_worker,'abort_transition_to_buffered'))
        if abort:
            self.mode = MODE_MANUAL
            self.program_device()
        else:
            raise Exception('Could not abort transition_to_buffered. You must restart this device to continue')
        
    @define_state(MODE_BUFFERED,False)
    def abort_buffered(self,notify_queue):
        abort_success = yield(self.queue_work(self._primary_worker,'abort_buffered'))
        if abort_success:
            notify_queue.put([self.device_name,'success'])
            self.mode = MODE_MANUAL
            self.program_device()
        else:
            notify_queue.put([self.device_name,'fail'])
            raise Exception('Could not abort the buffered sequence. You must restart this device to continue')
            
    @define_state(MODE_BUFFERED,False)
    def transition_to_manual(self,notify_queue,program=True):
        self.mode = MODE_TRANSITION_TO_MANUAL
        
        success = yield(self.queue_work(self._primary_worker,'transition_to_manual'))
        
        # Update the GUI with the final values of the run:
        for channel, value in self._final_values.items():
            if channel in self._AO:
                self._AO[channel].set_value(value,program=False)
            elif channel in self._DO:
                self._DO[channel].set_value(value,program=False)
            elif channel in self._DDS:
                self._DDS[channel].set_value(value,program=False)
            
        if success:
            notify_queue.put([self.device_name,'success'])
            self.mode = MODE_MANUAL
        else:
            notify_queue.put([self.device_name,'fail'])
            raise Exception('Could not transition to manual. You must restart this device to continue')
            
        if program:
            self.program_device()

            
class DeviceWorker(Worker):
    def init(self):
        # You read correctly, this isn't __init__, it's init. It's the
        # first thing that will be called in the new process. You should
        # do imports here, define instance variables, that sort of thing. You
        # shouldn't import the hardware modules at the top of your file,
        # because then they will be imported in both the parent and
        # the child processes and wont be cleanly restarted when the subprocess
        # is restarted. Since we're inside a method call though, you'll
        # have to use global statements for the module imports, as shown
        # below. Either that or you can make them instance variables, ie:
        # import module; self.module = module. Up to you, I prefer
        # the former.
        global serial; import serial
    
    def initialise(self):
        pass
        
    def shutdown(self):
        pass
        
    def program_manual(self,front_panel_values):
        pass
        
    def check_remote_values(self):
        pass
        
    def transition_to_buffered(self,h5file,front_panel_values,refresh):
        pass
        
    def abort_transition_to_buffered(self):
        pass
        
    def abort_buffered(self):
        pass
        
    def transition_to_manual(self):
        pass
        
            
if __name__ == '__main__':
    import sys
    import logging.handlers
    # Setup logging:
    logger = logging.getLogger('BLACS')
    handler = logging.handlers.RotatingFileHandler('BLACS.log', maxBytes=1024**2, backupCount=0)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if sys.stdout.isatty():
        terminalhandler = logging.StreamHandler(sys.stdout)
        terminalhandler.setFormatter(formatter)
        terminalhandler.setLevel(logging.DEBUG)
        logger.addHandler(terminalhandler)
    else:
        sys.stdout = sys.stderr = open(os.devnull)
    logger.setLevel(logging.DEBUG)
    #excepthook.set_logger(logger)
    logger.info('\n\n===============starting===============\n')
            
if __name__ == '__main__':
    # Test case!
    
    from connections import ConnectionTable
    from qtutils.widgets.dragdroptab import DragDropTabWidget
    
    class MyTab(DeviceTab):
        
        def initialise_GUI(self):
            # Create Digital Output Objects
            do_prop = {}
            for i in range(32):
                do_prop['port0/line%d'%i] = {}
            self.create_digital_outputs(do_prop)
                
            # Create Analog Output objects
            ao_prop = {}
            for i in range(4):
                ao_prop['ao%d'%i] = {'base_unit':'V',
                                     'min':-10.0,
                                     'max':10.0,
                                     'step':0.01,
                                     'decimals':3
                                    }            
            self.create_analog_outputs(ao_prop)
            
            # Create widgets for output objects and auto place them in the UI
            # The * here unpacks the returned tuple into sequential arguments
            # this is equivalent to called a,b,c = self.auto_create_widgets(); self.auto_place_widgets(a,b,c)
            a,b,c = self.auto_create_widgets()
            self.auto_place_widgets(a,b,c)
            
            # Set the primary worker
            self.create_worker("my_worker_name",DeviceWorker,{})
            self.primary_worker = "my_worker_name"
    
    
    
    connection_table = ConnectionTable(r'example_connection_table.h5')
    
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
    
    tab1 = MyTab(notebook,settings = {'device_name': 'ni_pcie_6363_0', 'connection_table':connection_table})
    window.add_my_tab(tab1)
    window.show()
    def run():
        app.exec_()
        
    sys.exit(run())