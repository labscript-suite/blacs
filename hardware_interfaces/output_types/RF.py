import gobject

class RF(gobject.GObject):
    def __init__(self,parent,hardware_callback,channel,hardware_name,real_name,limits):
        self.__gobject_init__()
        self.phase = 0.
        self.freq = 0.
        self.amp = 0.
        self.parent = parent
        self.channel = channel
        self.hardware_name = hardware_name
        self.real_name = real_name
        self.add_callback(hardware_callback)
        self.__max_freq = float(limits[1])
        self.__min_freq = float(limits[0])
        self.__max_amp = float(limits[3])
        self.__min_amp = float(limits[2])
        self.__max_phase = float(limits[5])
        self.__min_phase = float(limits[4])
        
    def add_callback(self,func):
        self.connect("update_value",func)
	
    def update_value(self,freq,amp,phase):
        freq = float(freq)
        if freq < self.__min_freq:
            self.freq = self.__min_freq
        elif freq > self.__max_freq:
            self.freq = self.__max_freq
        else:
            self.freq = freq
        
        amp = float(amp)
        if amp < self.__min_amp:
            self.amp = self.__min_amp
        elif amp > self.__max_amp:
            self.amp = self.__max_amp
        else:
            self.amp = amp
        
        phase = float(phase)
        # if phase wraps!
        if self.__max_phase == 360.0 and self.__min_phase == 0.0:
            self.phase = phase % 360.0
        # else limit phase between min/max    
        else:
            if phase < self.__min_phase:
                self.phase = self.__min_phase
            elif phase > self.__max_phase:
                self.phase = self.__max_phase
            else:
                self.phase = phase
        self.emit("update_value")
		
gobject.type_register(RF)
gobject.signal_new("update_value", RF, gobject.SIGNAL_RUN_FIRST,
                   gobject.TYPE_NONE, ())