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
from labscript_utils import check_version
import zprocess.locking
from blacs.plugins import PLUGINS_DIR, callback

# Need the version of labscript devices that has the wait monitors posting
# events to let us know when waits are completed:
# check_version('labscript_devices', '2.2.0', '3.0')

name = "Progress Bar"
module = "progress_bar" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

# The progress bar will update every UPDATE_INTERVAL seconds, or at the marker
# times, whichever is soonest after the last update:
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
        self.shot_start_time = None
        self.stop_time = None
        self.markers = None
        self.waits = None
        self.time_spent_waiting = None
        self.next_wait_index = None
        self.next_marker_index = None
        self.bar_text_prefix = None
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
        # Get the stop time of this shot, its time markers, and waits, if any:
        with h5py.File(h5_filepath, 'r') as f:
            self.stop_time = properties.get(f, self.master_pseudoclock, 'device_properties')['stop_time']
            try:
                self.markers = f['time_markers'][:]
                self.markers.sort(order=(bytes if PY2 else str)('time'))
            except KeyError:
                self.markers = None
            try:
                self.waits = f['waits'][:]
                self.waits.sort(order=(bytes if PY2 else str)('time'))
            except KeyError:
                self.waits = None

        # Initialise some variables and tell the mainloop to start:
        self.shot_start_time = time.time()
        self.time_spent_waiting = 0
        self.event_queue.put('start')

    @callback(priority=5)
    def on_science_over(self, h5_filepath):
        self.event_queue.put('stop', None)
        self.shot_start_time = None
        self.stop_time = None
        self.markers = None
        self.waits = None
        self.time_spent_waiting = None
        self.next_wait_index = None
        self.next_marker_index = None
        self.bar_text_prefix = None

    @inmain_decorator(True)
    def clear_bar(self):
        self.bar.setEnabled(False)
        self.bar.setFormat('No shot running')
        self.bar.setValue(0)

    def get_next_thing(self):
        """Figure out what's going to happen next: a wait, a time marker, or a regular
        update. Return a string saying which, and a float saying how long from now it
        will occur. If the thing has already happened but not been taken into account
        by our processing yet, then return zero for the time."""
        if self.waits is not None and self.next_wait_index < len(self.waits):
            next_wait_time = self.waits['time'][self.next_wait_index]
        else:
            next_wait_time = np.inf
        if self.markers is not None and self.next_marker_index < len(self.markers):
            next_marker_time = self.markers['time'][self.next_marker_index]
        assert self.shot_start_time is not None
        assert self.time_spent_waiting is not None
        labscript_time = time.time() - self.shot_start_time - self.time_spent_waiting
        next_update_time = labscript_time + UPDATE_INTERVAL
        if (next_update_time < next_wait_time) and (next_update_time < next_marker_time):
            return 'update', UPDATE_INTERVAL
        elif next_wait_time < next_marker_time:
            return 'wait', max(0, next_wait_time - labscript_time)
        else:
            return 'marker', max(0, next_marker_time - labscript_time)

    @inmain_decorator(True)
    def update_bar_style(self, marker=False, wait=False):
        assert not (marker and wait)
        if marker:
            label, _, color = self.markers[self.next_marker_index]
            self.bar_text_prefix = '[%s] ' % _ensure_str(label)
            palette = QtGui.QPalette()
            r, g, b = color[0]
        elif wait:
            label = self.waits[self.next_wait_index]['label']
            self.bar_text_prefix = '-%s- ' % _ensure_str(label)
            r, g, b = 128, 128, 128
        if marker or wait:
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
            self.bar_text_prefix = None
            # Default palette:
            self.bar.setPalette(QtWidgets.QApplication.style().standardPalette())

    @inmain_decorator(True)
    def update_bar_value(self):
        thinspace = u'\u2009'
        self.bar.setEnabled(True)
        labscript_time = time.time() - self.shot_start_time - self.time_spent_waiting
        value = int(round(labscript_time/self.stop_time * 100))
        self.bar.setValue(value)

        text = u'%.2f%ss / %.2f%ss (%%p%s%%)'
        text = text % (labscript_time, thinspace, self.stop_time, thinspace, thinspace)
        if self.bar_text_prefix is not None:
            text = self.bar_text_prefix + text
        self.bar.setFormat(text)

    def mainloop(self):
        # We delete shots in a separate thread so that we don't slow down the queue waiting on
        # network communication to acquire the lock, 
        running = False
        self.clear_bar()
        while True:
            try:
                if running:
                    # How long until the next thing of interest occurs, and what is it?
                    # It can be either a wait, a marker, or a regular update.
                    next_thing, timeout = self.get_next_thing()
                    try:
                        command = self.event_queue.get(timeout=timeout)
                    except Empty:
                        if next_thing == 'update':
                            self.update_bar_value()
                        if next_thing == 'marker':
                            self.update_bar_style(marker=True)
                            self.next_marker_index += 1
                            self.update_bar_value()
                        elif next_thing == 'wait':
                            self.update_bar_style(wait=True)
                            self.next_wait_index += 1
                            # Then wait!
                            raise NotImplementedError
                        continue
                else:
                    command = self.event_queue.get()
                if command == 'close':
                    break
                elif command == 'start':
                    running = True
                    self.time_spent_waiting = 0
                    self.update_bar_value()
                elif command == 'stop':
                    self.clear_bar()
                    running = False
                else:
                    raise ValueError(command)
            except Exception:
                logger.exception("Exception in mainloop, ignoring.")
    

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
        
    
