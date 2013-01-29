import logging
import math

from PySide.QtCore import *
from PySide.QtGui import *

from qtutils.widgets.analogoutput import AnalogOutput
from qtutils.widgets.digitaloutput import DigitalOutput
from unitconversions import *


class AO(object):
    def __init__(self, hardware_name, connection_name, device_name, program_function, settings, calib_class, calib_params, default_units, min, max, step, decimals):
        self._connection_name = connection_name
        self._hardware_name = hardware_name
        self._device_name = device_name
        
        self._locked = False
        self._comboboxmodel = QStandardItemModel()
        self._widgets = []
        self._current_units = default_units
        self._base_unit = default_units
        self._program_device = program_function
        
        # All of these are in base units ALWAYS
        self._current_value = 0
        self._current_step_size = step
        self._limits = [min,max]
        self._decimals = decimals
                
        self._logger = logging.getLogger('BLACS.%s.%s'%(self._device_name,hardware_name)) 
        
        # Initialise Calibrations
        if calib_class is not None:
            if calib_class not in globals() or not isinstance(calib_params,dict) or globals()[calib_class].base_unit != default_units:
                # log an error:  
                reason = ''
                if calib_class not in globals():
                    reason = 'The unit conversion class was not imported. Is it in the correct folder? Is it imported when you call "from unitconversions import *" from a python terminal?'
                elif not isinstance(calib_params,dict):
                    reason = 'The parameters for the unit conversion class are not a dictionary. Check your connection table code for errors and recompile it'
                elif globals()[calib_class].base_unit != default_units:
                    reason = 'The base unit of your unit conversion class does not match this hardware channel. The hardware channel has base units %s while your unit conversion class uses %s'%(globals()[calib_class].base_unit,default_units)
                self._logger.error('The unit conversion class (%s) could not be loaded. Reason: %s'%(calib_class,reason))   
                # Use default units
                self._calibration = None
                self._comboboxmodel.appendRow(QStandardItem(self._base_unit))
            else:
                # initialise calibration class
                self._calibration = globals()[calib_class](calib_params)    
                self._comboboxmodel.appendRow(QStandardItem(self._base_unit))
                        
                for unit in self._calibration.derived_units:
                    self._comboboxmodel.appendRow(QStandardItem(unit))
                    
        else:
            # use default units
            self._calibration = None
            self._comboboxmodel.appendRow(QStandardItem(self._base_unit))
        
        self._update_from_settings(settings)
    
    def _update_from_settings(self,settings):
        # Build up the settings dictionary if it isn't already
        if not isinstance(settings,dict):
            settings = {}
        if 'front_panel_settings' not in settings or not isinstance(settings['front_panel_settings'],dict):
            settings['front_panel_settings'] = {}
        if self._hardware_name not in settings['front_panel_settings'] or not isinstance(settings['front_panel_settings'][self._hardware_name],dict):
            settings['front_panel_settings'][self._hardware_name] = {}
        # Set default values if they are not already saved in the settings dictionary
        if 'base_value' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['base_value'] = False
        if 'locked' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['locked'] = False
        if 'base_step_size' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['base_step_size'] = self._current_step_size
        if 'current_units' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['current_units'] = self._base_unit
    
        # only keep a reference to the part of the settings dictionary relevant to this DO
        self._settings = settings['front_panel_settings'][self._hardware_name]
    
        # Update the state of the button
        self.set_value(self._settings['base_value'],program=False)

        # Update the lock state
        self._update_lock(self._settings['locked'])
        
        # Update the step size
        self.set_step_size(self._settings['base_step_size'],self._base_unit)
    
        # Update the unit selection
        self.change_unit(self._settings['current_units'])
     
    def convert_value_to_base(self, value, unit):
        if self._calibration and unit in self._calibration.derived_units:
            return getattr(self._calibration,unit+"_to_base")(value)
         
        # TODO: include device name somehow, and also the calibration class name
        raise RuntimeError('The value %s (%s) could not be converted to base units because the hardware channel %s, named %s, either does not have a unit conversion class or the unit specified was invalid'%(str(value),unit,self._hardware_name,self._name))
    
    def convert_value_from_base(self, value, unit):  
        if self._calibration and unit in self._calibration.derived_units:
            getattr(self._calibration,unit+"_from_base")(value)
    
        # TODO: include device name somehow, and also the calibration class name
        raise RuntimeError('The value %s (%s) could not be converted to base units because the hardware channel %s, named %s, either does not have a unit conversion class or the unit specified was invalid'%(str(value),unit,self._hardware_name,self._name))
    
    # handles the conversion of a range centered on value in units to base units
    # In other words, how big is "range" in base units assuming that you care about what range is
    # between value-range/2 and value+range/2
    #
    # If value+range/2 or value-range/2 is outside of the limits, then we will shift the fraction of range
    # used on the offending side of value
    # If range is greater than the difference of the limits, we will return the difference between the limits
    def convert_range_to_base(self,value,range,unit):
        # Do we need to convert the limits?
        if unit != self._base_unit:
            limits = [self.convert_value_from_base(self._limits[0],unit),self.convert_value_from_base(self._limits[1],unit)]
            if limits[0] > limits[1]:
                limits[0],limits[1] = limits[1],limits[0]
        else:
            limits = self._limits
        
        # limits are now in the units given to the function!
        # (As are range and value)
            
        # If range is bigger than the difference of the limits, return the difference of the limits
        # in base units
        if range >= abs(limits[0]-limits[1]):
            limits = [self.convert_value_to_base(limits[0],unit),self.convert_value_to_base(limits[1],unit)]
            return abs(limits[0]-limits[1])
          
        # At this point, the range must fit inside the limits, so if we find we are out of bounds on one side, 
        # we can be certain shifting the fractions will not cause us to go out of bounds on the other side
        positive_fraction = range/2.0
        negative_fraction = range/2.0
        # If the value+range/2 is greater than the upper limit, shift the fraction 
        if value+positive_fraction > self._limits[1]:
            positive_fraction = abs(self._limits[1]-value)
            negative_fraction = abs(range-positive_fraction)
        # Similarly if value-range/2 is less than the lower limit, shift the fraction
        elif value-negative_fraction < self._limits[0]:    
            negative_fraction = abs(self._limits[0]-value)        
            positive_fraction = abs(range-negative_fraction)
        
        # Now do the conversion!
        bound1 = self.convert_value_to_base(value+positive_fraction,unit)
        bound2 = self.convert_value_to_base(value-negative_fraction,unit)
        
        return abs(bound1-bound2)
    
    # This does the reverse of teh above function, with the same rules
    def convert_range_from_base(self,value,range,unit):
        # limits are always in base units
        limits = self._limits
        
        # limits are now in base units!
        # (As are range and value)
            
        # If range is bigger than the difference of the limits, return the difference of the limits
        # in the specified units units
        if range >= abs(limits[0]-limits[1]):
            limits = [self.convert_value_from_base(limits[0],unit),self.convert_value_from_base(limits[1],unit)]
            return abs(limits[0]-limits[1])
          
        # At this point, the range must fit inside the limits, so if we find we are out of bounds on one side, 
        # we can be certain shifting the fractions will not cause us to go out of bounds on the other side
        positive_fraction = range/2.0
        negative_fraction = range/2.0
        # If the value+range/2 is greater than the upper limit, shift the fraction 
        if value+positive_fraction > self._limits[1]:
            positive_fraction = abs(self._limits[1]-value)
            negative_fraction = abs(range-positive_fraction)
        # Similarly if value-range/2 is less than the lower limit, shift the fraction
        elif value-negative_fraction < self._limits[0]:    
            negative_fraction = abs(self._limits[0]-value)        
            positive_fraction = abs(range-negative_fraction)
        
        # Now do the conversion!
        bound1 = self.convert_value_from_base(value+positive_fraction,unit)
        bound2 = self.convert_value_from_base(value-negative_fraction,unit)
        
        return abs(bound1-bound2)

    def create_widget(self,display_name=None, horizontal_alignment=False, parent=None):
        widget = AnalogOutput(self._hardware_name,self_connection_name,display_name, horizontal_alignment, parent)
        self.add_widget(widget)
        return widget
        
    def add_widget(self, widget):
        if widget in self._widgets:
            return
            
        self._widgets.append(widget)
    
        # make sure the widget knows about this AO. 
        widget.set_AO(self,notify_old_AO=True,notify_new_AO=False)
        
        # Now connect this widgets signal to the AO slot
        widget.connect_value_change(self.set_value)
        
        # set the properties of the widgets...
        # set comboboxmodel
        widget.set_combobox_model(self._comboboxmodel)
        # This will set the min/max/value/num.decimals/stepsie and current_unit of ALL widgets
        # including the one just added!
        self.change_unit(self._current_units)
        # This will update the lock state of ALL widgets, including the one just added!
        self._update_lock(self._locked)
    
    # If calling this method directly from outside the set_AO function in the analog widget
    # you should NOT specify a value for new_AO.
    def remove_widget(self,widget,call_set_AO = True,new_AO = None):
        if widget not in self._widgets:
            raise RuntimeError('The widget cannot be removed because it is not registered with this AO object')
            #TODO: Make the above error message better!
         
        self._widgets.remove(widget)  
        
        if call_set_AO:
            widget.set_AO(new_AO,True,True)
            
        # Further cleanup
        widget.disconnect_value_change()
        widget.set_combobox_model(QStandardItemModel())
        
    def change_unit(self,unit):     
        # These values are always stored in base units!
        property_value_list = [self._current_value,self._limits[0],self._limits[1]]
        property_range_list = [self._current_step_size]
        
        # Now convert to the new unit
        if unit != self._base_unit:
            for index,param in enumerate(property_value_list):
                #convert each to base units
                property_value_list[index] = self.convert_value_from_base(param,unit)
            for index,param in enumerate(property_range_list):
                #convert each to base units
                property_range_list[index] = self.convert_range_from_base(property_value_list[0],param,unit)
                
            # figure out how many decimal points we need in the new unit
            trial1 = 10**(-self._decimals)
            derived_trial1 = self.convert_value_fram_base(trial1,unit)
            derived_trial2 = self.convert_value_fram_base(2*trial1,unit)
            difference = abs(derived_trial1-derived_trial2)
            if difference > 1:
                if difference > 10:
                    num_decimals = 0
                else:
                    num_decimals = 1
            else:
                num_decimals = abs(math.ceil(math.log10(difference))-2)
        else:
            num_decimals = self._decimals
        
        # Store the current units
        self._current_units = unit  
        self._settings['current_units'] = unit    
        
        # Check to see if the upper/lower bound has switched
        if property_value_list[1] > property_value_list[2]:
            property_value_list[1], property_value_list[2] = property_value_list[2], property_value_list[1]
        
        # Now update all the widgets
        for widget in self._widgets:
            # Update the combo box
            widget.block_combobox_signals()
            widget.set_selected_unit(unit)
            widget.unblock_combobox_signals()
            # Update the value
            widget.block_spinbox_signals()
            widget.set_spinbox_value(property_value_list[0])
            widget.unblock_spinbox_signals()
            # Update the limits
            widget.set_limits(property_value_list[1],property_value_list[2])
            # Update the step size
            widget.set_step_size(property_range_list[0])
            # Update the decimals
            widget.set_num_decimals(num_decimals)
      
    @property
    def value(self):
        return self._current_value
        
    def set_value(self, value, unit=None, program=True):
        # conversion to float means a string can be passed in too:
        value = float(value)
        
        if unit is not None and unit != self._base_unit:
            self._current_value = self.convert_value_to_base(value,unit)
        else:
            self._current_value = value
        
        # Update the saved value in the settings dictionary
        self._settings['base_value'] = self._current_value
            
        if program:
            self._program_device()
            
        for widget in self._widgets:
            # block signals
            widget.block_spinbox_signals()
            # update widget
            widget.set_spinbox_value(value)
            # unblock signals            
            widget.unblock_spinbox_signals()
    
    def set_step_size(self,step_size,unit):
        if unit != self._base_unit:
            # convert and store!
            value = self.convert_value_from_base(self._current_value,unit)
            self._step_size = self.convert_range_to_base(value,step_size,unit)
        else:
            # This check is usually performed when converting the range to base units
            # But since we are already in base units we should do it here
            if abs(self._limits[0]-self._limits[1]) <= step_size:
                step_size = abs(self._limits[0]-self._limits[1])
            self._step_size = step_size
        
        self._current_step_size = self._step_size
        self._settings['base_step_size'] = self._step_size
        
        # now convert to current units
        converted_step_size = self.get_step_size(self._current_units)
    
        # Update the step size for all widgets
        for widget in self._widgets:
            widget.set_step_size(converted_step_size)
    
    def get_step_size(self,unit):
        if unit != self._base_unit:
            # we should convert it
            return self.convert_range_from_base(self._current_value,self._step_size,unit)
        else:
            return self._step_size
    
    def lock(self):
        self._update_lock(True)
        
    def unlock(self):
        self._update_lock(False)
    
    def _update_lock(self, locked):    
        self._locked = locked        
        self._settings['locked'] = locked
        
        # Lock all widgets if they are not already locked
        for widget in self._widgets:
            if locked:
                widget.lock(False)
            else:
                widget.unlock(False)

            
