#####################################################################
#                                                                   #
# /plugins/lock_monitor/lockers.py                                  #
#                                                                   #
# Copyright 2021, Monash University and contributors                #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
"""Base classes for laser locking classes.

Classes used with the lock monitor blacs plugin should inherit, directly or
indirectly, from the `Locker` class defined in this module. The `ScanZoomLocker`
class, which inherits from `Locker`, is also provided here.

Dummy example lockers that don't actually control any hardware are available in
`dummy_lockers.py`.

For further information on how to use these classes, see the README.
"""
import os
import time

from labscript_utils.setup_logging import LOG_PATH
# Specify root directory for logging stuff.
LOG_PATH = os.path.join(LOG_PATH, 'lock_monitor')
os.makedirs(LOG_PATH, exist_ok=True)


class Locker():
    """A class with minimum attributes/methods for use with lock monitor.

    All locker classes used with the lock monitor blacs plugin should inherit
    from this class. Methods that aren't fleshed out here should be fleshed out
    in the child classes.

    Args:
        logger (:obj:`logging.Logger`): The logger to use, typically retried
            using `logging.getLogger` or
            `labscript_utils.setup_logging.setup_logging()`. Logging is very
            useful for debugging and keeping track of when lasers are locked. It
            is strongly recommended that subclasses make use of the logger, e.g.
            by calling `self.logger.info("Some log message")`.
        plot_root_dir_name (str): The name to use for the directory in which to
            save plots. This directory will be in the directory set by
            `blacs.plugins.lock_monitor.lockers.LOG_PATH`. Plots shouldn't be
            saved directly in this directory; but instead should be saved in the
            directory specified by `self.plot_dir`. That which will be a
            subdirectory organized by year/month/day.
        display_name (str): The display name to use for the laser. See the
            docstring of the corresponding property for more information.
        auto_close_figures (bool): Whether or not to automatically close figures
            that are generated. See the docstring for the corresponding property
            for more information.

    Attributes:
        logger (:obj:`logging.Logger`): The logger provided during
            initialization.
        plot_root_dir_name (str): The name to use for the parent directory in
            which to store plots, initially set to the initialization argument
            of the same name. See that argument's docstring and the docstring
            for `self.plot_dir` for more information.
    """

    def __init__(self, logger, plot_root_dir_name, display_name,
                 auto_close_figures):
        # Store initialization parameters.
        self.logger = logger
        self.__display_name = str(display_name)
        self.plot_root_dir_name = plot_root_dir_name
        self.__auto_close_figures = bool(auto_close_figures)

        # Other attributes.
        self.update_save_time()

    @property
    def display_name(self):
        """The display name for the laser passed during initialization.

        Among other things, the display name will be used to label the controls
        for the locker.
        """
        return self.__display_name

    @property
    def auto_close_figures(self):
        """Whether or not to automatically close figures after generating them.

        It is extremely helpful for debugging purposes to generate and save
        plots as the `lock()` method, and possibly other methods, run. It can be
        helpful to leave these figures open when testing/developing a locker
        class in an interactive python prompt or in a jupyter notebook so that
        they can easily be viewed right away. However, leaving figures open when
        using the class with lock monitor can lead to many figures being open at
        once if `lock()` is called many times, potentially consuming a lot of
        memory.

        To get the best of both worlds, plots generated should be either left
        open or closed based on the value of the `auto_close_figures` property.
        Note that this isn't done automatically; it is up to the subclasses to
        ensure that they leave open or close the figures that the generate in
        accordance with the value set for `auto_close_figures`.
        """
        return self.__auto_close_figures

    @auto_close_figures.setter
    def auto_close_figures(self, value):
        self.__auto_close_figures = bool(value)

    def update_save_time(self):
        """Update `self.save_time` to the current local time."""
        self.save_time = time.localtime()
        self.logger.debug("Updated self.save_time.")

    @property
    def save_time_str(self):
        return time.strftime('%Y%m%d_%H%M%S', self.save_time)

    @property
    def plot_dir(self):
        """The directory in which to store plots.

        The path will start with the directory specified by
        `blacs.plugins.lock_monitor.lockers.LOG_PATH`, followed by
        `self.plot_root_dir_name`, then subdirectories for the year, month, and
        day, and finally one more subdirectory named after `self.save_time_str`.
        To update `self.save_time_str` to the current time (so that a new
        directory is used) call `self.update_save_time()`.

        Note that accessing this property will also create this directory if it
        does not already exist.
        """
        plot_dir = os.path.join(
            LOG_PATH,
            self.plot_root_dir_name,
            time.strftime('%Y', self.save_time),  # Year.
            time.strftime('%m', self.save_time),  # Month.
            time.strftime('%d', self.save_time),  # Day.
            self.save_time_str,
        )
        os.makedirs(plot_dir, exist_ok=True)
        return plot_dir

    def get_display_name(self):
        """Get the display name for the locker.

        Returns:
            display_name (str): The value for `display_name` passed during
                initialization.
        """
        return self.display_name

    def init(self):
        """Prepare the LaserLocker.

        This method will be called by the `lock_monitor` plugin when it is
        started. Any preparation which isn't done in `__init__()` but needs to
        be done before checking the lock status for the first time should be
        done here. That can include things like adjusting settings on controls,
        function generators, oscilloscopes, and so on.

        Configuring hardware in `init()` rather than `__init__()` can be useful
        if you would like to be able to create an instance of this class without
        immediately sending commands to reconfigure the hardware.

        It is often best practice to reset instruments to their default
        settings, by using the SCPI `'*RST'` command for example, then adjust
        the settings as needed. This ensures that all settings, including ones
        that aren't explicitly changed, are always set to the same values.
        Otherwise changes to parameters not explicitly set here, done manually
        or by other software, can change the behavior of the system and cause
        difficult-to-debug issues. Additionally, locking the front panel of the
        instruments can prevent similar issues caused by changes made by users
        manually after this method has run. Along the same lines it is sometimes
        also possible to use a software lock to ensure that no other programs
        interact with the instruments. For example, `pyvisa` resources can be
        opened with `access_mode=pyvisa.constants.AccessModes.exclusive_lock` to
        ensure that no other connections are made to the device.
        """
        pass

    def callback_pre_transition_to_buffered(self, path):
        """This method is called right before transitioning to buffered.

        The `lock_monitor` blacs plugin calls this method from blacs when a shot
        is run. The call occurs right before blacs starts transitioning to
        buffered, which is when it will prepare all of the hardware for the
        upcoming shot.

        This method should be implemented by child classes and should return
        either `True` or `False`. If `True` is returned then blacs will continue
        as normal after this callback returns. If `False` is returned, then the
        `lock_monitor` plugin will attempt relock the laser. Therefore this
        method should return `True` if the laser is in lock, or if another
        callback will determine whether or not the laser is in lock. This method
        should only return `False` if it determines that the laser is indeed out
        of lock.

        Args:
            path (str): The path to the hdf5 file of the shot currently running.

        Returns:
            status_ok (bool): The status of the laser lock. This will be set to
                `False` if it is known that the laser needs to be relocked. It
                will be set to `True` if the laser is in lock, or if a different
                callback will determine whether or not the laser is in lock.
        """
        return True

    def callback_science_starting(self, path):
        """This method is called right before setting a sequence running.

        The `lock_monitor` blacs plugin calls this method from blacs when a shot
        is run. The call occurs right after blacs finishes transitioning to
        buffered but right before instructing the master pseudoclock to start
        running the sequence. Note that this callback may not be called if a
        shot is aborted, so do not rely on it running every time other callbacks
        are run.

        This method should be implemented by child classes and should return
        either `True` or `False`. If `True` is returned then blacs will continue
        as normal after this callback returns. If `False` is returned, then the
        `lock_monitor` plugin will attempt relock the laser. Therefore this
        method should return `True` if the laser is in lock, or if another
        callback will determine whether or not the laser is in lock. This method
        should only return `False` if it determines that the laser is indeed out
        of lock.

        Args:
            path (str): The path to the hdf5 file of the shot currently running.

        Returns:
            status_ok (bool): The status of the laser lock. This will be set to
                `False` if it is known that the laser needs to be relocked. It
                will be set to `True` if the laser is in lock, or if a different
                callback will determine whether or not the laser is in lock.
        """
        return True

    def callback_science_over(self, path):
        """This method is called right after a sequence runs.

        The `lock_monitor` blacs plugin calls this method from blacs when a shot
        is run. The call occurs right after the sequence finishes but before
        blacs transitions back to manual mode.

        This method should be implemented by child classes and should return
        either `True` or `False`. If `True` is returned then blacs will continue
        as normal after this callback returns. If `False` is returned, then the
        `lock_monitor` plugin will attempt relock the laser. Therefore this
        method should return `True` if the laser is in lock, or if another
        callback will determine whether or not the laser is in lock. This method
        should only return `False` if it determines that the laser is indeed out
        of lock.

        Args:
            path (str): The path to the hdf5 file of the shot currently running.

        Returns:
            status_ok (bool): The status of the laser lock. This will be set to
                `False` if it is known that the laser needs to be relocked. It
                will be set to `True` if the laser is in lock, or if a different
                callback will determine whether or not the laser is in lock.
        """
        return True

    def callback_analysis_cancel_send(self, path):
        """This method is called right after transitioning to manual.

        The `lock_monitor` blacs plugin calls this method from blacs when a shot
        is run. The call occurs right after blacs transitions back to manual
        mode but before the shot is sent to lyse. Note that this callback may
        not be called if a shot is aborted, so do not rely on it running every
        time other callbacks are run.

        This method should be implemented by child classes and should return
        either `True` or `False`. If `True` is returned then blacs will continue
        as normal after this callback returns. If `False` is returned, then the
        `lock_monitor` plugin will attempt relock the laser. Therefore this
        method should return `True` if the laser is in lock, or if another
        callback will determine whether or not the laser is in lock. This method
        should only return `False` if it determines that the laser is indeed out
        of lock.

        Args:
            path (str): The path to the hdf5 file of the shot currently running.

        Returns:
            status_ok (bool): The status of the laser lock. This will be set to
                `False` if it is known that the laser needs to be relocked. It
                will be set to `True` if the laser is in lock, or if a different
                callback will determine whether or not the laser is in lock.
        """
        return True

    def lock(self):
        """Lock the laser.

        This method should attempt to lock the laser, then return `True` if the
        laser was successfully locked or `False` otherwise. If automatic locking
        is not supported for a laser, this method should simply return `False`
        to indicate that it has not locked the laser. The parent class's version
        of this method always returns `False` so it is only necessary to
        override this method in child classes if they do support automatic
        locking of their laser.

        It is extremely helpful for debugging purposes if this method, or other
        methods that it calls, logs its progress and results using
        `self.logger`. Additionally, generating and saving figures of signals
        measured when locking the laser can also be extremely helpful. It is
        recommended to call `self.update_save_time()` then save the figures in
        `self.plot_dir` to have the figures from this call to `lock()` stored in
        their own automatically-generated directory, though saving the figures
        elsewhere is fine.

        If `self.init()` adjusts settings of hardware, it may be wise for
        subclasses to call `self.init()` before calling `self.lock()`. Doing so
        generally shouldn't be necessary since lock monitor runs `init()`
        automatically when it starts. However, explicitly running `init()` again
        before locking would override any changes to the settings made manually
        or by other software since `init()` was last called, which would make
        the code more robust against those kinds of changes.

        Returns:
            is_locked (bool): Whether or not the laser was successfully locked.
        """
        # Update the self.save_time so that plots from this call to lock() are
        # stored in their own directory, assuming they are saved in
        # self.plot_dir.
        self.update_save_time()

        # Return False by default to indicate that this method has not locked
        # the laser. Child classes that support locking their laser should
        # override this method then return True or False as indicated in the
        # docstring above.
        return False

    def close(self):
        """Close connections to devices used for locking the laser."""
        pass


