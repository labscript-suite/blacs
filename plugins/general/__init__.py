#####################################################################
#                                                                   #
# /plugins/general/__init__.py                                      #
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

from qtutils import UiLoader
    
class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.BLACS = None
        
    def get_menu_class(self):
        return None
        
    def get_notification_classes(self):
        return []
        
    def get_setting_classes(self):
        return [Setting]
        
    def get_callbacks(self):
        pass
        
    def set_menu_instance(self,menu):
        self.menu = menu
        
    def set_notification_instances(self,notifications):
        self.notifications = notifications

    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        
    def get_save_data(self):
        return {}
        
    def close(self):
        pass
        
# class Menu(object):
    # pass
    
# class Notification(object):
    # pass


class Setting(object):
    name = "General"

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        self.var_list = [('ct_editor','','text','setText')]
        for var in self.var_list:
            if var[0] not in self.data:
                data[var[0]] = var[1]
        
    # Create the GTK page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'general.ui'))
        
        # get the widgets!
        self.widgets = {}
        for var in self.var_list:            
            self.widgets[var[0]] = getattr(ui,var[0])
            getattr(self.widgets[var[0]],var[3])(self.data[var[0]])
        
        return ui,None
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        # transfer the contents of the list store into the data store, and then return the data store
        for var in self.var_list:
            # TODO: Make more general than forcing type to string
            self.data[var[0]] = str(getattr(self.widgets[var[0]],var[2])())
        
        return self.data
        
    def close(self):
        pass
        
    
