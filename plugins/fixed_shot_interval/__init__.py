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
    from Queue import Queue, Empty
else:
    from queue import Queue, Empty
import time
import logging
import os

from qtutils import UiLoader, inmain, inmain_decorator

from qtutils.qt.QtGui import QIcon
from qtutils.qt.QtCore import QSize

from blacs.plugins import PLUGINS_DIR, callback

name = "fixed shot interval"
module = "fixed_shot_interval" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

NO_FIXED_INTERVAL = 0

icon_names = {'waiting': ':/qtutils/fugue/hourglass',
              'good': ':/qtutils/fugue/tick',
              'bad': ':/qtutils/fugue/exclamation-red', 
              '': ':/qtutils/fugue/status-offline'}

tooltips = {'waiting': 'Waiting...',
            'good': 'Shot completed in required time',
            'bad': 'Shot took too long for target interval',
            '': 'No status to report'}


class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.ui = None
        self.interval = initial_settings.get('interval', NO_FIXED_INTERVAL)
        self.time_of_last_shot = None
        self.queue = None

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
        return {'pre_transition_to_buffered': self.pre_transition_to_buffered}
        
    def _abort(self):
        self.queue.put('abort')

    @inmain_decorator(True)
    def _update_icon(self, status):
        icon = QIcon(icon_names[status])
        pixmap = icon.pixmap(QSize(16, 16))
        tooltip = tooltips[status]
        self.ui.icon.setPixmap(pixmap)
        self.ui.icon.setToolTip(tooltip)

    @callback(priority=100) # this callback should run after all other callbacks.
    def pre_transition_to_buffered(self, h5_filepath):
        # Get the queue manager so we can call get_status()
        import __main__
        queue_manager = __main__.app.queue

        if self.interval != 0 and self.time_of_last_shot is not None:
            # Wait until it has been self.interval since the start of the last
            # shot. Otherwise, run the shot immediately.
            timeout = self.time_of_last_shot + self.interval - time.time()
            if timeout <= 0:
                self._update_icon('bad')
            else:
                # A queue so we can detect an abort
                self.queue = Queue()
                # Connect to the abort button so we can stop waiting if the user
                # clicks abort.
                inmain(self.BLACS['ui'].queue_abort_button.clicked.connect, self._abort)
                # Store the current queue manager status, to restore it after we are done:
                previous_status = queue_manager.get_status()
                queue_manager.set_status('Waiting for target shot interval', h5_filepath)
                try:
                    self._update_icon('waiting')
                    self.queue.get(timeout=timeout)
                    self._update_icon('')
                except Empty:
                    self._update_icon('good')
                # Disconnect from the abort button:
                inmain(self.BLACS['ui'].queue_abort_button.clicked.disconnect, self._abort)
                # Restore previous_status:
                queue_manager.set_status(previous_status, h5_filepath)
        else:
            self._update_icon('')

        self.time_of_last_shot = time.time()

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
        
    
