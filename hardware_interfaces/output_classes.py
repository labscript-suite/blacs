import gtk
from calibrations import *

class AO(object):
    def __init__(self, name,  channel, widget, combobox, calib_class, calib_params, default_units, static_update_function, min, max, step):
        self.adjustment = gtk.Adjustment(0,min,max,step,10*step,0)
        self.handler_id = self.adjustment.connect('value-changed',static_update_function)
        self.name = name
        self.channel = channel
        self.add_widget(widget,combobox)
        self.comboboxes = []
        self.comboboxhandlerids = []
        
        self.comboboxmodel = combobox.get_model()
        self.current_units = default_units
        self.hardware_unit = default_units
        
        if calib_class is not None:
            if calib_class not in globals() or not isinstance(calib_params,dict) or test.hardware_unit != default_units:
                # Throw an error:
                # Use default units
                self.calibration = None
                self.comboboxmodel.append([default_units])
            else:
                # initialise calibration class
                self.calibration = globals()[calib_class](calib_params)
                self.comboboxmodel.append([self.calibration.hardware_unit])
                for unit in self.calibration.human_units:
                    self.comboboxmodel.append([unit])
                    
                combobox.set_active(0)
        else:
            # use default units
            self.calibration = None
            self.comboboxmodel.append([default_units])
            
        
        
    def add_widget(widget, combobox):
        widget.set_adjustment(self.adjustment)
        # Set the model to match the other comboboxes
        combobox.set_model(self.comboboxmodel)
        # set the active item to match the active item of one of the comboboxes
        combobox.set_active(self.comboboxes[0].get_active())
        self.comboboxes.append(combobox)
        self.comboboxhandlerids.append(combobox.connect('selection-changed',self.on_selection_changed)
     
    def on_selection_changed(self,combobox):
        for box, id in zip(self.comboboxes,self.comboboxhandlerids):
            if box is not combobox:
                box.handler_block(id)
                box.set_selection(combobox.get_selection())
                box.handler_unblock(id)
                
        # Update the parameters of the Adjustment to match the new calibration!
        new_units = self.comboboxmodel.get(combobox.get_active_iter(),0)
        parameter_list = [self.adjustment.get_value(),self.adjustment.get_lower(),self.adjustment.get_upper(),self.adjustment.get_step_increment(),
                            self.adjustment.get_page_increment()]
        
        # If we aren't alreay in hardware units, convert to hardware units
        if self.current_units != self.calibration.hardware_unit:
            # get the conversion function
            convert = getattr(self.calibration,self.current_units+"_to_hardware")
            for index,param in enumerate(parameter_list):
                #convert each to hardware units
                parameter_list[index] = convert(param)
        
        # Now convert to the new unit
        if new_units != self.calibration.hardware_unit:
            convert = getattr(self.calibration,new_units+"_from_hardware")
            for index,param in enumerate(parameter_list):
                #convert each to hardware units
                parameter_list[index] = convert(param)
        
        # Store the current units
        self.current_units = new_units
        
        # Check to see if the upper/lower bound has switched
        if parameter_list[1] > parameter_list[2]:
            parameter_list[1], parameter_list[2] = parameter_list[2], parameter_list[1]
        
        # Update the Adjustment
        self.adjustment.configure(parameter_list[0],parameter_list[1],parameter_list[2],parameter_list[3],parameter_list[4],0)
                
    @property
    def value(self):
        value = self.adjustment.get_value()
        # If we aren't alreay in hardware units, convert to hardware units
        if self.current_units != self.hardware_unit: 
            convert = getattr(self.calibration,self.current_units+"_to_hardware")
            value = convert(value)
        return value
        
    def set_value(self, value, program=True):
        # conversion to float means a string can be passed in too:
        value = float(value)
        # If we aren't in hardware units, convert to the new units!
        if self.current_units != self.hardware_unit: 
            convert = getattr(self.calibration,self.current_units+"_from_hardware")
            value = convert(value)
            
        if not program:
            self.adjustment.handler_block(self.handler_id)
        if value != self.value:            
            self.adjustment.set_value(value)
        if not program:
            self.adjustment.handler_unblock(self.handler_id)
            
            
class DO(object):
    def __init__(self, name, channel, widget, static_update_function):
        self.widget = widget
        self.handler_id = widget.connect('toggled',static_update_function)
        self.name = name
        self.channel = channel
        
    @property   
    def state(self):
        return bool(self.widget.get_state())
        
    def set_state(self,state,program=True):
        # conversion to integer, then bool means we can safely pass in
        # either a string '1' or '0', True or False or 1 or 0
        state = bool(int(state))
        if not program:
            self.widget.handler_block(self.handler_id)
        if state != self.state:
            self.widget.set_state(state)
        if not program:
            self.widget.handler_unblock(self.handler_id)
   

class RF(object):
    def __init__(self, amp, freq, phase):
        self.amp = amp
        self.freq = freq
        self.phase = phase
        
        
class DDS(object):
    def __init__(self, RF, gate):
        self.RF = RF
        self.amp = RF.amp
        self.freq = RF.freq
        self.phase = RF.phase
        self.gate = gate
        
