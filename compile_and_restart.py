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
from __future__ import division, unicode_literals, print_function, absolute_import

import os
import shutil

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from qtutils import *
import runmanager
from labscript_utils.qtwidgets.outputbox import OutputBox

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
        
        self.setLayout(self.ui.layout())
        self.resize(500, 300)
        self.show()
        self.setWindowTitle('Recompile connection table')
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
                shutil.move(self.tempfilename,self.output_path)
            except Exception as e:
                msg = ('Couldn\'t replace existing connection table h5 file. ' + 
                       'Is it open in another process? ' +
                       'error was:\n %s\n') % str(e)
                self.output_box.output(msg, red=True)
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
        if self.close_notification_func:
            self.close_notification_func()
        QTimer.singleShot(100, self.blacs['ui'].close)
        self.accept()
        self.blacs['set_relaunch'](True)
