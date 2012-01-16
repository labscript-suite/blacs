import gtk

class AO(object):
    def __init__(self, name,  channel, widget, combobox, static_update_function, min, max, step):
        self.adjustment = gtk.Adjustment(0,min,max,step,10*step,0)
        self.handler_id = self.adjustment.connect('value-changed',static_update_function)
        self.name = name
        self.channel = channel
        self.add_widget(widget,combobox)
        self.comboboxes = []
        self.comboboxhandlerids = []
        
    def add_widget(widget, combobox):
        widget.set_adjustment(self.adjustment)
        self.comboboxes.append(combobox)
        self.comboboxhandlerids.append(combobox.connect('selection-changed',self.on_selection_changed)
     
    def on_selection_changed(self,combobox):
        for box, id in zip(self.comboboxes,self.comboboxhandlerids):
            if box is not combobox:
                box.handler_block(id)
                box.set_selelction(combobox.get_selection())
                box.handler_unblock(id)
        self.adjustment.set_value()
                
    @property
    def value(self):
        value = self.adjustment.get_value()
        # ...convert to hardware units
        return value
        
    def set_value(self, value, program=True):
        # conversion to float means a string can be passed in too:
        value = float(value)
        if not program:
            self.adjustment.handler_block(self.handler_id)
        if value != self.value:
            # ...convert to current units
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
        