class DO(object):
    def __init__(self, hardware_name, connection_name, program_function, settings):
        self._hardware_name = hardware_name
        self._connection_name = connection_name
        self._widget_list = []
        # Note that while we could store self._current_state and self._locked in the
        # settings dictionary, this dictionary is available to other parts of BLACS
        # and using separate variables avoids those parts from being able to directly
        # influence behaviour (the worst they can do is change the value used on initialisation)
        self._locked = False
        self._current_state = False
        self._program_device = program_function
        self._update_from_settings(settings)
    
    def _update_from_settings(self,settings):
        # Build up the settings dictionary if it isn't already
        if not isinstance(settings,dict):
            settings = {}
        if 'front_panel_settings' not in settings or not isinstance(settings['front_panel_settings'],dict):
            settings['front_panel_settings'] = {}
        if self._hardware_name not in settings['front_panel_settings'] or not isinstance(settings['front_panel_settings'][self._hardware_name],dict):
            settings['front_panel_settings'][self._hardware_name] = {}
        # Set default values if they are not already saved in the settings dictionary
        if 'base_value' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['base_value'] = False
        if 'locked' not in settings['front_panel_settings'][self._hardware_name]:
            settings['front_panel_settings'][self._hardware_name]['locked'] = False
    
        # only keep a reference to the part of the settings dictionary relevant to this DO
        self._settings = settings['front_panel_settings'][self._hardware_name]
    
        # Update the state of the button
        self.set_state(self._settings['base_value'],program=False)

        # Update the lock state
        self._update_lock(self._settings['locked'])
    
    def create_widget(self,*args,**kwargs):
        widget = DigitalOutput('%s\n%s'%(self._hardware_name,self._connection_name),*args,**kwargs)
        self.add_widget(widget)
        return widget
    
    def add_widget(self,widget):
        if widget not in self._widget_list:
            widget.set_DO(self,True,False)
            widget.toggled.connect(self.set_state)
            self._widget_list.append(widget)
            self.set_state(self._current_state,False)
            self._update_lock(self._locked)
        
    def remove_widget(self,widget):
        if widget not in self._widget_list:
            # TODO: Make this error better!
            raise RuntimeError('The widget specified was not part of the DO object')
        widget.toggled.disconnect(self.set_state)
        self._widget_list.remove(widget)
        
    @property  
    def state(self):
        return bool(self._current_state)
    
    def lock(self):
        self._update_lock(True)
        
    def unlock(self):
        self._update_lock(False)
    
    def _update_lock(self,locked):
        self._locked = locked
        for widget in self._widget_list:
            if locked:
                widget.lock(False)
            else:
                widget.unlock(False)
        
        # update the settings dictionary if it exists, to maintain continuity on tab restarts
        self._settings['locked'] = locked
            
    def set_state(self,state,program=True):
        # conversion to integer, then bool means we can safely pass in
        # either a string '1' or '0', True or False or 1 or 0
        state = bool(int(state))    
        
        # We are programatically setting the state, so break the check lock function logic
        self._current_state = state
        
        # update the settings dictionary if it exists, to maintain continuity on tab restarts
        self._settings['base_value'] = state
        
        if program:
            self._program_device()
            
        for widget in self._widget_list:
            if state != widget.state:
                widget.blockSignals(True)
                widget.state = state
                widget.blockSignals(False)
   

