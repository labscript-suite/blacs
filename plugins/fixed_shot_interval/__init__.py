#####################################################################
#                                                                   #
# /plugins/delete_repeated_shots/__init__.py                        #
#                                                                   #
# Copyright 2017, JQI                                               #
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
    from Queue import Queue
else:
    from queue import Queue

import logging
import os
import subprocess
import threading
import sys

from qtutils import UiLoader

from labscript_utils.shared_drive import path_to_agnostic
import zprocess.locking
from blacs.plugins import PLUGINS_DIR, callback

name = "fixed shot interval"
module = "fixed_shot_interval" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

NO_FIXED_INTERVAL = 0

class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.ui = None
        self.interval = initial_settings.get('interval', NO_FIXED_INTERVAL)
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS

        # Add our controls to the BLACS UI:
        self.ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'controls.ui'))
        BLACS['ui'].queue_controls_frame.layout().addWidget(self.ui)

        # Restore settings to the GUI controls:
        self.ui.spinBox.setValue(self.interval)

        # Connect signals:
        self.ui.spinBox.valueChanged.connect(self.on_spinbox_value_changed)
        self.ui.reset_button.clicked.connect(self.on_reset_button_clicked)


    def on_spinbox_value_changed(self, value):
        self.interval = value

    def on_reset_button_clicked(self):
        self.ui.spinBox.setValue(NO_FIXED_INTERVAL)

    def get_save_data(self):
        return {'interval': self.interval}
    
    def get_callbacks(self):
        return {'shot_complete': self.on_shot_complete}
        
    @callback(priority=100) # this callback should run after all other callbacks.
    def on_shot_complete(self, h5_filepath):
        pass

    def mainloop(self):
        # We delete shots in a separate thread so that we don't slow down the queue waiting on
        # network communication to acquire the lock, 
        while True:
            try:
                event = self.event_queue.get()
                if event == 'close':
                    break
                elif event == 'shot complete':
                    while len(self.delete_queue) > self.n_shots_to_keep:
                        with self.delete_queue_lock:
                            h5_filepath = self.delete_queue.pop(0)
                        # Acquire a lock on the file so that we don't
                        # delete it whilst someone else has it open:
                        with zprocess.locking.Lock(path_to_agnostic(h5_filepath)):
                            try:
                                os.unlink(h5_filepath)
                                logger.info("Deleted repeated shot file %s" % h5_filepath)
                            except OSError:
                                logger.exception("Couldn't delete shot file %s" % h5_filepath)
                else:
                    raise ValueError(event)
            except Exception:
                logger.exception("Exception in repeated shot deletion loop, ignoring.")
    

    def close(self):
        self.event_queue.put('close')
        self.mainloop_thread.join()


    # The rest of these are boilerplate:
    def get_menu_class(self):
        return None
        
    def get_notification_classes(self):
        return []
        
    def get_setting_classes(self):
        return []
    
    def set_menu_instance(self, menu):
        self.menu = menu
        
    def set_notification_instances(self, notifications):
        self.notifications = notifications
        
    
