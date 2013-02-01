import sys

from PySide.QtCore import *
from PySide.QtGui import *

from tab_base_classes import Tab, Worker, define_state
from tab_base_classes import STATE_MANUAL, STATE_TRANSITION_TO_BUFFERED, STATE_TRANSITION_TO_MANUAL, STATE_BUFFERED  
from output_classes import AO, DO, DDS
from qtutils.widgets.toolpalette import ToolPaletteGroup

class DeviceTab(Tab):
    def __init__(self,notebook,settings,restart=False):
        Tab.__init__(self,notebook,settings,restart)
        self._settings = settings
        self._device_name = settings['device_name']
        self._connection_table = settings['connection_table']
        
        # Create the variables we need
        self._AO = {}
        self._DO = {}
        self._DDS = {}
        
        self._final_values = {}
        self._primary_worker = None
        
        # Call the initialise GUI function
        self.initialise_GUI()
        self.initialise_device()
        
    
    def initialise_GUI(self):
        # Override this function
        # set the primary worker at this time
        pass
        
    @property
    def primary_worker(self):
        return self._primary_worker
        
    @primary_worker.setter
    def primary_worker(self,worker):
        self._primary_worker = worker
            
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
            self._DO[hardware_name] = self._create_DO_object(self._device_name,hardware_name,properties)
    
    def _create_DO_object(self,parent_device,hardware_name,properties):
        # Find the connection name
        device = self._connection_table.find_child(parent_device,hardware_name)
        connection_name = device.name if device else '-'
        
        # Instantiate the DO object
        return DO(hardware_name, connection_name, self.program_device, self._settings)
    
    def create_analog_outputs(self,analog_properties):
        for hardware_name,properties in analog_properties.items():                    
            # Create and save the AO object
            self._AO[hardware_name] = self._create_AO_object(self._device_name,hardware_name,properties)

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
        return AO(hardware_name, connection_name, self._device_name, self.program_device, self._settings, calib_class, calib_params,
                properties['base_unit'], properties['min'], properties['max'], properties['step'], properties['decimals'])
            
    def create_dds_outputs(self,dds_properties):
        for hardware_name,properties in dds_properties.items():
            subchnl_name_list = ['freq','amp','phase']
            sub_chnls = {}
            for subchnl in subchnl_name_list:
                if subchnl in properties:
                    # Create the AO object
                    sub_chnls[subchnl] = self._create_AO_object(hardware_name,hardware_name+'_'+subchnl,properties[subchnl])
            
            if 'gate' in properties:
                sub_chnls['gate'] = self._create_DO_object(hardware_name,hardware_name+'_gate',properties)
            
            self._DDS[hardware_name] = DDS(sub_chnls)
        
    def create_digital_widgets(self,channel_properties):
        widgets = {}
        for hardware_name,properties in channel_properties.items():
            properties.setdefault('args',[])
            properties.setdefault('kwargs',{})
            if hardware_name in self._DO:
                widgets[hardware_name] = self._DO[hardware_name].create_widget(properties['args'],properties['kwargs'])
        
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
        for arg in *args:
            if type(arg) == type(()):
                # we have a name, use it!
                name = arg[0]
                widget_dict = arg[1]
            else:
                # ignore things that are not dictionaries or empty dictionaries
                if if type(arg) != type({}) or len(arg.keys()) < 1:
                    continue
                if type(arg[arg.keys()[0]]) == type(AO):
                    name = 'Analog Outputs'
                elif type(arg[arg.keys()[0]]) == type(DO):
                    name = 'Digital Outputs'
                elif type(arg[arg.keys()[0]]) == type(DDS):
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
                toolpalette.addWidget(widget_dict[key])
            
        # Add the widget containing the toolpalettegroup to the tab layout
        self.get_tab_layout().addWidget(widget)
                           
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
            
    @define_state(STATE_MANUAL|STATE_BUFFERED|STATE_TRANSITION_TO_BUFFERED|STATE_TRANSITION_TO_MANUAL,True)
    def destroy(self):
        self.queue_work('shutdown')
        self.destroy_complete = True
        self.close_tab()
    
    # Only allow this to be called when we are in STATE_MANUAL and keep it queued up if we are not
    @define_state(STATE_MANUAL,True)
    def program_device(self):
        yield(self.queue_work(self._primary_worker,'program_manual',self.get_front_panel_values()))
        
    @define_state(STATE_MANUAL,True)
    def transition_to_buffered(self,h5_file,notify_queue): 
        self.mode = STATE_TRANSITION_TO_BUFFERED
        # The final values of the run, to update the GUI with at the end of the run:
        self._final_values = yield(self.queue_work(self._primary_worker,'transition_to_buffered',self.get_front_panel_values(),self._force_full_buffered_reprogram))
        
        # If we get None back, then the worker process did not finish properly
        if self._final_values = None:
            notify_queue.put([self.device_name,'fail'])
            self.abort_transition_to_buffered()
        else:
            # Tell the queue manager that we're done:
            self.mode = STATE_BUFFERED
            notify_queue.put([self.device_name,'success'])
       
    @define_state(STATE_TRANSITION_TO_BUFFERED,False)
    def abort_transition_to_buffered(self):
        abort_success = yield(self.queue_work(self._primary_worker,'abort_transition_to_buffered'))
        if abort:
            self.mode = STATE_MANUAL
            self.program_device()
        else:
            raise Exception('Could not abort transition_to_buffered. You must restart this device to continue')
        
    @define_state(STATE_BUFFERED,False)
    def abort_buffered(self,notify_queue):
        abort_success = yield(self.queue_work(self._primary_worker,'abort_buffered'))
        if abort_success:
            notify_queue.put([self.device_name,'success'])
            self.mode = STATE_MANUAL
            self.program_device()
        else:
            notify_queue.put([self.device_name,'fail'])
            raise Exception('Could not abort the buffered sequence. You must restart this device to continue')
            
    @define_state(STATE_BUFFERED,False)
    def transition_to_manual(self,notify_queue,program=True):
        self.mode = STATE_TRANSITION_TO_MANUAL
        
        success = yield(self.queue_work(self._primary_worker,'transition_to_static'))
        
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
            self.mode = STATE_MANUAL
        else:
            notify_queue.put([self.device_name,'fail'])
            raise Exception('Could not transition to manual. You must restart this device to continue')
            
        if program:
            self.program_device()
    