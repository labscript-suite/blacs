class AO(object):
    def __init__(self, name,  channel, widget, static_update_function, min, max, step):
        self.widget = widget
        self.handler_id = self.widget.connect('value-changed',static_update_function)
        self.set_limits(min,max,step)
        self.name = name
        self.channel = channel
        
    def set_limits(self,min, max, step):
        self.widget.set_increments(step,10*step)
        self.widget.set_range(min,max)

    @property
    def value(self):
        return self.widget.get_value()
        
    def set_value(self, value, program=True):
        # conversion to float means a string can be passed in too:
        value = float(value)
        if not program:
            self.widget.handler_block(self.handler_id)
        if value != self.value:
            self.widget.set_value(value)
        if not program:
            self.widget.handler_unblock(self.handler_id)
            
            
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
        
