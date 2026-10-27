#####################################################################
#                                                                   #
# /plugins/progress_bar/__init__.py                                 #
#                                                                   #
# Copyright 2018, Christopher Billington                            #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
import logging
import math
import os
import subprocess
import threading
import sys
import time
from queue import Queue

import numpy as np

from qtutils import UiLoader, inmain_later
from qtutils.icons import Icon
from qtutils.qt import QtGui, QtWidgets, QtCore

import labscript_utils.h5_lock
import h5py

import labscript_utils.properties as properties
from labscript_utils.connections import ConnectionTable
from zprocess import TimeoutError
from labscript_utils.ls_zprocess import Event
from blacs.plugins import PLUGINS_DIR, callback

name = "Progress Bar"
module = "progress_bar" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

# The progress bar will update every UPDATE_INTERVAL seconds, or at the marker
# times, whichever is soonest after the last update:
UPDATE_INTERVAL = 0.02
BAR_MAX = 1000

# Duration of each wait on the bar when the wait monitor does not post wait completed
# events:
UNMONITORED_WAIT_DURATION = 0.1

def _ensure_str(s):
    """convert bytestrings and numpy strings to python strings"""
    return s.decode() if isinstance(s, bytes) else str(s)


def black_has_good_contrast(r, g, b):
    """Return whether black text or white text would have better contrast on a
    background of the given colour, according to W3C recommendations (see
    https://www.w3.org/TR/WCAG20/). Return True for black or False for
    white"""
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
        self.command_queue = Queue()
        self.master_pseudoclock = None
        self.shot_start_time = None
        self.stop_time = None
        self.markers = None
        self.waits = None
        self.time_spent_waiting = None
        self.next_wait_index = None
        self.next_marker_index = None
        self.bar_text_prefix = None
        self.h5_filepath = None
        self.wait_start_time = None
        self.next_thing = None
        self.timer = None
        self.wait_completed_events_supported = False
        self.wait_completed = Event('wait_completed', role='wait')
        self.command_thread = threading.Thread(target=self.command_loop)
        self.command_thread.daemon = True

    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        self.ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'controls.ui'))
        self.ui.wait_warning.setIcon(Icon(':/qtutils/fugue/clock--exclamation'))
        self.bar = self.ui.bar
        self.style = QtWidgets.QStyleFactory.create('Fusion')
        if self.style is None:
            # If we're on Qt4, fall back to Plastique style:
            self.style = QtWidgets.QStyleFactory.create('Plastique')
        if self.style is None:
            # Not sure what's up, but fall back to app's default style:
            self.style = QtWidgets.QApplication.style()
        self.bar.setStyle(self.style)
        self.bar.setMaximum(BAR_MAX)
        self.bar.setAlignment(QtCore.Qt.AlignCenter)
        # Add our controls to the BLACS gui:
        BLACS['ui'].queue_status_verticalLayout.insertWidget(0, self.ui)
        # We need to know the name of the master pseudoclock so we can look up
        # the duration of each shot:
        self.master_pseudoclock = self.BLACS['experiment_queue'].master_pseudoclock

        # Check if the wait monitor device, if any, supports wait completed events:
        with h5py.File(self.BLACS['connection_table_h5file'], 'r') as f:
            if 'waits' in f:
                acq_device = f['waits'].attrs['wait_monitor_acquisition_device']
                acq_device = _ensure_str(acq_device)
                if acq_device:
                    props = properties.get(f, acq_device, 'connection_table_properties')
                    if props.get('wait_monitor_supports_wait_completed_events', False):
                        self.wait_completed_events_supported = True

        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_timeout)
        self.clear_bar()
        self.command_thread.start()

    def get_save_data(self):
        return {}
    
    def get_callbacks(self):
        return {'science_over': self.on_science_over,
                'science_starting': self.on_science_starting}
        
    # This callback should be run after any callbacks that might have significant time
    # delays. For example it should run after the cycle_time science_starting callback.
    # The priority should be set accordingly.
    @callback(priority=200)
    def on_science_starting(self, h5_filepath):
        self.command_queue.put(('start', h5_filepath))

    @callback(priority=5)
    def on_science_over(self, h5_filepath):
        self.command_queue.put(('stop', None))

    def clear_bar(self):
        self.bar.setEnabled(False)
        self.bar.setFormat('No shot running')
        self.bar.setValue(0)
        self.bar.setPalette(self.style.standardPalette())
        self.ui.wait_warning.hide()

    def get_next_thing(self):
        """Figure out what's going to happen next: a wait, a time marker, or a
        regular update. Return a string saying which, and a float saying how
        long from now it will occur. If the thing has already happened but not
        been taken into account by our processing yet, then return zero for
        the time."""
        if self.waits is not None and self.next_wait_index < len(self.waits):
            next_wait_time = self.waits['time'][self.next_wait_index]
        else:
            next_wait_time = np.inf
        if self.markers is not None and self.next_marker_index < len(self.markers):
            next_marker_time = self.markers['time'][self.next_marker_index]
        else:
            next_marker_time = np.inf
        assert self.shot_start_time is not None
        assert self.time_spent_waiting is not None
        labscript_time = time.time() - self.shot_start_time - self.time_spent_waiting
        next_update_time = labscript_time + UPDATE_INTERVAL
        if next_update_time < next_wait_time and next_update_time < next_marker_time:
            return 'update', UPDATE_INTERVAL
        elif next_wait_time < next_marker_time:
            return 'wait', max(0, next_wait_time - labscript_time)
        else:
            return 'marker', max(0, next_marker_time - labscript_time)

    def update_bar_style(self, marker=False, wait=False, previous=False):
        """Update the bar's style to reflect the next marker or wait,
        according to self.next_marker_index or self.next_wait_index. If
        previous=True, instead update to reflect the current marker or
        wait."""
        assert not (marker and wait)
        # Ignore requests to reflect markers or waits if there are no markers
        # or waits in this shot:
        marker = marker and self.markers is not None and len(self.markers) > 0
        wait = wait and self.waits is not None and len(self.waits) > 0
        if marker:
            marker_index = self.next_marker_index - 1 if previous else self.next_marker_index
            marker = marker_index >= 0
        if marker:
            label, _, color = self.markers[marker_index]
            self.bar_text_prefix = '[%s] ' % _ensure_str(label)
            r, g, b = color[0]
            if color.dtype == np.uint8 and (r, g, b) == (0, 0, 0):
                # is old colour spec, in which (0,0,0) meant no colour specified.
                r, g, b = (-1, -1, -1)
            # (-1,-1,-1) means no colour set for the marker. Don't change the bar colour
            # in this case.
            if (r, g, b) != (-1, -1, -1):
                bar_color = QtGui.QColor(r, g, b)
                if black_has_good_contrast(r, g, b):
                    highlight_text_color = QtCore.Qt.black
                else:
                    highlight_text_color = QtCore.Qt.white
            else:
                bar_color = None
                highlight_text_color = None
            regular_text_color = None # use default
        elif wait:
            wait_index = self.next_wait_index
            if previous:
                wait_index -= 1
                assert wait_index >= 0
            label = self.waits[wait_index]['label']
            self.bar_text_prefix = '-%s- ' % _ensure_str(label)
            highlight_text_color = regular_text_color = QtGui.QColor(192, 0, 0)
            bar_color = QtCore.Qt.gray
        if marker or wait:
            palette = self.style.standardPalette()
            if bar_color is not None:
                palette.setColor(QtGui.QPalette.Highlight, bar_color)
            # Ensure the colour of the text on the filled in bit of the progress
            # bar has good contrast:
            if highlight_text_color is not None:
                palette.setColor(QtGui.QPalette.HighlightedText, highlight_text_color)
            if regular_text_color is not None:
                palette.setColor(QtGui.QPalette.Text, regular_text_color)
            self.bar.setPalette(palette)
        else:
            self.bar_text_prefix = None
            # Default palette:
            self.bar.setPalette(self.style.standardPalette())

    def update_bar_value(self, marker=False, wait=False):
        """Update the progress bar with the current time elapsed. If marker or wait is
        true, then use the exact time at which the next marker or wait is defined,
        rather than the current time as returned by time.time()"""
        thinspace = u'\u2009'
        self.bar.setEnabled(True)
        assert not (marker and wait)
        if marker:
            labscript_time = self.markers['time'][self.next_marker_index]
        elif wait:
            labscript_time = self.waits['time'][self.next_wait_index]
        else:
            labscript_time = time.time() - self.shot_start_time - self.time_spent_waiting
        value = int(round(labscript_time / self.stop_time * BAR_MAX))
        text = u'%.2f%ss / %.2f%ss (%%p%s%%)'
        text = text % (labscript_time, thinspace, self.stop_time, thinspace, thinspace)
        if self.bar_text_prefix is not None:
            text = self.bar_text_prefix + text
        # setValue() repaints the bar immediately. With updates disabled, the bar is
        # instead repainted once, with both changes, by the event loop:
        self.bar.setUpdatesEnabled(False)
        try:
            self.bar.setValue(value)
            self.bar.setFormat(text)
        finally:
            self.bar.setUpdatesEnabled(True)

    def read_shot_file(self, h5_filepath):
        """Return the stop time, waits and markers of the shot, and the time at which
        we consider the shot to have started"""
        with h5py.File(h5_filepath, 'r') as f:
            props = properties.get(f, self.master_pseudoclock, 'device_properties')
            stop_time = props['stop_time']
            try:
                markers = f['time_markers'][:]
                markers.sort(order='time')
            except KeyError:
                markers = None
            try:
                waits = f['waits'][:]
                waits.sort(order='time')
            except KeyError:
                waits = None
        return stop_time, markers, waits, time.time()

    def command_loop(self):
        """Read each shot file in this thread, and pass the start and stop of each shot
        to the main thread in the order that they were received"""
        while True:
            command, h5_filepath = self.command_queue.get()
            if command == 'close':
                break
            elif command == 'start':
                try:
                    shot = self.read_shot_file(h5_filepath)
                except Exception:
                    logger.exception("Could not read shot file.")
                    inmain_later(self.show_error)
                else:
                    inmain_later(self.start_shot, h5_filepath, *shot)
            elif command == 'stop':
                inmain_later(self.stop_shot)
            else:
                raise ValueError(command)

    def start_shot(self, h5_filepath, stop_time, markers, waits, shot_start_time):
        try:
            self.h5_filepath = h5_filepath
            self.stop_time = stop_time
            self.markers = markers
            self.waits = waits
            self.shot_start_time = shot_start_time
            self.time_spent_waiting = 0
            self.next_marker_index = 0
            self.next_wait_index = 0
            self.update_bar_value()
            if (
                self.waits is not None
                and len(self.waits) > 0
                and not self.wait_completed_events_supported
            ):
                self.ui.wait_warning.show()
            self.schedule_next_thing()
        except Exception:
            logger.exception("Exception starting shot, ignoring.")
            self.show_error()

    def stop_shot(self):
        self.timer.stop()
        self.clear_bar()
        self.h5_filepath = None
        self.shot_start_time = None
        self.stop_time = None
        self.markers = None
        self.waits = None
        self.time_spent_waiting = None
        self.next_wait_index = None
        self.next_marker_index = None
        self.bar_text_prefix = None
        self.wait_start_time = None
        self.next_thing = None

    def show_error(self):
        """Stop processing the current shot, if any, and show an error on the bar"""
        self.stop_shot()
        self.bar.setFormat("Error in progress bar plugin")

    def schedule_next_thing(self):
        """Start the timer for the next update, marker or wait. During a wait, start
        the timer for the next check of whether the wait has completed."""
        if self.wait_start_time is not None:
            self.next_thing, timeout = 'wait_check', UPDATE_INTERVAL
        else:
            self.next_thing, timeout = self.get_next_thing()
        self.timer.start(math.ceil(timeout * 1000))

    def wait_has_completed(self):
        try:
            self.wait_completed.wait(self.h5_filepath, timeout=0)
            return True
        except TimeoutError:
            if self.wait_completed_events_supported:
                return False
            return time.time() - self.wait_start_time >= UNMONITORED_WAIT_DURATION

    def on_timeout(self):
        try:
            if self.next_thing == 'update':
                self.update_bar_value()
            elif self.next_thing == 'marker':
                self.update_bar_style(marker=True)
                self.update_bar_value(marker=True)
                self.next_marker_index += 1
            elif self.next_thing == 'wait':
                self.wait_start_time = time.time()
                self.update_bar_style(wait=True)
                self.update_bar_value(wait=True)
                self.next_wait_index += 1
            if self.wait_start_time is not None and self.wait_has_completed():
                self.time_spent_waiting += time.time() - self.wait_start_time
                self.wait_start_time = None
                # Set the bar style back to the previous marker, if any:
                self.update_bar_style(marker=True, previous=True)
                self.update_bar_value()
            self.schedule_next_thing()
        except Exception:
            logger.exception("Exception updating progress bar, ignoring.")
            self.show_error()

    def close(self):
        self.timer.stop()
        self.command_queue.put(('close', None))
        self.command_thread.join()

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
        
    
