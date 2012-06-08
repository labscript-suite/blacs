import os
import gtk

class Watcher(object):
    name = "Watched Files"

    def __init__(self):
        # initialise !
        pass
        
    # Create the GTK page, and add to the notebook    
    def create_dialog(self,notebook):
        builder = gtk.Builder()
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),'watcher.glade'))
        builder.connect_signals(self)
    
        toplevel = builder.get_object('toplevel')
        
        notebook.append_page(toplevel,gtk.Label("File Watcher"))
        toplevel.show()
        
    def save(self):
        pass
        
    def close(self):
        pass
    
    
    