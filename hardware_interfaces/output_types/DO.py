import gobject

class DO(gobject.GObject):
    def __init__(self,parent,hardware_callback,programming_callback,channel,hardware_name,real_name):
        self.__gobject_init__()
        self.state = False
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.update_gui_callbacks = []
        self.add_callback(hardware_callback)
        self.program_hardware = programming_callback
        
    def add_callback(self,func):
        self.update_gui_callbacks.append(func)
	
    def update_value(self,state,update_gui = True, program_hardware = True):
        # conversion to integer, then bool means we can safely pass in either a string '1' or '0', True or False or 1 or 0
        self.state = bool(int(state))
        if update_gui:
            for func in self.update_gui_callbacks:
                func(self)
            
        if program_hardware:
            self.program_hardware(self)
