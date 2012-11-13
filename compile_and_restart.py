import sys
import os
import subprocess
from Queue import Queue

import gtk
import gobject

import runmanager
from subproc_utils.gtk_components import OutputBox

class CompileAndRestart(object):
    def __init__(self, blacs, globals_files,connection_table_labscript, output_path):
        self.globals_files = globals_files
        self.labscript_file = connection_table_labscript
        self.output_path = output_path
        self.tempfilename = self.output_path.strip('.h5')+'.temp.h5'
        self.blacs = blacs
        
        builder = gtk.Builder()
        builder.add_from_file('compile_and_restart.glade')
        builder.connect_signals(self)
        
        self.toplevel = builder.get_object('toplevel')
        self.label_compiling = builder.get_object('label_compiling')
        self.label_success = builder.get_object('label_success')
        self.label_failure = builder.get_object('label_failure')
        self.button_compile = builder.get_object('button_compile')
        self.button_restart = builder.get_object('button_restart')
        self.button_cancel = builder.get_object('button_cancel')

        output_parent = builder.get_object('output_parent')
        
        self.output_box = OutputBox(output_parent)
        
        self.toplevel.show()

        self.compile()
        
    def on_activate_default(self,window):
        if self.button_restart.get_sensitive():
            self.restart()
        elif self.button_compile.get_sensitive():
            self.compile()

    def on_compile_clicked(self, button):
        self.compile()
        
    def on_restart_clicked(self,button):
        self.restart()
    
    def on_cancel_clicked(self,widget):
        self.toplevel.destroy()
    
    def on_window_delete(self,window,event):
        if self.button_cancel.get_sensitive():
            return False
        else:
            return True
                
    def compile(self):
        self.button_compile.set_sensitive(False)
        self.button_cancel.set_sensitive(False)
        self.label_compiling.set_visible(True)
        self.label_success.set_visible(False)
        self.label_failure.set_visible(False)
        self.button_restart.set_sensitive(False)
        runmanager.compile_labscript_with_globals_files_async(self.labscript_file,
            self.globals_files, self.tempfilename, self.output_box.port, self.finished_compiling)
            
    def finished_compiling(self, success):
        with gtk.gdk.lock:
            self.button_compile.set_sensitive(True)
            self.button_cancel.set_sensitive(True)
            self.label_compiling.set_visible(False)
            if success:
                self.button_restart.set_sensitive(True)
                self.label_success.set_visible(True)
                try:
                    os.remove(self.output_path)
                except OSError:
                     # File doesn't exist, no need to delete then:
                    pass
                try:
                    os.rename(self.tempfilename,self.output_path)
                except OSError:
                    self.output_box.queue.put(['stderr','Couldn\'t replace existing connection table h5 file. Is it open in another process?'])
                    self.label_failure.set_visible(True)
                    self.label_success.set_visible(False)
                    self.button_restart.set_sensitive(False)
                    os.remove(self.tempfilename)
            else:
                self.label_failure.set_visible(True)
                self.button_restart.set_sensitive(False)
                try:
                    os.remove(self.tempfilename)
                except Exception:
                    pass
                
    def restart(self):
        gobject.timeout_add(100, self.blacs.destroy)
        self.toplevel.destroy()
        gtk.quit_add(0,self.relaunch)
        
    def relaunch(self):
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)
        
if __name__ == '__main__':
    gtk.threads_init()
    globals_file = '/home/bilbo/labconfig/bilbo-laptop_calibrations.h5'
    labscript_file = '/home/bilbo/labconfig/bilbo-laptop.py'
    output_path = '/home/bilbo/Desktop/pythonlib/BLACS/connectiontables/bilbo-laptop.h5'
    compile_and_restart = CompileAndRestart(None, [], labscript_file, output_path)
    gtk.main()
