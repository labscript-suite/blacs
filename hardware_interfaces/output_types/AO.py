import gobject

class AO(gobject.GObject):
    def __init__(self,parent,hardware_callback,programming_callback,channel,hardware_name,real_name,limits):
        self.__gobject_init__()
        self.value = 0.
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.update_gui_callbacks = []
        self.add_callback(hardware_callback)
        self.program_hardware = programming_callback
        self.__max_value = float(limits[1])
        self.__min_value = float(limits[0])
        
    def add_callback(self,func):
        self.update_gui_callbacks.append(func)
	
    def update_value(self,value,update_gui = True, program_hardware = True):
        value = float(value)
        if value < self.__min_value:
            self.value = self.__min_value
        elif value > self.__max_value:
            self.value = self.__max_value
        else:
            self.value = value
        
        if update_gui:
            for func in self.update_gui_callbacks:
                func(self)
            
        if program_hardware:
            self.program_hardware(self)