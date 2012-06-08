import gtk
import new
import time

class Notifications(object):
    def __init__(self,BLACS):
        self.BLACS = BLACS
        
        self.builder = gtk.Builder()
        self.builder.add_from_file('notifications.glade')
        
        self.toplevel = self.builder.get_object('toplevel')
        self.notification_bar = self.builder.get_object('minimized_notifications')
        self.notifications = {}
        
        # Define notifications here
        self.types = ['unversioned','recompile']
        
        for name in self.types:
            self.notifications[name] = {}
            self.notifications[name]['expanded'] = self.builder.get_object('expanded_'+name)
            self.notifications[name]['minimized'] = self.builder.get_object('minimized_'+name)            
        
            def minimize(self,widget,name=name):
                self.notifications[name]['minimized'].show()
                self.notifications[name]['expanded'].hide()
                self.update_bar()
                
            def expand(self,widget,name=name):
                self.notifications[name]['minimized'].hide()
                self.notifications[name]['expanded'].show()
                self.update_bar()
                
            self.__dict__['expand_'+name] = new.instancemethod(expand,self,Notifications)
            self.__dict__['minimize_'+name] = new.instancemethod(minimize,self,Notifications)
        
        self.builder.connect_signals(self)
        
        self.BLACS.mainbox.pack_start(self.toplevel,False,False,0)
        self.BLACS.mainbox.reorder_child(self.toplevel,1)
        
    def update_bar(self):
        for name,widgets in self.notifications.items():
            if widgets['minimized'].get_visible():
                self.notification_bar.show()
                return
        self.notification_bar.hide()
        
    def on_recompile_restart(self,widget):
        # Recompile the connection table
        
        # if compilation successful, restart BLACS
        
        pass        
    
    def close_all(self):
        for name in self.types:
            self.notifications[name]['minimized'].hide()
            self.notifications[name]['expanded'].hide()
        self.update_bar()
    
    def close(self,name):
        self.notifications[name]['minimized'].hide()
        self.notifications[name]['expanded'].hide()
        self.update_bar()
        
    def show(self,name):
        # Don't bother showing if it is already visible
        if self.notifications[name]['minimized'].get_visible() or self.notifications[name]['expanded'].get_visible():
            return
        self.notifications[name]['minimized'].hide()
        self.notifications[name]['expanded'].show()
        self.update_bar()
        
    def on_recompile_restart(self,widget):
        self.BLACS.recompile_connection_table(None)