class ScanZoomLocker(Locker):
    """A class for locking a laser by zooming in on a spectroscopic feature.

    This class is designed to lock a laser to a spectroscopic feature in the
    manner that it is usually done manually. In particular it attempts to scan
    the laser, identify the desired spectroscopic feature in an oscilloscope
    trace, then adjust the scan offset and reduce the scan range to zoom in on
    that spectroscopic feature. That zooming step is repeated multiple times to
    iteratively zoom in on the feature. After a number of zooms set by the
    `n_zooms_before_setpoint` initialization argument, the setpoint (aka error
    signal offset) is adjusted. Finally after a number of zooming iterations set
    by the `n_zooms` initialization argument, the feedback is enabled.

    Due to the wide variety of hardware that can be used, the user must flesh
    out the methods defined in this class by adding code to actually communicate
    with the hardware. This class can be though of as a template for which the
    user must write the code to actually adjust the signals to the requested
    values and retrieve the required data back from the hardware. Additionally
    the user must write some data analysis code to identify the target
    spectroscopic feature and determine which feedforward control signal value
    will center the scan around it. Generally methods that aren't fleshed out
    here should be fleshed out in the user's classes that inherit from this
    class.

    See the parent class's docstring for additional information.

    Args:
        logger (:obj:`logging.Logger`): The logger to use, typically retried
            using `logging.getLogger` or
            `labscript_utils.setup_logging.setup_logging()`. Logging is very
            useful for debugging and keeping track of when lasers are locked. It
            is strongly recommended that subclasses make use of the logger, e.g.
            by calling `self.logger.info("Some log message")`.
        plot_root_dir_name (str): The name to use for the directory in which to
            save plots. This directory will be in the directory set by
            `blacs.plugins.lock_monitor.lockers.LOG_PATH`. Plots shouldn't be
            saved directly in this directory; but instead should be saved in the
            directory specified by `self.plot_dir`. That which will be a
            subdirectory organized by year/month/day.
        display_name (str): The name of the laser. Among other things, it will
            be used to label the controls for the locker.
        auto_close_figures (bool): Whether or not to automatically close figures
            that are generated. See the docstring for the corresponding property
            for more information.
        zoom_factor (float): The factor by which to decrease the scan range for
            each zooming iteration during locking. For example, setting it to
            `10` will reduce the scan range by a factor of 10 during each
            zooming iteration. Making this value very small will mean that many
            zooming iterations are required before the scan range becomes small
            enough to turn on the feedback and lock the laser successfully.
            Making this value too large may result in the desired spectroscopic
            feature ending up outside of the scan range (e.g. due to
            inaccuracies in determining the feedforward signal value that
            centers the scan around the target spectroscopic feature), which
            will prohibit the laser from locking to the correct feature.
        n_zooms (int): The number of zooming iterations to do when locking.
        n_zooms_before_setpoint (int): The number of zooming iterations to
            perform before adjusting the setpoint.
        initial_scan_amplitude (float): The initial amplitude to use for the
            scan for the first zooming iteration.
        initial_scan_feedforward (float): The initial feedforward value to
            use for the first zooming iteration.

    Attributes:
        logger (:obj:`logging.Logger`): The logger provided during
            initialization.
        plot_root_dir_name (str): The name to use for the parent directory in
            which to store plots, initially set to the initialization argument
            of the same name. See that argument's docstring and the docstring
            for `self.plot_dir` for more information.
        zoom_factor (float): The factor by which to decrease the scan range for
            each zoom, initially set by the initialization argument of the same
            name.
        n_zooms (int): The number of zooming iterations to perform before
            enabling the feedback, initially set by the initialization argument
            of the same name.
        n_zooms_before_setpoint (int): The number of zooming iterations to
            perform before adjusting the setpoint, initially set by the
            initialization argument of the same name.
        initial_scan_amplitude (float): The initial amplitude to use for the
            scan for the first zooming iteration, initially set by the
            initialization argument of the same name.
        initial_scan_feedforward (float): The initial feedforward value to
            use for the first zooming iteration, initially set by the
            initialization argument of the same name.
        n_zoom (int): A counter for keeping track of how many zooming iterations
            have been done while locking.
    """

    def __init__(self, logger, plot_root_dir_name, display_name,
                 auto_close_figures, zoom_factor, n_zooms,
                 n_zooms_before_setpoint, initial_scan_amplitude,
                 initial_scan_feedforward):
        # Call parent's __init__() method.
        super().__init__(
            logger=logger,
            plot_root_dir_name=plot_root_dir_name,
            display_name=display_name,
            auto_close_figures=auto_close_figures,
        )

        # Store initialization parameters.
        self.zoom_factor = zoom_factor
        self.n_zooms = n_zooms
        self.n_zooms_before_setpoint = n_zooms_before_setpoint
        self.initial_scan_amplitude = initial_scan_amplitude
        self.initial_scan_feedforward = initial_scan_feedforward

        # Variable for keeping track of how many zooming iterations have been
        # done while locking.
        self.n_zoom = 0

    def disable_feedback(self):
        """Turn off the lock's feedback."""
        pass

    def enable_feedback(self):
        """Turn on the lock's feedback."""
        pass

    def set_scan_amplitude(self, amplitude):
        """Set the amplitude of the laser's scan.

        Args:
            amplitude (float): The amplitude to set the scan to.
        """
        pass

    def get_scan_amplitude(self):
        """Get the amplitude of the laser's scan.

        Returns:
            amplitude (float): The amplitude of the laser's scan.
        """
        pass

    def set_feedforward(self, feedforward):
        """Set the feedforward output of the feedback loop.

        The feedforward control is the output that adjusts the laser's frequency
        when it is not in lock. It's typically an offset added to the output of
        a PID controller. Typically it must be set to within a range of values
        in order for the laser to lock when feedback is enabled.

        Args:
            feedforward (float): The value to set for the feedforward control.
        """
        pass

    def get_feedforward(self):
        """Get the feedforward output of the feedback loop.

        The feedforward control is the output that adjusts the laser's frequency
        when it is not in lock. It's typically an offset added to the output of
        a PID controller. Typically it must be set to within a range of values
        in order for the laser to lock when feedback is enabled.

        Returns:
            feedforward (float): The current value of the feedforward control.
        """
        pass

    def set_setpoint(self, setpoint):
        """Set the setpoint of the feedback loop.

        The setpoint control adjusts the offset of the error signal and so is
        sometimes referred to as "error offset". It is often, but not always,
        set to zero.

        Args:
            setpoint (float): The value to set for the setpoint control.
        """
        pass

    def get_setpoint(self):
        """Get the setpoint of the feedback loop.

        The setpoint control adjusts the offset of the error signal and so is
        sometimes referred to as "error offset". It is often, but not always,
        set to zero.

        Returns:
            setpoint (float): The current value of the setpoint control.
        """
        pass

    def get_lockpoint_feedforward_value(self):
        """Get the feedforward value that centers the scan around the lockpoint.

        Executing this method will typically require communicating with an
        oscilloscope to get a trace of a spectroscopic signal as the laser's
        frequency is scanned. This method should get that trace, identify the
        target spectroscopic feature, then determine what value the feedforward
        control should be set to in order to center the scan around the target
        spectroscopic feature, aka lockpoint.

        It is strongly recommended that this method generate a figure showing
        the oscilloscope trace with the lockpoint marked. Such figures are
        instrumental in debugging when the `lock()` method fails. It is
        recommended, but not required, to save the plots in the directory
        `self.plot_dir`. Note that this method will generally be called multiple
        times for each call to `lock()` so it may be wise to include
        `self.n_zoom`, the index of the zooming iteration, in the file name to
        avoid overwriting it in subsequent zooming iterations. For example, a
        good file name with path would be
        `os.path.join(self.plot_dir, f'scope_trace_{self.save_time_str}_{self.n_zoom}.png')`.
        Make sure to then close the figure if `self.auto_close_figures` is set
        to `True`.

        Additionally, it is recommended to log information using `self.logger`.
        For example, a log entry could be
        `self.logger.info(f"Lockpoint feedforward is {lock_point_feedforward}")`.
        Logging the file name and path of the saved figure may also be helpful.

        Returns:
            lockpoint_feedforward (float): The feedforward value that would
                center the scan around the lockpoint.
        """
        pass

    def get_lockpoint_setpoint_value(self):
        """Get the desired value for the setpoint when the laser is locked.

        Executing this method will typically require communicating with an
        oscilloscope to get a trace of a spectroscopic signal as the laser's
        frequency is scanned. This method should get that trace then determine
        what value should be used for the setpoint control. Changing the value
        of the setpoint control will effectively shift the spectroscopic signal
        up or down without changing its shape.

        The notes in the docstring for `self.get_lockpoint_feedforward_value()`
        about the usefulness of logging and saving plots apply here as well. See
        that docstring for more information.

        For some setups it may be sufficient to simply always return zero from
        this method. For other setups it may be worth communicating with an
        oscilloscope to adjust the setpoint to account for drifts in the offset
        of the spectroscopic signal.

        Returns:
            lockpoint_setpoint (float): The setpoint value to use when locking
                the laser.
        """
        pass

    def zoom_in_on_lockpoint(self, zoom_factor=None):
        """Adjust the scan range and offset to zoom in on the lockpoint.

        Args:
            zoom_factor (float, optional): The amount by which to zoom in, which
                generally should be a factor larger than one. For example,
                setting it to `10` would instruct this method to decrease the
                ramp amplitude by a factor of 10. If set to `None`, then
                `self.zoom_factor`, which is set during initialization,
                will be used.
        """
        # Get default value of zoom_factor if necessary.
        if zoom_factor is None:
            zoom_factor = self.zoom_factor

        # Find the lockpoint.
        lockpoint = self.get_lockpoint_feedforward_value()

        # Decrease scan range by zoom_factor and re-center the scan around the
        # lockpoint.
        new_scan_amplitude = self.get_scan_amplitude() / zoom_factor
        self.set_scan_amplitude(new_scan_amplitude)
        self.set_feedforward(lockpoint)

    def lock(self):
        """Lock the laser.

        This method works by iteratively decreasing the scan amplitude by a
        factor of `self.zoom_factor`, each time re-centering the scan around the
        lockpoint. After `self.n_zooms_before_setpoint`, the setpoint is
        adjusted to the value returned by `self.get_lockpoint_setpoint_value`.
        Finally, after a number of iterations set by `self.n_zooms`, the
        feedback is enabled to lock the laser.

        If `self.init()` adjusts settings of hardware, it may be wise for
        subclasses to call `self.init()` before calling this `lock()` method
        (with `super().lock()`). Doing so generally shouldn't be necessary since
        lock monitor runs `init()` automatically when it starts. However,
        explicitly running `init()` again before locking would override any
        changes to the settings made manually or by other software since
        `init()` was last called, which would make the code more robust against
        those kinds of changes.

        Returns:
            is_locked (bool): Whether or not the laser was successfully locked.
        """
        self.logger.info("lock() called.")
        # Update the save time so that self.plot_dir points to a new directory
        # in which to store all of the plots generated during this call to
        # lock().
        self.update_save_time()

        # Ensure that the lock is turned off.
        self.disable_feedback()

        # Set initial scan parameters.
        self.logger.info("Setting initial scan parameters...")
        self.set_scan_amplitude(self.initial_scan_amplitude)
        self.set_feedforward(self.initial_scan_feedforward)
        self.logger.info("Finished setting initial scan parameters.")

        # Zoom in to the lockpoint.
        self.n_zoom = 0
        for j in range(self.n_zooms):
            # Adjust the setpoint to the necessary value if the correct number
            # of zooms have been done.
            if j == self.n_zooms_before_setpoint:
                self.logger.info("Adjusting setpoint...")
                setpoint = self.get_lockpoint_setpoint_value()
                self.set_setpoint(setpoint)
                self.logger.info("Finished adjusting setpoint.")
            self.logger.info(f"Starting zoom iteration #{self.n_zoom}...")
            self.zoom_in_on_lockpoint()
            self.logger.info(f"Finished zoom iteration #{self.n_zoom}.")
            self.n_zoom += 1

        # Ensure setpoint is adjusted if set to be done after last zoom.
        if self.n_zoom == self.n_zooms_before_setpoint:
            self.logger.info("Adjusting setpoint...")
            setpoint = self.get_lockpoint_setpoint_value()
            self.set_setpoint(setpoint)
            self.logger.info("Finished adjusting setpoint.")

        # Enable the lock.
        self.enable_feedback()

        # Check that locking was successful.
        is_locked = self.check_lock()
        self.logger.info(f"lock() finished with is_locked={is_locked}.")

        return is_locked

    def check_lock(self):
        """Verify that the laser is locked.

        This method should check that the feedback is enabled and that the laser
        is actually still in lock. If the laser is in lock, it should return
        `True`, and it should return `False` otherwise.

        A typical way to check this is to ensure that the error signal of the
        feedback loop is sufficiently small and that the output of the PID
        controller is within some range (indicating that the integrator hasn't
        wound up and railed due to the laser going out of lock).

        Typically the code required to verify that the laser is in lock already
        exists in the `callback_*` methods. Therefore this method often can just
        call the required `callback_*` methods.

        Returns:
            is_locked (bool): Whether or not the laser is locked.
        """
        return False
