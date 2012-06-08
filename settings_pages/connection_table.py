import os
import gtk

class ConnectionTable(object):
    name = "Connection Table"

    def __init__(self):
        # initialise !
        pass
        
    # Create the GTK page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        builder = gtk.Builder()
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'connection_table.glade'))
        builder.connect_signals(self)
    
        toplevel = builder.get_object('toplevel')
        
        return toplevel,None
        
    def save(self):
        pass
        
    def close(self):
        pass
    
    
    