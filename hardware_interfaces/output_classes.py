import gtk
from calibrations import *

class AO(object):
    def __init__(self, name,  channel, widget, combobox, calib_class, calib_params, default_units, static_update_function, min, max, step):
        self.adjustment = gtk.Adjustment(0,min,max,step,10*step,0)
        self.handler_id = self.adjustment.connect('value-changed',static_update_function)
        self.name = name
        self.channel = channel
        self.locked = False
        self.comboboxmodel = combobox.get_model()
        self.comboboxes = []
        self.comboboxhandlerids = []
        self.current_units = default_units
        self.hardware_unit = default_units
        self.limits = [min,max]
        
        
        # Initialise Calibrations
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
        
        self.add_widget(widget,combobox)
        
    def add_widget(self,widget, combobox):
        widget.set_adjustment(self.adjustment)
        # Set the model to match the other comboboxes
        combobox.set_model(self.comboboxmodel)
        # set the active item to match the active item of one of the comboboxes
        if self.comboboxes:
            combobox.set_active(self.comboboxes[0].get_active())
        else:
            combobox.set_active(0)
        self.comboboxes.append(combobox)
        self.comboboxhandlerids.append(combobox.connect('changed',self.on_selection_changed))
        
        # Add signal to populate the right click context menu with our own things!
        widget.connect("populate-popup", self.populate_context_menu)
     
    def on_selection_changed(self,combobox):
        for box, id in zip(self.comboboxes,self.comboboxhandlerids):
            if box is not combobox:
                box.handler_block(id)
                box.set_selection(combobox.get_selection())
                box.handler_unblock(id)
                
        # Update the parameters of the Adjustment to match the new calibration!
        new_units = self.comboboxmodel.get(combobox.get_active_iter(),0)[0]
        parameter_list = [self.adjustment.get_value(),self.adjustment.get_lower(),self.adjustment.get_upper(),self.adjustment.get_step_increment(),
                            self.adjustment.get_page_increment(), self.limits[0],self.limits[1]]
        
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
        
        # update saved limits
        if parameter_list[5] > parameter_list[6]:
            parameter_list[5], parameter_list[6] = parameter_list[6], parameter_list[5] 
        self.limits = [parameter_list[5], parameter_list[6]]
        
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
    
    def set_limits(self, menu_item):
        pass
        
    def change_step(self, menu_item):
        dialog = gtk.Dialog("My dialog",
                     None,
                     gtk.DIALOG_MODAL,
                     (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                      gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        
        label = gtk.Label("Set the step size for the up/down controls on the spinbutton in %s"%self.current_units)
        dialog.vbox.pack_start(label, expand = False, fill = False)
        label.show()
        entry = gtk.Entry()
        dialog.get_content_area().pack_end(entry)
        entry.show()
        response = dialog.run()
        value_str = entry.get_text()
        dialog.destroy()
        
        if response == gtk.RESPONSE_ACCEPT:
            
            try:
                # Get the value from the entry
                value = float(value_str)
                
                # Check if the value is valid
                if value > (self.limits[1] - self.limits[0]):
                    raise Exception("The step size specified is greater than the difference between the current limits")
                
                self.adjustment.set_step_increment(value)
                self.adjustment.set_page_increment(value*10)
                
            except Exception, e:
                # Make a message dialog with an error in
                dialog = gtk.MessageDialog(None,
                     gtk.DIALOG_MODAL,
                     gtk.MESSAGE_ERROR,
                     (gtk.STOCK_OK, gtk.RESPONSE_ACCEPT),
                     "An error occurred while updating the step size:\n\n")
                     
                dialog.run()
                dialog.destroy()
        
    def lock(self, menu_item):
        self.locked = not self.locked
        
        if self.locked:
            # Save the limits (this will be inneccessary once we implement set_limits)
            self.limits = [self.adjustment.get_lower(),self.adjustment.get_upper()]
            
            # Set the limits equal to the value
            value = self.adjustment.get_value()
            self.adjustment.set_lower(value)
            self.adjustment.set_upper(value)
        else:
            # Restore the limits
            self.adjustment.set_lower(self.limits[0])
            self.adjustment.set_upper(self.limits[1])
        
    def populate_context_menu(self,widget,menu):
        # is it a right click?
        menu_item1 = gtk.MenuItem("Set Limits")
        menu_item1.connect("activate",self.set_limits)
        menu_item1.show()
        menu.append(menu_item1)
        menu_item2 = gtk.MenuItem("Unlock Widget" if self.locked else "Lock Widget")
        menu_item2.connect("activate",self.lock)
        menu_item2.show()
        menu.append(menu_item2)
        menu_item3 = gtk.MenuItem("Change step size")
        menu_item3.connect("activate",self.change_step)
        menu_item3.show()
        menu.append(menu_item3)
        sep = gtk.SeparatorMenuItem()
        sep.show()
        menu.append(sep)
        # reorder children
        menu.reorder_child(menu_item2,0)
        menu.reorder_child(menu_item1,1)
        menu.reorder_child(sep,2)
        
        
            
class DO(object):
    def __init__(self, name, channel, widget, static_update_function):
        self.action = gtk.ToggleAction('%s\n%s'%(channel,name), '%s\n%s'%(channel,name), "", 0)
        self.handler_id = self.action.connect('toggled',static_update_function)
        self.name = name
        self.channel = channel
        self.add_widget(widget)
        self.locked = False
    
    def add_widget(self,widget):
        self.action.connect_proxy(widget)
        widget.connect('button-release-event',self.btn_release)
        
    @property   
    def state(self):
        return bool(self.action.get_active())
    
    def lock(self,menuitem):
        self.locked = not self.locked
        self.action.set_sensitive(not self.locked)
            
    def set_state(self,state,program=True):
        # conversion to integer, then bool means we can safely pass in
        # either a string '1' or '0', True or False or 1 or 0
        state = bool(int(state))
        if not program:
            self.action.handler_block(self.handler_id)
        if state != self.state:
            self.action.set_active(state)
        if not program:
            self.action.handler_unblock(self.handler_id)
   
    def btn_release(self,widget,event):
        if event.button == 3:
            menu = gtk.Menu()
            menu_item = gtk.MenuItem("Unlock Widget" if self.locked else "Lock Widget")
            menu_item.connect("activate",self.lock)
            menu_item.show()
            menu.append(menu_item)
            menu.popup(None,None,None,event.button,event.time)
            
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
        
