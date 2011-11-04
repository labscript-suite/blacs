import gobject
from hardware_interfaces.output_types.RF import *
from hardware_interfaces.output_types.DO import *

# The DDS output type is simply a combination of an RF channel and a DO channel
# In the case of the supernova, this is a combination a novatech dds and a DO from somewhere
# In the case of the PulseBlaster, this is the pulseblaster DDS and a fake DO immitating the on/off control of the DDS
class DDS(gobject.GObject):
    def __init__(self,parent,rf,do):
        self.__gobject_init__()
        self.parent = parent
        self.rf = rf
        self.do = do
        #self.add_callback(hardware_callback)
        
        # register child_updated function with children, so that DDS outputs are updated when RF/DO is updated
        #self.do.add_callback(self.child_updated)
        #self.rf.add_callback(self.child_updated)
                
    def add_callback(self,func):
        #self.connect("update_value",func)
        self.do.add_callback(func)
        self.rf.add_callback(func)
        
	
    def update_value(self,state,freq,amp,phase,update_gui = True, program_hardware = True):
        # Update DO/RF (also triggers callbacks only registered with children)
        # Since we register our own callback with these children, we don't need to do the emit on the dds object like we usually do.
        # child_updated will be called by the following functions!
        self.do.update_value(state,update_gui=update_gui, program_hardware=program_hardware)
        self.rf.update_value(freq,amp,phase,update_gui=update_gui, program_hardware=program_hardware)
		
                      