#####################################################################
#                                                                   #
# /standalone_device.py                                             #
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

import gtk
import sys
import socket
from labscript_utils.labconfig import LabConfig
# Connection Table Code
from connections import ConnectionTable

from hardware_interfaces import *
for device in device_list:    
    exec("from hardware_interfaces."+device+" import "+device)
    
    
if __name__ == "__main__":
    gtk.gdk.threads_init()
    
    # Load the experiment config file, and verify that the necessary parameters are there"
    config_path = r'C:\labconfig\\'+socket.gethostname()+r'.ini'
    settings_path = r'C:\labconfig\\'+socket.gethostname()+r'_BLACS.h5'
    required_config_params = {"DEFAULT":["experiment_name"],
                              "programs":["text_editor",
                                          "text_editor_arguments",
                                         ],
                              "paths":["shared_drive",
                                       "connection_table_h5",
                                       "connection_table_py",                                       
                                      ],
                              "ports":["BLACS"],
                             }
    exp_config = LabConfig(config_path,required_config_params)    
    
    #
    # Load Connection Table
    #
    # Get file paths (used for file watching later)           
    connection_table_h5file = exp_config.get('paths','connection_table_h5')
    connection_table_labscript = exp_config.get('paths','connection_table_py')
    
    # Create Connection Table object
    try:
        connection_table = ConnectionTable(connection_table_h5file)
    except Exception as e:
        print(e)
        dialog = gtk.MessageDialog(None,gtk.DIALOG_MODAL,gtk.MESSAGE_ERROR,gtk.BUTTONS_NONE,"The connection table in '%s' is not valid. Please check the compilation of the connection table for errors\n\n"%connection_table_h5file)
             
        dialog.run()
        dialog.destroy()
        sys.exit("Invalid Connection Table")
        
    
    window = gtk.Window()
    notebook = gtk.Notebook()
    window.add(notebook)
    
    ni_card = ni_pci_6733(object,notebook,{"device_name":"ni_pci_6733_0", "connection_table":connection_table})
    
    notebook.show()
    window.show()
    
    with gtk.gdk.lock:
        gtk.main()