class DDS(object):
    def __init__(self, output_list):
        self._sub_channel_list = ['freq','amp','phase','gate']
        for subchnl in self._sub_channel_list:
            value = None
            if subchnl in output_list:
                value = output_list[subchnl]
            
            setattr(self,subchnl,value)
            
    def add_sub_channel(self,type,output):
        if type not in self._sub_channel_list:
            raise RuntimeError('Invalid output type sepcified when adding a sub channel to a DDS. It must be either freq, amp, phase or gate')
        
        setattr(self,type,output)
        #TODO update all widgets to now show this!
        
    def add_widget(self, widget):
        # TODO create a DDS output widget class for people to use.
        # Link the output objects (sub channels) to the relevant widgets
        # show/hide output widgets if the object is not set (eg hide gate button)
        pass
        
if __name__ == '__main__':
    from qtutils.widgets.toolpalette import ToolPaletteGroup
    import sys
    
    qapplication = QApplication(sys.argv)
    
    window = QWidget()
    layout = QVBoxLayout(window)
    widget = QWidget()
    layout.addWidget(widget)
    tpg = ToolPaletteGroup(widget)
    toolpalette = tpg.append_new_palette('Digital Outputs')    
    toolpalette2 = tpg.append_new_palette('Analog Outputs')    
    layout.addItem(QSpacerItem(0,0,QSizePolicy.Minimum,QSizePolicy.MinimumExpanding))
    
    # create settings dictionary
    settings = {'front_panel_settings':{
                    'do0':{
                        'base_value':False,
                        'locked':False,
                        },
                    'ao0':{
                        'base_value':3.0,
                        'locked':False,
                        'base_step_size':0.1,
                        'current_units':'V',
                        }
                }
        }
    
    def print_something():
        print 'program_function called'
    
    # Create a DO object
    my_DO = DO(hardware_name='do0', connection_name='my first digital output', program_function=print_something, settings=settings)
    
    # Link in two DO widgets
    button1 = DigitalOutput('do0\nmy first digital output')
    button2 = DigitalOutput('a linked do0')
    toolpalette.addWidget(button1)
    toolpalette.addWidget(button2)
    my_DO.add_widget(button1)
    my_DO.add_widget(button2)
    
    # Create an AO object
    my_AO = AO(hardware_name = 'ao0', connection_name='my ao', device_name='ni_blah',
                program_function=print_something, settings=settings, 
                calib_class=None, calib_params=None, default_units='V', 
                min=-10.0, max=10.0, step=0.01, decimals=3)
    
    # link in two AO widgets
    analog1 = AnalogOutput('AO1')
    analog2 = AnalogOutput('AO1 copy')
    my_AO.add_widget(analog1)
    my_AO.add_widget(analog2)
    toolpalette2.addWidget(analog1)
    toolpalette2.addWidget(analog2)
    
    
    window.show()
    sys.exit(qapplication.exec_())
    