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

from qtutils import UiLoader, inmain, inmain_decorator
from qtutils.qt import QtGui, QtWidgets, QtCore

import labscript_utils.h5_lock
import h5py

from labscript_utils.shared_drive import path_to_agnostic
import labscript_utils.properties as properties
import zprocess.locking
from blacs.plugins import PLUGINS_DIR, callback

name = "Progress Bar"
module = "progress_bar" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

# The progress bar will update every UPDATE_INTERVAL seconds, or at the marker
# times, whichecer is soonest after the last update:
UPDATE_INTERVAL = 0.2


class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.bar = QtWidgets.QProgressBar()
        self.bar.setEnabled(False)
        self.event_queue = Queue()
        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        self.master_pseudoclock = None
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        # Add the progress bar to the BLACS gui:
        BLACS['ui'].queue_status_verticalLayout.addWidget(self.bar)
        # We need to know the name of the master pseudoclock so we can look up
        # the duration of each shot:
        self.master_pseudoclock = self.BLACS['experiment_queue'].master_pseudoclock

    def get_save_data(self):
        return {}
    
    def get_callbacks(self):
        return {'science_over': self.on_science_over,
                'science_starting': self.on_science_starting}
        
    @callback(priority=100)
    def on_science_starting(self, h5_filepath):
        
        # Get the stop time of this shot:
        with h5py.File(h5_filepath) as f:
            stop_time = properties.get(f, self.master_pseudoclock, 'device_properties')['stop_time']

        # Enable the bar:
        inmain(self.bar.setEnabled, True)


    @callback(priority=5)
    @inmain_decorator(True)
    def on_science_over(self, h5_filepath):
        # Hide the bar
        self.bar.setEnabled(False)

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
        
    
