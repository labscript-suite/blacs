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

import logging
import os
import subprocess
import threading
import sys
import time

import numpy as np

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
UPDATE_INTERVAL = 0.05


def _ensure_str(s):
    """convert bytestrings and numpy strings to python strings"""
    return s.decode() if isinstance(s, bytes) else str(s)


def black_has_good_contrast(r, g, b):
    """Return whether black text or white text would have better contrast on a
    background of the given colour, according to W3C recommendations (see
    https://www.w3.org/TR/WCAG20/). Return True for black or False for white"""
    cs = []
    for c in r, g, b:
        c = c / 255.0
        if c <= 0.03928:
            c = c/12.92
        else:
            c = ((c+0.055)/1.055) ** 2.4
        cs.append(c)
    r, g, b = cs
    L = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return L > np.sqrt(1.05 * 0.05) - 0.05


class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.bar = QtWidgets.QProgressBar()
        self.event_queue = Queue()
        self.master_pseudoclock = None
        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        # Add the progress bar to the BLACS gui:
        BLACS['ui'].queue_status_verticalLayout.insertWidget(0, self.bar)
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
        
        # Get the stop time of this shot and its time markers, if any:
        with h5py.File(h5_filepath, 'r') as f:
            stop_time = properties.get(f, self.master_pseudoclock, 'device_properties')['stop_time']
            try:
                time_markers = f['time_markers'][:]
                time_markers.sort(order=(bytes if PY2 else str)('time'))
            except KeyError:
                time_markers = None

        # Tell the mainloop what's up:
        self.event_queue.put(['start', (stop_time, time_markers)])
        
    @callback(priority=5)
    def on_science_over(self, h5_filepath):
        self.event_queue.put(['stop', None])

    @inmain_decorator(True)
    def update_bar(self, shot_start_time, stop_time, time_markers):
        """Update the progress bar and return when the next update should occur"""
        thinspace = u'\u2009'
        self.bar.setEnabled(True)
        time_elapsed = time.time() - shot_start_time

        value = int(round(time_elapsed/stop_time * 100))
        self.bar.setValue(value)

        text = u'%.2f%ss / %.2f%ss (%%p%s%%)'
        text = text % (time_elapsed, thinspace, stop_time, thinspace, thinspace)
        
        if time_markers is not None and len(time_markers) > 0:
            # What marker are we up to?
            marker_index = np.searchsorted(time_markers['time'], time_elapsed) - 1
            if marker_index >= 0:
                label, t, color = time_markers[marker_index]
                text = '[%s] ' % _ensure_str(label) + text
                palette = QtGui.QPalette()
                r, g, b = color[0]
                palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(r, g, b))
                # Ensure the colour of the text on the filled in bit of the progress
                # bar has good contrast:
                if black_has_good_contrast(r, g, b):
                    bg_color = QtGui.QColor(0, 0, 0)
                else:
                    bg_color = QtGui.QColor(255, 255, 255)
                palette.setColor(QtGui.QPalette.HighlightedText, bg_color)
                self.bar.setPalette(palette)
            else:
                self.bar.setPalette(QtWidgets.QApplication.style().standardPalette())

        self.bar.setFormat(text)

        return UPDATE_INTERVAL

    @inmain_decorator(True)
    def clear_bar(self):
        self.bar.setEnabled(False)
        self.bar.setFormat('No shot running')
        self.bar.setValue(0)

    def mainloop(self):
        # We delete shots in a separate thread so that we don't slow down the queue waiting on
        # network communication to acquire the lock, 
        timeout = None
        self.clear_bar()
        while True:
            try:
                try:
                    command, data = self.event_queue.get(timeout=timeout)
                except Empty:
                    timeout = self.update_bar(shot_start_time, stop_time, time_markers)
                    continue
                if command == 'close':
                    break
                elif command == 'start':
                    shot_start_time = time.time()
                    stop_time, time_markers = data
                    timeout = self.update_bar(shot_start_time, stop_time, time_markers)
                elif command == 'stop':
                    timeout = None
                    self.clear_bar()
                else:
                    raise ValueError(event)
            except Exception:
                logger.exception("Exception in repeated shot deletion loop, ignoring.")
    

    def close(self):
        self.event_queue.put(['close', None])
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
        
    
