import gobject

class AO(gobject.GObject):
    def __init__(self,parent,hardware_callback,programming_callback,channel,hardware_name,real_name,limits):
        self.__gobject_init__()
        self.value = 0.
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.add_callback(hardware_callback)
        self.__max_value = float(limits[1])
        self.__min_value = float(limits[0])
        self.connect("program", programming_callback)
        self.programming_callback = programming_callback
        
    def add_callback(self,func):
        self.connect("update_gui",func)
	
    def update_value(self,value,update_gui = True, program_hardware = True):
        value = float(value)
        if value < self.__min_value:
            self.value = self.__min_value
        elif value > self.__max_value:
            self.value = self.__max_value
        else:
            self.value = value
        
        if update_gui:
            self.emit("update_gui")
            
        if program_hardware:
            self.emit("program")
		
gobject.type_register(AO)
gobject.signal_new("update_gui", AO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())
                   
gobject.signal_new("program", AO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())                   