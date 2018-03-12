#####################################################################
#                                                                   #
# /compile_and_restart.py                                           #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import os

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from qtutils import *
import runmanager
from qtutils.outputbox import OutputBox

from blacs import BLACS_DIR


class CompileAndRestart(QDialog):
    def __init__(self, blacs, globals_files,connection_table_labscript, output_path, close_notification_func=None):
        QDialog.__init__(self,blacs['ui'])
        self.setAttribute(Qt.WA_DeleteOnClose, True) # make sure the dialog is deleted when the window is closed
        
        self.globals_files = globals_files
        self.labscript_file = connection_table_labscript
        self.output_path = output_path
        self.tempfilename = self.output_path.strip('.h5')+'.temp.h5'
        self.blacs = blacs
        self.close_notification_func = close_notification_func
        
        self.ui = UiLoader().load(os.path.join(BLACS_DIR, 'compile_and_restart.ui'))
        self.output_box = OutputBox(self.ui.verticalLayout)       
        self.ui.restart.setEnabled(False)
        
        # Connect buttons
        self.ui.restart.clicked.connect(self.restart)
        self.ui.compile.clicked.connect(self.compile)
        self.ui.cancel.clicked.connect(self.reject)
        
        self.ui.setParent(self)
        self.ui.show()        
        self.show()

        self.compile()

    def closeEvent(self,event):
        if not self.ui.cancel.isEnabled():        
            event.ignore()            
        else:
            event.accept()
    
    def on_activate_default(self,window):
        if self.button_restart.get_sensitive():
            self.restart()
        elif self.button_compile.get_sensitive():
            self.compile()
                
    def compile(self):
        self.ui.compile.setEnabled(False)
        self.ui.cancel.setEnabled(False)
        self.ui.restart.setEnabled(False)
        msg = 'Recompiling connection table'
        self.ui.label.setText(msg)
        self.output_box.output(msg + '\n')
        runmanager.compile_labscript_with_globals_files_async(self.labscript_file,
            self.globals_files, self.tempfilename, self.output_box.port, self.finished_compiling)
    
    @inmain_decorator(True)    
    def finished_compiling(self, success):
        self.ui.compile.setEnabled(True)
        self.ui.cancel.setEnabled(True)
        if success:
            try:
                os.remove(self.output_path)
            except OSError:
                 # File doesn't exist, no need to delete then:
                pass
            try:
                os.rename(self.tempfilename,self.output_path)
            except OSError:
                self.output_box.output('Couldn\'t replace existing connection table h5 file. Is it open in another process?\n', red=True)
                self.ui.label.setText('Compilation failed.')
                self.ui.restart.setEnabled(False)
                os.remove(self.tempfilename)
            else:
                self.ui.restart.setEnabled(True)
                self.ui.cancel.setEnabled(False)
                msg = 'Compilation succeeded, restart when ready'
                self.ui.label.setText(msg)
                self.output_box.output(msg + '\n')
        else:
            self.ui.restart.setEnabled(False)
            msg = 'Compilation failed. Please fix the errors in the connection table (python file) and try again'
            self.ui.label.setText(msg)
            self.output_box.output(msg + '\n')
            try:
                os.remove(self.tempfilename)
            except Exception:
                pass
                
    def restart(self):
        #gobject.timeout_add(100, self.blacs.destroy)
        if self.close_notification_func:
            self.close_notification_func()
        QTimer.singleShot(100, self.blacs['ui'].close)
        self.accept()        
        self.blacs['set_relaunch'](True)
        
        #self.blacs.qt_application.aboutToQuit.connect(self.relaunch)
        #gtk.quit_add(0,self.relaunch)
    
        
if __name__ == '__main__':
    #gtk.threads_init()
    globals_file = '/home/bilbo/labconfig/bilbo-laptop_calibrations.h5'
    labscript_file = '/home/bilbo/labconfig/bilbo-laptop.py'
    output_path = '/home/bilbo/Desktop/pythonlib/BLACS/connectiontables/bilbo-laptop.h5'
    #compile_and_restart = CompileAndRestart(None, [], labscript_file, output_path)
    #gtk.main()
