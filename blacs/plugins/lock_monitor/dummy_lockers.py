#####################################################################
#                                                                   #
# /plugins/lock_monitor/dummy_lockers.py                            #
#                                                                   #
# Copyright 2021, Monash University and contributors                #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
"""Example dummy lockers for testing/development purposes.

This module contains some classes which can be used with lock monitor but which
do not actually control any hardware. They can be used with lock monitor for
testing and development purposes. In particular, the import paths
`blacs.plugins.lock_monitor.dummy_lockers.dummy_locker_instance` and
`blacs.plugins.lock_monitor.dummy_lockers.dummy_scan_zoom_locker_instance` can
be added in lock monitor's settings.
"""
import logging
import numpy as np
import os
import sys
import time

import matplotlib.pyplot as plt

from blacs.plugins.lock_monitor.lockers import LOG_PATH, Locker, ScanZoomLocker


class DummyLocker(Locker):
    """An example locker class that doesn't actually control anything.

    An instance of this locker class can be added to lock monitor by opening its
    settings and adding the import path
    `blacs.plugins.lock_monitor.dummy_lockers.dummy_locker_instance`.

    This locker class will randomly pretend its laser is out of lock on occasion
    to simulate re-locking a laser. The probability that any given callback will
    report that the laser is out of lock is controlled by the
    `unlocked_probability` initialization argument.

    When this locker "locks", it really just waits for a few seconds then
    returns without having done anything.
    """

    def __init__(self, unlocked_probability, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unlocked_probability = unlocked_probability

    def _get_random_status_ok(self):
        # Randomly decide if the dummy laser is in or out of lock
        status_ok = (np.random.random() > self.unlocked_probability)
        if status_ok:
            self.logger.info(f"Randomly chose status_ok is {status_ok}.")
        else:
            self.logger.warning(f"Randomly chose status_ok is {status_ok}.")
        return status_ok

    def init(self):
        self.logger.info("init() started...")
        # Simulate initialization taking some time.
        time.sleep(10)
        self.logger.info("init() finished.")

    def callback_pre_transition_to_buffered(self, path):
        self.logger.info("callback_pre_transition_to_buffered() called.")
        status_ok = self._get_random_status_ok()
        return status_ok

    def callback_science_starting(self, path):
        self.logger.info("callback_science_starting() called.")
        status_ok = self._get_random_status_ok()
        return status_ok

    def callback_science_over(self, path):
        self.logger.info("callback_science_over() called.")
        status_ok = self._get_random_status_ok()
        return status_ok

    def callback_analysis_cancel_send(self, path):
        self.logger.info("callback_analysis_cancel_send() called.")
        status_ok = self._get_random_status_ok()
        return status_ok

    def lock(self):
        self.logger.info("lock() starting...")

        # Simulate locking taking some time.
        self.logger.debug("Simulating taking some time to lock...")
        time.sleep(3)
        self.logger.debug("Finished simulating taking time to lock.")

        # lock() needs to return whether or not the laser is locked, which will
        # again be decided randomly for this dummy laser.
        is_locked = self._get_random_status_ok()
        self.logger.info("lock() finished.")
        return is_locked


# Create a dummy locker that doesn't actually control anything, which can be
# used for testing purposes. First create a logger for it. See the readme for
# some discussion on how to set up a logger.
_dummy_logger = logging.getLogger(__name__)
_dummy_logger.setLevel(logging.DEBUG)
_formatter = logging.Formatter(
    '%(asctime)s:%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s: %(message)s'
)
# Set up a console handler.
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_formatter)
_dummy_logger.addHandler(_console_handler)
# Set up file handler.
_full_filename = os.path.join(LOG_PATH, 'dummy_locker.log')
_file_handler = logging.FileHandler(_full_filename, mode='w')
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_formatter)
_dummy_logger.addHandler(_file_handler)
# Create the DummyLocker instance which can be added to lock monitor.
dummy_locker_instance = DummyLocker(
    unlocked_probability=0.05,
    logger=_dummy_logger,
    plot_root_dir_name="dummy_locker",
    display_name="Dummy Locker",
    auto_close_figures=True,
)


