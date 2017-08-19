#####################################################################
#                                                                   #
# /virtual_devices/shutter.py                                       #
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
from labscript_utils import PY2
if PY2:
    str = unicode

from hardware_interfaces.output_types.DO import *
from hardware_interfaces.output_types.AO import *
import gobject
import pygtk
import gtk

class shutter(object):

    def __init__(self,do_array):
    
        # Load the glade file, and build the interface
        self.builder = gtk.Builder()
        self.builder.add_from_file('virtual_Devices/shutter.glade')
        
        # Save the topleve object in the tab variable.
        # This is IMPORTANT, as whatever is in self.tab is appended to the notebook
        # The toplevel item in your glade file should be a hBox or a vBox, and it's name
        # (under the general tab in glade) should be toplevel
        self.tab = self.builder.get_object('toplevel')
        
        # Save the DO objects in an array for later use
        self.do_array = do_array
        
        # Capabilities definitions (internal class use only)
        self.num_shutters = 4
        
        #programatically rename GUI based on do_array
        self.digital_widgets = []
        for i in range(0,self.num_shutters):
            # save the digital toggle widget in a list, so we can access it later
            self.digital_widgets.append(self.builder.get_object("do_toggle_"+str(i+1)))
            
            # Programatically change the labels on each of our toggle widgets, so they match
            # those stored in the DO object (both real hardware name, and physical name)
            temp1 = self.builder.get_object("do_channel_label_"+str(i+1))
            temp2 = self.builder.get_object("do_name_label_"+str(i+1))
            temp1.set_text(self.do_array[i].hardware_name)
            temp2.set_text(self.do_array[i].real_name)
            
            # register callback function
            # This function is called when the digital output is updated somewhere else in the program
            self.do_array[i].add_callback(self.update_value)
            
        # Need to connect gtk GUI signals!
        self.builder.connect_signals(self)
        
    def update_value(self,output):        
        # find the digital out in our array, so we know which GUI element to change
        channel = None
        for i in range(0,self.num_shutters):
            if output == self.do_array[i]:
                channel = i
                break
                
        # if the GUI element is not in the correct state, fix it!
        if self.digital_widgets[channel].get_active() != output.state:
            self.digital_widgets[channel].set_active(output.state)
    
    # This is the function called when the buttons are toggled
    # The function name is defined within the glade file, under signals, for each button
    def update_shutter(self,widget):
        # find the widget in our array, which has been toggled
        for i in range(0,self.num_shutters):
            if self.digital_widgets[i] == widget:
                # send to update signal to the DO object, which will then trigger 
                # update calls for matching GUI objects in other parts of the program
                self.do_array[i].update_value(widget.get_active())
                return
                