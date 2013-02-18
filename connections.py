import h5_lock, h5py
import logging
import excepthook
import numpy as np

class ConnectionTable(object):    
    def __init__(self, h5file):
        self.logger = logging.getLogger('BLACS.ConnectionTable') 
        self.toplevel_children = {}
        self.logger.debug('Parsing connection table from %s'%h5file)
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                table = hdf5_file['connection table']
            except:
                raise
            try:
                if len(table):
                    self.table = np.array(table)
                else:
                    self.table = np.array([])
                for row in self.table:
                    if row[3] == "None":
                        self.toplevel_children[row[0]] = Connection(row[0],row[1],None,row[3],row[4],row[5],row[6],self.table)
                try:
                    self.master_pseudoclock = table.attrs['master_pseudoclock']
                except:
                    self.master_pseudoclock = None
            except:
                self.logger.error('Unable to get connection table  %s'%h5file)
                raise
    
    def assert_superset(self,other):
        # let's check that we're a superset of the connection table in "other"
        if not isinstance(other,ConnectionTable):
            raise TypeError, "Loaded file is not a valid connection table"
        
        missing = []    # things i don't know exist
        incompat = []   # things that are different from what i expect
        
        devlist = dict(zip(self.table['name'],self.table))  # dict-arise it!
        for dev in other.table:
            z = devlist.get(dev[0],None)    # does it exist?
            if z is None:
                missing.append(dev[0])
            elif z != dev:                  # is it the same?
                incompat.append(dev[0])
        
        # construct a human-readable explanation
        errmsg = ""
        if len(missing) > 0:
            errmsg += '\nDevices that do not exist in the connection table:\n\t'+'\n\t'.join(missing)
        if len(incompat) > 0:
            errmsg += '\nDevices with incompatible settings:\n\t'+'\n\t'.join(incompat)
        
        # if there is no error message, then everything must be good!
        if len(errmsg) > 0:
            raise Exception, "Cannot execute script as connection tables do not match."+errmsg
        
    def compare_to(self,other_table):
        if not isinstance(other_table,ConnectionTable):
            return False,{"error":"The connection table passed in is not a valid connection table"}
        error = {}
        # Check if top level children in other table are a subset of self.        
        for name,connection in other_table.toplevel_children.items():
            if not name in self.toplevel_children:
                self.logger.error('missing: %s'%str(name))
                if "children_missing" not in error:
                    error["children_missing"] = {}
                error["children_missing"][name] = True
            else:
                # for each top level child in other, check if children of that object are also children of the child in self.
                result,child_error = self.toplevel_children[name].compare_to(connection)
                if not result:
                    #TODO more info on what doesn't match? Print a diff and return it as part of the message?
                    self.logger.error('Connection table mismatch')
                    if "children" not in error:
                        error["children"] = {}
                    error["children"][name] = child_error
                
        if error != {}:
            return False,error
        else:
            return True,error

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
    
    # Returns the "Connection" object which is a child of "device_name", connected via "parent_port"
    # Eg, Returns the child of "pulseblaster_0" connected via "dds 0"
    def find_child(self,device_name,parent_port):
        for k,v in self.toplevel_children.items():
            val = v.find_child(device_name,parent_port)
            if val is not None:
                return val
                
        return None
    
    def find_by_name(self,name):
        for device_name,connection in self.toplevel_children.items():
            if device_name == name:
                return connection
            else:
                result = connection.find_by_name(name)
                if result is not None:
                    return result
        return None
    
class Connection(object):
    
    def __init__(self, name, device_class, parent, parent_port, unit_conversion_class, unit_conversion_params, BLACS_connection, table):
        self.child_list = {}
        self.name = name
        self.device_class = device_class
        self.parent_port = parent_port
        self.parent = parent
        self.unit_conversion_class = unit_conversion_class
        self.unit_conversion_params = unit_conversion_params
        self.BLACS_connection = BLACS_connection
        
        # Create children
        for row in table:
            if row[2] == self.name:
                self.child_list[row[0]] = Connection(row[0],row[1],self,row[3],row[4],row[5],row[6],table)
        
    def compare_to(self,other_connection):
        if not isinstance(other_connection,Connection):
            return False,{"error":"Internal Error. Connection Table object is corrupted."}
            
        error = {}
        # Compare all parameters between this connection, and other connection
        if self.name != other_connection.name:
            error["name"] = True
        if self.device_class != other_connection.device_class:
            error["device_class"] = True
        if self.parent_port != other_connection.parent_port:
            error["parent_port"] = True
        if self.unit_conversion_class != other_connection.unit_conversion_class:
            error["unit_conversion_class"] = True
        if self.unit_conversion_params != other_connection.unit_conversion_params:
            error["unit_conversion_params"] = True
        if self.BLACS_connection != other_connection.BLACS_connection:
            error["BLACS_connection"] = True
        
        # for each child in other_connection, check that the child also exists here
        for name,connection in other_connection.child_list.items():
            if not name in self.child_list:
                error.setdefault("children_missing",{})
                error["children_missing"][name] = True
                
            else:    
                # call compare_to on child so that we can check it's children!
                result,child_error = self.child_list[name].compare_to(connection)
                if not result:
                    error.setdefault("children",{})
                    error["children"][name] = child_error
                
        # We made it!
        if error != {}:
            return False,error
        else:
            return True,error
        
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

    def find_child(self,device_name,parent_port):
        for k,v in self.child_list.items():
            if v.parent.name == device_name and v.parent_port == parent_port:
                return v
        
        # This is done separately to the above iteration for speed. 
        # We search for all children first, before going down another layer.
        for k,v in self.child_list.items():
            val = v.find_child(device_name,parent_port)
            if val is not None:
                return val
        
        return None

    def find_by_name(self,name):
        for device_name,connection in self.child_list.items():
            if device_name == name:
                return connection
            else:
                result = connection.find_by_name(name)
                if result is not None:
                    return result
        return None    
