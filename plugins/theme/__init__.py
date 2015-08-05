#####################################################################
#                                                                   #
# /plugins/theme/__init__.py                                        #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import logging
import os
import subprocess
import sys

if 'PySide' in sys.modules.copy():
    from PySide.QtCore import *
    from PySide.QtGui import *
else:
    from PyQt4.QtCore import *
    from PyQt4.QtGui import *

from qtutils import *

name = "GUI Theme"
module = "theme" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

class Plugin(object):
    def __init__(self,initial_settings):
        self.menu = None
        self.notifications = {}
        self.BLACS = None
        self.initial_settings = initial_settings
        
    def get_menu_class(self):
        return None
        
    def get_notification_classes(self):
        return []
        
    def get_setting_classes(self):
        return [Setting]
        
    def get_callbacks(self):
        return {'settings_changed':self.update_stylesheet}
        
    def update_stylesheet(self):
        if self.BLACS is not None:
            stylesheet_settings = self.BLACS['settings'].get_value(Setting,"stylesheet")
            QApplication.instance().setStyleSheet(stylesheet_settings)
        
    def set_menu_instance(self,menu):
        self.menu = menu
                
    def set_notification_instances(self,notifications):
        self.notifications = notifications
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        self.update_stylesheet()
    
    def get_save_data(self):
        return {}
    
    def close(self):
        pass
        
    
class Setting(object):
    name = name

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        if 'stylesheet' not in self.data:
            self.data['stylesheet'] = ''
    
    def on_set_green_button_theme(self):
        self.widgets['stylesheet'].appendPlainText("""DigitalOutput {
    background-color: rgb(20,75,20,192);
    border: 1px solid rgb(20,75,20,128);
    border-radius: 3px;
    padding: 4px;
}

DigitalOutput:hover {
    background-color: #148214;
    border: None;
    border-radius: 3px;
}
 
DigitalOutput:checked {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #48dd48, stop: 1 #20ff20);
    border: 1px solid #8f8f91;
    border-radius: 3px;
}
 
DigitalOutput:hover:checked {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #48dd48, stop: 1 #78ff78);
    border: 1px solid #8f8f91;
    border-radius: 3px;
}
 """)
        
    # Create the page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'theme.ui'))
        
        # restore current stylesheet
        ui.stylesheet_text.setPlainText(self.data['stylesheet'])
        ui.example_button.clicked.connect(self.on_set_green_button_theme)
        
        # save reference to widget
        self.widgets = {}
        self.widgets['stylesheet'] = ui.stylesheet_text
        self.widgets['example_button'] = ui.example_button
        
        return ui,None
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        self.data['stylesheet'] = str(self.widgets['stylesheet'].toPlainText())
        return self.data
        
    def close(self):
        self.widgets['example_button'].clicked.disconnect(self.on_set_green_button_theme)
        
    
