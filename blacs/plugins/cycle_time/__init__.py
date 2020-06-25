#####################################################################
#                                                                   #
# /plugins/cycle_time/__init__.py                                   #
#                                                                   #
# Copyright 2017, Monash Univiersity and contributors               #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
from queue import Queue, Empty
from time import monotonic
import time
import logging
import os

from qtutils import UiLoader, inmain, inmain_decorator

import labscript_utils.h5_lock
import h5py

from qtutils.qt.QtGui import QIcon
from qtutils.qt.QtCore import QSize

from blacs.plugins import PLUGINS_DIR, callback
from labscript_utils.properties import get_attribute

name = "cycle_time"
module = "cycle_time" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)


class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.time_of_last_shot = None
        self.queue = Queue()
        self.target_cycle_time = None
        self.delay_after_programming = None
        self.next_target_cycle_time = None
        self.next_delay_after_programming = None

    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        self.queue_manager = self.BLACS['experiment_queue']

    def get_save_data(self):
        return {}
    
    def get_callbacks(self):
        return {
            'pre_transition_to_buffered': self.pre_transition_to_buffered,
            'science_starting': self.science_starting,
        }
        
    def _abort(self):
        self.queue.put('abort')

    @callback(priority=100) # this callback should run after all other callbacks.
    def pre_transition_to_buffered(self, h5_filepath):
        # Delay according to the settings of the previously run shot, and save the
        # settings for the upcoming shot:
        self.target_cycle_time = self.next_target_cycle_time
        self.delay_after_programming = self.next_delay_after_programming

        with h5py.File(h5_filepath, 'r') as f:
            try:
                group = f['shot_properties']
            except KeyError:
                # Nothing for us to do
                return
            self.next_target_cycle_time = get_attribute(group, 'target_cycle_time')
            self.next_delay_after_programming = get_attribute(
                group, 'cycle_time_delay_after_programming'
            )

        if not self.delay_after_programming:
            self.do_delay(h5_filepath)

    # this callback should run before the progress bar plugin, but after all other
    # callbacks. The priority should be set accordingly.
    @callback(priority=100) 
    def science_starting(self, h5_filepath):
        if self.delay_after_programming:
            self.do_delay(h5_filepath)

    def do_delay(self, h5_filepath):
        if self.target_cycle_time is not None and self.time_of_last_shot is not None:
            # Wait until it has been self.target_cycle_time since the start of the last
            # shot. Otherwise, return immediately.
            deadline = self.time_of_last_shot + self.target_cycle_time
            inmain(self.BLACS['ui'].queue_abort_button.clicked.connect, self._abort)
            # Store the current queue manager status, to restore it after we are done:
            previous_status = self.queue_manager.get_status()
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self.queue_manager.set_status(
                    'Waiting {:.1f}s for target cycle time'.format(remaining),
                    h5_filepath,
                )
                try:
                    self.queue.get(timeout=remaining % 0.1)
                    break # Got an abort
                except Empty:
                    continue
            # Disconnect from the abort button:
            inmain(self.BLACS['ui'].queue_abort_button.clicked.disconnect, self._abort)
            # Restore previous_status:
            self.queue_manager.set_status(previous_status, h5_filepath)

        self.time_of_last_shot = monotonic()

    # The rest of these are boilerplate:
    def close(self):
        pass
    
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
        
    
