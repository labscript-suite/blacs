import gobject

class DO(gobject.GObject):
    def __init__(self,parent,hardware_callback,programming_callback,channel,hardware_name,real_name):
        self.__gobject_init__()
        self.state = False
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.add_callback(hardware_callback)
        self.connect("program", programming_callback)
        self.programming_callback = programming_callback
        
    def add_callback(self,func):
        self.connect("update_gui",func)
	
    def update_value(self,state,update_gui = True, program_hardware = True):
        # conversion to integer, then bool means we can safely pass in either a string '1' or '0', True or False or 1 or 0
        self.state = bool(int(state))
        if update_gui:
            self.emit("update_gui")
            
        if program_hardware:
            self.emit("program")
        
		
gobject.type_register(DO)
gobject.signal_new("update_gui", DO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())
                   
gobject.signal_new("program", DO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())