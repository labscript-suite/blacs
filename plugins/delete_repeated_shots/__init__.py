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

import logging
import os
import subprocess
import threading
import sys
from Queue import Queue

from qtutils import UiLoader

from labscript_utils.shared_drive import path_to_agnostic
import zprocess.locking
from blacs.plugins import PLUGINS_DIR

name = "Delete repeated shots"
module = "delete_repeated_shots" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)


KEEP_ALL_SHOTS = 0

class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.ui = None
        self.n_shots_to_keep = initial_settings.get('n_shots_to_keep', KEEP_ALL_SHOTS)
        self.delete_queue = initial_settings.get('delete_queue', [])
        self.event_queue = Queue()
        self.delete_queue_lock = threading.Lock()
        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS

        # Add our controls to the BLACS UI:
        self.ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'controls.ui'))
        BLACS['ui'].queue_controls_frame.layout().addWidget(self.ui)

        # Restore settings to the GUI controls:
        self.ui.spinBox.setValue(self.n_shots_to_keep)

        # Connect signals:
        self.ui.spinBox.valueChanged.connect(self.on_spinbox_value_changed)
        self.ui.reset_button.clicked.connect(self.on_reset_button_clicked)
        BLACS['ui'].queue_repeat_button.toggled.connect(self.ui.setEnabled)

        # Our control is only enabled when repeat mode is active:
        self.ui.setEnabled(BLACS['ui'].queue_repeat_button.isChecked())

    def on_spinbox_value_changed(self, value):
        with self.delete_queue_lock:
            self.n_shots_to_keep = value
            # If the user reduces the number of shots to keep, but we had a
            # larger list of shots awaiting deletion, remove shots from the
            # deletion queue (without deleting them) until the queue is the
            # same size as the number of shots we are now keeping. This means
            # that if we set to keep 100 shots, and then we go ahead and run a
            # hundred shots, if we then set it to keep 5 shots it won't delete
            # the 95 oldest shots in the queue. Rather it will only delete the
            # most recent 5 (and not immediately - over the next 5 shots).
            while len(self.delete_queue) > self.n_shots_to_keep:
                self.delete_queue.pop(0)

    def on_reset_button_clicked(self):
        self.ui.spinBox.setValue(KEEP_ALL_SHOTS)

    def get_save_data(self):
        return {'n_shots_to_keep': self.n_shots_to_keep,
                'delete_queue': self.delete_queue}
    
    def get_callbacks(self):
        return {'shot_complete': self.on_shot_complete}
        
    def on_shot_complete(self, h5_filepath):

        # If we're keeping all shots, then there's nothing to do here:
        if self.n_shots_to_keep == KEEP_ALL_SHOTS:
            return

        # Is the file a repeated shot?
        basename, ext = os.path.splitext(os.path.basename(h5_filepath))
        if '_rep' in basename and ext == '.h5':
            repno = basename.split('_rep')[-1]
            try:
                int(repno)
            except ValueError:
                # not a rep:
                return
            else:
                # Yes, it is a rep. Queue it for deletion:
                self.delete_queue.append(h5_filepath)
                self.event_queue.put('shot complete')

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
        
    