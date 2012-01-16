import h5py
import logging
import excepthook

class ConnectionTable(object):    
    def __init__(self, h5file):
        self.logger = logging.getLogger('BLACS.ConnectionTable') 
        self.toplevel_children = {}
        self.logger.debug('Parsing connection table from %s'%h5file)
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                table = hdf5_file['connection table'][:]
                
                for row in table:
                    if row[3] == "None":
                        self.toplevel_children[row[0]] = Connection(row[0],row[1],None,row[3],row[4],row[5],table)
                
            except:
                self.logger.error('Unable to get connection table  %s'%h5file)
                raise
        
    def compare_to(self,other_table):
        if not isinstance(other_table,ConnectionTable):
            return False
    
        # Check if top level children in other table are a subset of self.        
        for key,value in other_table.toplevel_children.items():
            if not key in self.toplevel_children:
                self.logger.error('missing: %s'%str(key))
                return False
            
            # for each top level child in other, check if children of that object are also children of the child in self.
            if not self.toplevel_children[key].compare_to(value):
                #TODO more info on what doesn't match? Print a diff and return it as part of the message?
                self.logger.error('Connection table mismatch')
                return False
                
        return True

    def print_details(self):
        for key,value in self.toplevel_children.items():
            print key
            value.print_details('    ')
    
    # Returns a list of "connection" objects which have the one of the classes specified in the "device_list"
    def find_devices(self,device_list):
        return_list = {}
        for key,value in self.toplevel_children.items():
            return_list = value.find_devices(device_list,return_list)
        
        return return_list
    
    # Returns the "Connection" object which is a child of "device_name", connected via "connected_to"
    # Eg, Returns the child of "pulseblaster_0" connected via "dds 0"
    def find_child(self,device_name,connected_to):
        for k,v in self.toplevel_children.items():
            val = v.find_child(device_name,connected_to)
            if val is not None:
                return val
                
        return None
    
class Connection(object):
    
    def __init__(self, name, device_class, parent, connected_to, calibration_class, calibration_parameters, table):
        self.child_list = {}
        self.name = name
        self.device_class = device_class
        self.connected_to = connected_to
        self.parent = parent
        self.calibration_class = calibration_class
        self.calibration_parameters = calibration_parameters
        
        # Create children
        for row in table:
            if row[2] == self.name:
                self.child_list[row[0]] = Connection(row[0],row[1],self,row[3],row[4],row[5],table)
        
    def compare_to(self,other_connection):
        if not isinstance(other_connection,Connection):
            return False
            
        # Compare all parameters between this connection, and other connection
        if self.name != other_connection.name:
            return False
        if self.device_class != other_connection.device_class:
            return False
        if self.connected_to != other_connection.connected_to:
            return False
        if self.calibration_class != other_connection.calibration_class:
            return False
        if self.calibration_parameters != other_connection.calibration_parameters:
            return False
        
        # for each child in other_connection, check that the child also exists here
        for key,value in other_connection.child_list.items():
            if not key in self.child_list:
                return False
                
            # call compare_to on child so that we can check it's children!
            if not self.child_list[key].compare_to(value):
                return False
                
        # We made it!
        return True
        
    def print_details(self,indent):
        for key, value in self.child_list.items():
            print indent + key
            value.print_details(indent+'    ')
    
    def find_devices(self,device_list,return_list):
        for device in device_list:
            if device.lower() == self.device_class.lower():
                return_list[self.name] = device            
            
        for key,value in self.child_list.items():
            return_list = value.find_devices(device_list,return_list)
            
        return return_list   

    def find_child(self,device_name,connected_to):
        for k,v in self.child_list.items():
            if v.parent.name == device_name and v.connected_to == connected_to:
                return v
        
        # This is done separately to the above iteration for speed. 
        # We search for all children first, before going down another layer.
        for k,v in self.child_list.items():
            val = v.find_child(device_name,connected_to)
            if val is not None:
                return val
        
        return None
