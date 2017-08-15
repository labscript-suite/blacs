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

from qtutils import *

name = "GUI Theme"
module = "theme" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)


DEFAULT_STYLESHEET = """DigitalOutput {
    font-size: 12px;
    background-color: rgb(20,75,20,192);
    border: 1px solid rgb(20,75,20,128);
    border-radius: 3px;
    padding: 2px;
    color: #202020;
}

DigitalOutput:hover {
    background-color: #148214;
    border: None;
}

DigitalOutput:disabled{
   background-color: rgb(20,75,20,120);
   color: #505050;
}

DigitalOutput:checked {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #48dd48, stop: 1 #20ff20);
    border: 1px solid #8f8f91;
    color: #000000;
}

DigitalOutput:hover:checked {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #48dd48, stop: 1 #78ff78);
    border: 1px solid #8f8f91;
}

DigitalOutput:checked:disabled{
   background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #7ee77e, stop: 1 #62ff62);
   color: #606060;
}
 """


def is_default_stylesheet(stylesheet):
    """Return whether a stylesheet is the same as the default stylesheet, modulo whitespace"""

    def no_whitespace(s):
        return "".join(s.split())

    return no_whitespace(str(stylesheet)) == no_whitespace(DEFAULT_STYLESHEET) 


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
            # show centralwidget as a workaround to fix stylsheets
            # not beeing applied under PyQt5 on first draw
            self.BLACS['ui'].centralwidget.show()
            stylesheet_settings = self.BLACS['settings'].get_value(Setting,"stylesheet")
            self.BLACS['ui'].centralwidget.setStyleSheet(self.unmodified_stylesheet + stylesheet_settings)
        
    def set_menu_instance(self,menu):
        self.menu = menu
                
    def set_notification_instances(self,notifications):
        self.notifications = notifications
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        self.unmodified_stylesheet = self.BLACS['ui'].centralwidget.styleSheet()
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
        
        if 'stylesheet' not in self.data or not self.data['stylesheet']:
            # If it's absent or an empty string, use the default stylesheet:
            self.data['stylesheet'] = DEFAULT_STYLESHEET
    
    def on_set_green_button_theme(self):
        self.widgets['stylesheet'].appendPlainText(DEFAULT_STYLESHEET)
        
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
        stylesheet = str(self.widgets['stylesheet'].toPlainText())
        if not stylesheet.endswith('\n'):
            # This is a way to distinguish between an intentionally blank
            # stylesheet, and an empty string, which used to be what was
            # stored When the user had made no changes, which now we take to
            # imply that they want to use the default stylesheet:
            stylesheet += '\n'
        self.data['stylesheet'] = stylesheet
        data = self.data.copy()
        if is_default_stylesheet(stylesheet):
            # Only save if it is not the default stylesheet:
            del data['stylesheet']
        return data
        
    def close(self):
        self.widgets['example_button'].clicked.disconnect(self.on_set_green_button_theme)
        
    
