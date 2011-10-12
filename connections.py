import h5py

class ConnectionTable(object):    
    def __init__(self, h5file):
        self.toplevel_children = {}
        
        with h5py.File(h5file,'r') as hdf5_file:
            try:
                table = hdf5_file['connection table'][:]
                
                for row in table:
                    if row[3] == "None":
                        self.toplevel_children[row[0]] = Connection(row[0],row[1],None,row[3],table)
                
            except:
                print 'Unable to load connection table from '+h5file
        
    def compare_to(self,other_table):
        if not isinstance(other_table,ConnectionTable):
            return False
    
        # Check if top level children in other table are a subset of self.        
        for key,value in other_table.toplevel_children.items():
            if not key in self.toplevel_children:
                print 'missing: '+key
                return False
            
            # for each top level child in other, check if children of that object are also children of the child in self.
            if not self.toplevel_children[key].compare_to(value):
                return False
                
        return True

    def print_details(self):
        for key,value in self.toplevel_children.items():
            print key
            value.print_details('    ')
            
    def find_devices(self,device_list):
        return_list = {}
        for key,value in self.toplevel_children.items():
            for device in device_list:
                if device in key:
                    return_list[key] = device
                    break
            
            return_list = value.find_devices(device_list,return_list)
        
        return return_list
    
class Connection(object):
    
    def __init__(self, name, device_class, parent, connected_to, table):
        self.child_list = {}
        self.name = name
        self.device_class = device_class
        self.connected_to = connected_to
        self.parent = parent
        
        # Create children
        for row in table:
            if row[2] == self.name:
                self.child_list[row[0]] = Connection(row[0],row[1],self,row[3],table)
        
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
        for key,value in self.child_list.items():
            for device in device_list:
                if device in key:
                    return_list[key] = device
                    break
            
            return_list = value.find_devices(device_list,return_list)
            
        return return_list    