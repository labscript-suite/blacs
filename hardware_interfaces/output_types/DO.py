import gobject

class DO(gobject.GObject):
    def __init__(self,parent,hardware_callback,channel,hardware_name,real_name):
        self.__gobject_init__()
        self.state = False
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.add_callback(hardware_callback)
        
    def add_callback(self,func):
        self.connect("update_value",func)
	
    def update_value(self,state):
        # conversion to integer, then bool means we can safely pass in either a string '1' or '0', True or False or 1 or 0
        self.state = bool(int(state))
        self.emit("update_value")
		
gobject.type_register(DO)
gobject.signal_new("update_value", DO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())