import os
import gtk

class ConnectionTable(object):
    name = "Connection Table"

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        self.stores_list = ['globals','calibrations']
        
        for store in self.stores_list:
            if '%s_list'%store not in self.data:
                self.data['%s_list'%store] = []
        
    # Create the GTK page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        builder = gtk.Builder()
        self.builder = builder
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'connection_table.glade'))
        builder.connect_signals(self)
    
        toplevel = builder.get_object('toplevel')
        
        # get the liststores and populate them!
        self.stores = {}
        self.views = {}
        #iterate over the two listores
        for store in self.stores_list:
            # Get and save the liststore for later use
            self.stores[store] = builder.get_object('%s_store'%store)
            self.views[store] = builder.get_object('%s_view'%store)
            # If we have saved data in the data store, then load it into the list store
            if '%s_list'%store in self.data:
                for path in self.data['%s_list'%store]:
                    self.stores[store].append([path])
            # otherwise add an empty list to our data store, and leave the liststore empty
            else:
                self.data['%s_list'%store] = []
        
        return toplevel,None
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        # transfer the contents of the list store into the data store, and then return the data store
        for store in self.stores_list:
            iter = self.stores[store].get_iter_first()
            # clear the existing list
            self.data['%s_list'%store] = []
            while iter:
                self.data['%s_list'%store].append(self.stores[store].get_value(iter,0))                
                iter = self.stores[store].iter_next(iter)
        
        return self.data
        
    def close(self):
        pass
        
    def add_global_file(self,widget):
        # create file choose dialog
        chooser = gtk.FileChooserDialog(title='select globals .h5 file',action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                    buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_OPEN,gtk.RESPONSE_OK))
        filter = gtk.FileFilter()
        filter.add_pattern("*.h5")
        filter.set_name("HDF5 Files")
        chooser.add_filter(filter)
        chooser.set_default_response(gtk.RESPONSE_OK)
        # set this to the current location of the h5_chooser    
        #chooser.set_current_folder(self.globals_path)
               
        chooser.set_current_name('.h5')
        response = chooser.run()
        path = chooser.get_filename()
        chooser.destroy()
        if response == gtk.RESPONSE_OK: 
            # make sure the path isn't already in the list!
            iter = self.stores['globals'].get_iter_first()
            while iter:
                fp = self.stores['globals'].get_value(iter,0)
                if fp == path:
                    return
                iter = self.stores['globals'].iter_next(iter)
        
            # get path, add to liststore
            self.stores['globals'].append([path])
    
    def delete_global_file(self,widget):
        selection = self.views['globals'].get_selection()
        model, selection = selection.get_selected_rows()
        while selection:
            path = selection[0]
            iter = model.get_iter(path)
            model.remove(iter)
            selection = self.views['globals'].get_selection()
            model, selection = selection.get_selected_rows()

    def add_calibration_file(self,widget):
        # create file choose dialog
        chooser = gtk.FileChooserDialog(title='Select calibration script',action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                    buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_OPEN,gtk.RESPONSE_OK))
        filter = gtk.FileFilter()
        filter.add_pattern("*.py")
        filter.set_name("Python Files")
        chooser.add_filter(filter)
        chooser.set_default_response(gtk.RESPONSE_OK)
        # set this to the current location of the h5_chooser    
        #chooser.set_current_folder(self.globals_path)
               
        chooser.set_current_name('.py')
        response = chooser.run()
        path = chooser.get_filename()
        chooser.destroy()
        if response == gtk.RESPONSE_OK: 
            # make sure the path isn't already in the list!
            iter = self.stores['calibrations'].get_iter_first()
            while iter:
                fp = self.stores['calibrations'].get_value(iter,0)
                if fp == path:
                    return
                iter = self.stores['calibrations'].iter_next(iter)
        
            # get path, add to liststore
            self.stores['calibrations'].append([path])
    
    def add_calibration_folder(self,widget):
        # create file choose dialog
        chooser = gtk.FileChooserDialog(title='Select calibration script folder',action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                    buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_OPEN,gtk.RESPONSE_OK))

        chooser.set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)
        chooser.set_default_response(gtk.RESPONSE_OK)
        # set this to the current location of the h5_chooser    
        #chooser.set_current_folder(self.globals_path)
               
        response = chooser.run()
        path = chooser.get_filename()
        chooser.destroy()
        if response == gtk.RESPONSE_OK: 
            # make sure the path isn't already in the list!
            iter = self.stores['calibrations'].get_iter_first()
            while iter:
                fp = self.stores['calibrations'].get_value(iter,0)
                if fp == path:
                    return
                iter = self.stores['calibrations'].iter_next(iter)
        
            # get path, add to liststore
            self.stores['calibrations'].append([path])
    
    def delete_calibration(self,widget):
        selection = self.views['calibrations'].get_selection()
        model, selection = selection.get_selected_rows()
        while selection:
            path = selection[0]
            iter = model.get_iter(path)
            model.remove(iter)
            selection = self.views['calibrations'].get_selection()
            model, selection = selection.get_selected_rows()