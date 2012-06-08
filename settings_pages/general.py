import os
import gtk

class General(object):
    name = "General"

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        self.var_list = [('ct_editor','','get_text','set_text')]
        for var in self.var_list:
            if var[0] not in self.data:
                data[var[0]] = var[1]
        
    # Create the GTK page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        builder = gtk.Builder()
        self.builder = builder
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'general.glade'))
        builder.connect_signals(self)
    
        toplevel = builder.get_object('toplevel')
        
        # get the widgets!
        self.widgets = {}
        for var in self.var_list:
            self.widgets[var[0]] = self.builder.get_object(var[0])
            getattr(self.widgets[var[0]],var[3])(self.data[var[0]])
        
        return toplevel,None
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        # transfer the contents of the list store into the data store, and then return the data store
        for var in self.var_list:
            self.data[var[0]] = getattr(self.widgets[var[0]],var[2])()
        
        return self.data
        
    def close(self):
        pass
        
    