class DummyScanZoomLocker(ScanZoomLocker):
    """An example locker class that doesn't actually control anything.

    An instance of this locker class can be added to lock monitor by opening its
    settings and adding the import path
    `blacs.plugins.lock_monitor.dummy_lockers.dummy_scan_zoom_locker_instance`.

    This locker class will randomly pretend its laser is out of lock on occasion
    to simulate re-locking a laser. The probability that any given callback will
    report that the laser is out of lock is controlled by the
    `unlocked_probability` initialization argument.

    This dummy locker will simulate the approach taken by `ScanZoomLocker` by
    running it on simulated data. It will produce log messages and save plots as
    well, which makes it a good reference when implementing a real
    `ScanZoomLocker` subclass.
    """

    def __init__(self, unlocked_probability, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unlocked_probability = unlocked_probability

    def init(self):
        self.logger.info("init() started...")
        # Since this method is usually the best place to connect to hardware,
        # we'll create the attributes used for simulating hardware here.
        # Variables for storing settings of dummy controls.
        self._feedback_enabled = False
        self._scan_amplitude = 0
        self._feedforward = 0
        self._setpoint = 0

        # Variables used for simulating an oscilloscope trace of a spectroscopic
        # signal.
        self._target_feedforward = 0
        self._target_setpoint = 0

        # Simulate initialization taking some time.
        time.sleep(10)
        self.logger.info("init() finished.")

    # Take this method from DummyLocker
    _get_random_status_ok = DummyLocker._get_random_status_ok

    def _randomize_target(self):
        """Simulate drifts in the laser.

        In particular calling this method simulates a random change in the
        free-running frequency of a laser and adding a random offset to its
        spectroscopic signal. It does so by changing the
        `self._target_feedforward` and `self._target_setpoint` attributes, which
        represent the values that `self._feedforward` and `self._setpoint`
        should ideally have after zooming in.

        The other code won't access the target values to pretend like we don't
        know what the values should be; the target values are only used to
        generate simulated data from the system in `self.get_scope_trace()`.
        """
        self.logger.debug("Simulating system drift...")
        # Pick a target feedforward value randomly between -spread/2 and
        # spread/2.
        spread = 5
        self._target_feedforward = spread * np.random.random() - spread / 2.
        self.logger.debug(
            f"Simulated feedforward target is {self._target_feedforward}"
        )

        # Pick a random target setpoint value as well.
        spread = 1
        self._target_setpoint = spread * np.random.random() - spread / 2.
        self.logger.debug(
            f"Simulated setpoint target is {self._target_setpoint}"
        )
        self.logger.debug("Finished simulating system drift.")

    def get_scope_trace(self):
        """Simulate a scope trace of a spectroscopy signal.

        This scope trace produced simulates a single noisy dispersive feature.

        Returns:
            signal (np.array): A simulated 1D array of voltages from an
                oscilloscope.
        """
        self.logger.info("Simulating a scope trace.")
        n_points = 1001

        # The scan is centered around self._feedforward with amplitude set by
        # self._scan_amplitude.
        x = np.linspace(-self._scan_amplitude, self._scan_amplitude, n_points)
        x = x + self._feedforward

        # Dispersive signal is centered around self._target_feedforward and is
        # offset by (self._target_setpoint - self._setpoint).
        width = 0.1
        detuning = (x - self._target_feedforward)
        normalized_detuning = detuning / width
        true_signal = normalized_detuning / (1 + normalized_detuning**2)
        true_signal = true_signal + self._target_setpoint - self._setpoint

        # Add some noise to the signal.
        noise = 0.01 * np.random.randn(n_points)
        signal = true_signal + noise

        return signal

    def callback_pre_transition_to_buffered(self, path):
        self.logger.info("callback_pre_transition_to_buffered() called.")
        return self.check_lock()

    def callback_science_starting(self, path):
        self.logger.info("callback_science_starting() called.")
        return self.check_lock()

    def callback_science_over(self, path):
        self.logger.info("callback_science_over() called.")
        return self.check_lock()

    def callback_analysis_cancel_send(self, path):
        self.logger.info("callback_analysis_cancel_send() called.")
        return self.check_lock()

    def disable_feedback(self):
        self._feedback_enabled = False

    def enable_feedback(self):
        self._feedback_enabled = True

    def set_scan_amplitude(self, amplitude):
        self._scan_amplitude = amplitude

    def get_scan_amplitude(self):
        return self._scan_amplitude

    def set_feedforward(self, feedforward):
        self._feedforward = feedforward

    def get_feedforward(self):
        return self._feedforward

    def set_setpoint(self, setpoint):
        self._setpoint = setpoint

    def get_setpoint(self):
        return self._setpoint

    def get_lockpoint_feedforward_value(self):
        # Simulate getting a spectroscopic trace from an oscilloscope.
        trace = self.get_scope_trace()

        # The lockpoint is halfway between the min and max of the simulated
        # signal (neglecting noise)
        min_index = np.argmin(trace)
        max_index = np.argmax(trace)
        lockpoint_index = (min_index + max_index) / 2.

        # Now figure out what feedforward voltage would center the scan around
        # lockpoint_index. For real systems this typically requires knowing
        # some calibration constants, but those are effectively all equal to one
        # for this simulated system.
        n_points = len(trace)
        scan_min = self._feedforward - self._scan_amplitude
        scan_max = self._feedforward + self._scan_amplitude
        scan_peak_to_peak = scan_max - scan_min
        scan_fraction = lockpoint_index / (n_points - 1)
        lockpoint_feedforward = scan_min + scan_fraction * scan_peak_to_peak

        # Log results.
        shift = lockpoint_feedforward - self._feedforward
        msg = (
            "get_lockpoint_feedforward_value() info: "
            f"lockpoint_index={lockpoint_index}, "
            f"lockpoint feedforward value={lockpoint_feedforward}, "
            f"difference from previous={shift}."
        )
        self.logger.info(msg)

        # Plot results.
        fig = plt.figure()
        fig.suptitle(
            f"Scope Traces After {self.n_zoom} Zoom(s)",
            fontsize='x-large',
            fontweight='bold',
        )
        axes = fig.add_subplot(111)
        axes.plot(trace, label='Spectroscopy')
        # Mark min/max/center of fringe along x-axis.
        axes.plot(min_index, 0, marker='o', color='red')
        axes.plot(max_index, 0, marker='o', color='red')
        axes.plot(lockpoint_index, 0, marker='x', color='red')
        axes.set_xlabel("Trace index")
        axes.set_ylabel("Error")
        axes.legend()

        # Save the figure.
        filename = os.path.join(
            self.plot_dir,
            f'scope_trace_{self.save_time_str}_{self.n_zoom}.png',
        )
        fig.savefig(
            filename,
            bbox_inches='tight',
        )

        # Close the figure if configured to do so.
        if self.auto_close_figures:
            plt.close(fig)

        return lockpoint_feedforward

    def get_lockpoint_setpoint_value(self):
        # Simulate getting a spectroscopic trace from an oscilloscope.
        trace = self.get_scope_trace()

        # The lockpoint is halfway between the min and max of the simulated
        # signal (neglecting noise).
        error_min = np.amin(trace)
        error_max = np.amax(trace)
        # For real systems this step typically requires knowing some calibration
        # constants, but those are effectively all equal to one for this
        # simulated system.
        lockpoint_setpoint = (error_min + error_max) / 2.

        # Log the results.
        msg = (
            f"get_lockpoint_setpoint_value() info: "
            f"error_min={error_min}, "
            f"error_max={error_max}, "
            f"setpoint={lockpoint_setpoint}."
        )
        self.logger.info(msg)

        return lockpoint_setpoint

    def lock(self):
        # Simulate random drifts in system before simulating locking.
        self._randomize_target()
        return super().lock()

    def check_lock(self):
        # Decide randomly if the laser is in lock.
        return self._get_random_status_ok()


# Create a dummy locker that doesn't actually control anything, which can be
# used for testing purposes. First create a logger for it. See the readme for
# some discussion on how to set up a logger.
_dummy_logger = logging.getLogger(__name__)
_dummy_logger.setLevel(logging.DEBUG)
_formatter = logging.Formatter(
    '%(asctime)s:%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s: %(message)s'
)
# Set up a console handler.
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_formatter)
_dummy_logger.addHandler(_console_handler)
# Set up file handler.
_full_filename = os.path.join(LOG_PATH, 'dummy_scan_zoom_locker.log')
_file_handler = logging.FileHandler(_full_filename, mode='w')
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_formatter)
_dummy_logger.addHandler(_file_handler)
# Create the DummyLocker instance which can be added to lock monitor.
dummy_scan_zoom_locker_instance = DummyScanZoomLocker(
    unlocked_probability=0.05,
    logger=_dummy_logger,
    plot_root_dir_name="dummy_scan_zoom_locker",
    display_name="Dummy ScanZoomLocker",
    auto_close_figures=True,
    zoom_factor=4,
    n_zooms=6,
    n_zooms_before_setpoint=3,
    initial_scan_amplitude=10,
    initial_scan_feedforward=0,
)
