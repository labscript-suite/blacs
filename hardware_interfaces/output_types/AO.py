import gobject

class AO(gobject.GObject):
    def __init__(self,parent,hardware_callback,channel,hardware_name,real_name,limits):
        self.__gobject_init__()
        self.value = 0.
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.add_callback(hardware_callback)
        self.__max_value = float(limits[1])
        self.__min_value = float(limits[0])
        
    def add_callback(self,func):
        self.connect("update_value",func)
	
    def update_value(self,value):
        value = float(value)
        if value < self.__min_value:
            self.value = self.__min_value
        elif value > self.__max_value:
            self.value = self.__max_value
        else:
            self.value = value
        
        self.emit("update_value")
		
gobject.type_register(AO)
gobject.signal_new("update_value", AO, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())