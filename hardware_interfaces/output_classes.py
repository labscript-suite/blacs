class AO(object):
    def __init__(self, name,  channel, widget, static_update_function, min, max, step, page):
        self.widget = widget
        self.handler_id = self.widget.connect('value-changed',static_update_function)
        self.set_limits(min,max,page,step)
        self.name = name
        self.channel = channel
        
    def set_limits(self,min, max, page, steps):
        self.widget.set_increments(step,page)
        self.widget.set_range(min,max)

    @property
    def value(self):
        return self.widget.get_value()
        
    def set_value(self, value, program=True):
        if not program:
            self.widget.block(self.hadler_id)
        if value != self.value:
            self.widget.set_value(value)
        if not_program:
            self.widget.unblock(self.handler_id)
            
            
class DO(object):
    def __init__(self, name, channel, widget, static_update_function):
        self.widget = widget
        self.handler_id = widget.connect('toggled',static_update_function)
        self.name = name
        self.channel = channel
        
    @property   
    def state(self):
        return self.widget.get_state()
        
    def set_state(self,state,program=True):
        # conversion to integer, then bool means we can safely pass in
        # either a string '1' or '0', True or False or 1 or 0
        state = bool(int(state))
        if not program:
            self.widget.block(self.hadler_id)
        if value != widget.get_value():
            self.widget.set_state(state)
        if not_program:
            self.widget.unblock(self.handler_id)
   
   
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
        
