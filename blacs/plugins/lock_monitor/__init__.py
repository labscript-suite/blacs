#####################################################################
#                                                                   #
# /plugins/lock_monitor/__init__.py                                 #
#                                                                   #
# Copyright 2021, Monash University and contributors                #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

from concurrent.futures import ThreadPoolExecutor
import importlib
import logging
import os
from queue import Queue
import shutil
import threading

from blacs.plugins import PLUGINS_DIR
from blacs.tab_base_classes import PluginTab, Worker
import labscript_utils.h5_lock
import h5py  # Must be imported after labscript_utils.h5_lock, not before.
from labscript_utils.qtwidgets.digitaloutput import DigitalOutput
from labscript_utils.qtwidgets.outputbox import OutputBox
from labscript_utils.qtwidgets.toolpalette import ToolPaletteGroup
from qtutils import inmain, inmain_decorator, UiLoader
from qtutils.qt.QtCore import Qt
from qtutils.qt.QtGui import QIcon
from qtutils.qt.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

name = "Lock Monitor"
module = 'lock_monitor'  # should be folder name
logger = logging.getLogger('BLACS.plugin.%s' % module)

# Work around circular import dependency by lazily importing tempfilename from
# blacs.experiment_queue only once it's needed.
tempfilename = None


class Plugin(object):
    def __init__(self, initial_settings):
        logger.info("Plugin.__init__() called.")
        # Standard plugin attributes.
        self.menu = None
        self.notifications = {}
        self.BLACS = None

        # Attributes for keeping track of workers. Workers can be uniquely
        # identified by their import path.
        self.workers = []
        self._worker_by_import_path_dict = {}

        # Workers control settings. The dictionaries below will use import_path
        # as a key and the value will be the value of the option for that
        # locker. For example, if monitoring is enabled for a locker, then
        # self._monitoring_enabled(import_path) will be set to True.
        self._monitoring_enabled = {}
        self._locking_enabled = {}
        self._force_lock = {}
        self._restart_worker = {}

        # Threading locks to avoid race conditions.
        self._monitoring_enabled_lock = threading.Lock()
        self._locking_enabled_lock = threading.Lock()
        self._force_lock_lock = threading.Lock()
        self._restart_worker_lock = threading.Lock()

        # Attributes related to behavior when laser locking fails.
        self._failed_lockers = []
        self._shot_requeued = False
        self._lock_failure_messages = []

        # Make matplotlib use the undisplayed Agg backend so its GUI stuff
        # doesn't get messed up by blacs GUI stuff. Do this here instead of at
        # the top of the file so that it only runs when a Plugin is
        # instantiated. That way it won't run when just importing the module,
        # which can e.g. mess up plotting in jupyter notebooks. That would be
        # particularly annoying when using a jupyter notebook to develop a
        # Locker class as they need to import the locker classes from this
        # module.
        logger.info("Setting matplotlib to use 'Agg' backend...")
        import matplotlib
        matplotlib.use('Agg')
        logger.info("Set matplotlib to use 'Agg' backend.")

    def _start_locker_inits(self):
        """Start running the `init()` method of all lockers.

        The commands to the workers will each be sent from their own thread.
        Doing this in separate threads lets the workers, and the rest of blacs,
        start up in parallel. The actual work is done by the workers in separate
        processes so they do truly run in parallel despite the fact that the
        threads sending the command aren't truly in parallel due to the GIL.

        This method starts the threads running then returns. The threads will be
        joined later by `_ensure_locker_init_threads_joined()` to make sure that
        they finish before any shots are run.
        """
        # Start running the init() methods of the lockers.
        logger.info("Starting threads to run init() for each locker...")
        self._locker_init_threads = []
        # Create a dict for threads to indicate if they caught an error.
        self._locker_init_errored = {}
        for worker in self.workers:
            thread = threading.Thread(
                target=self._run_locker_init,
                args=(worker,),
                daemon=True,
            )
            self._locker_init_threads.append((worker, thread))
            thread.start()
        logger.info("Finished starting threads to run init() for each locker.")

    def _run_locker_init(self, worker):
        """Instruct a worker to run it's locker's init() method.

        This method is designed to be run in its own thread. It will report back
        if the locker's `init()` method raised an error by setting the value of
        `self._locker_init_errored[worker]`, setting it to `True` if there was
        an error or `False` otherwise.

        Args:
            worker (LockMonitorWorker): The worker which should run its locker's
                `init()` method.
        """
        try:
            logger.info(f"Starting locker's init() for {worker.import_path}...")
            self.run_worker_method(worker, 'locker_init')
            self._locker_init_errored[worker] = False
            logger.info(f"Finished locker's init() for {worker.import_path}.")
        except Exception:
            logger.exception(
                f"{worker.import_path} locker's init() raised an error."
            )
            self._locker_init_errored[worker] = True

    def _ensure_locker_init_threads_joined(self):
        """Ensure threads running lockers' `init()` methods have joined.

        `_start_locker_inits()` starts threads to run the `init()` method of
        each locker, but doesn't wait for them to finish. Calling this method
        ensures that they have finished, which must be done before any shots are
        run.

        Admittedly the queue nature of the communication with the workers means
        that this method maybe isn't necessary. However, at the very least it
        makes it possible to update the blacs status to inform the user that
        blacs is waiting on the `init()` methods to finish if they try to run a
        shot before they have.

        This method will also mark that the threads have been joined to avoid
        needing to do this check in the future.
        """
        if self._locker_init_threads is not None:
            # Join the threads which were started in this class's __init__()
            # method to create the workers.
            logger.info("Joining locker init() threads...")
            self.set_status("Waiting for laser locker\ninit() methods...")

            # Iterate over each worker, one per import_path.
            for worker, thread in self._locker_init_threads:
                # Join the thread.
                thread.join()
                import_path = worker.import_path
                logger.debug(f"{import_path} locker init() thread joined.")

            # Set _locker_init_threads to None to signal that they've all been
            # joined.
            self._locker_init_threads = None
            logger.info("Finished joining locker init() threads.")

    def set_status(self, status):
        """Set the blacs status message.

        The status message is the text displayed just above the shot queue and
        below the pause/repeat/abort controls.

        Args:
            status (str): The message to display.
        """
        self.queue_manager.set_status(status)

    def pause_queue(self):
        """Pause the blacs shot queue."""
        logger.warning("Pausing the experiment queue...")
        self.BLACS['experiment_queue'].manager_paused = True
        logger.info("Paused the experiment queue...")

    def abort_shot(self):
        """Attempt to abort the currently running shot.

        Note that it can be too late to abort a shot, so calling this method
        does NOT guarantee that the shot will be aborted.
        """
        logger.warning("Aborting the current shot...")
        self.queue_manager.current_queue.put(
            ['Queue Manager', 'abort']
        )
        logger.info("Abort message sent.")

    def requeue_shot(self, path):
        """Put the shot back to the front of the blacs queue.

        This method will clean the hdf5 file as needed then put the clean file
        at the front of the shot queue. This method will attempt to overwrite
        the file specified by `path`, but if it fails it will create a new file
        instead.

        Args:
            path (str): The path of to the hdf5 file of the shot to requeue.
        """
        # Don't requeue the current shot more than once per attempt at running
        # it.
        if self._shot_requeued:
            logger.info("requeue_shot() called but shot already requeued.")
            return

        logger.info("Re-queueing the current shot...")
        # Cleaning the hdf5 file isn't always necessary before re-queueing it
        # (depends on at which callback the shot was aborted) but doing it
        # doesn't hurt.
        path = self.clean_h5_file(path)

        # Prepend the shot file to the front of the shot queue.
        self.queue_manager.prepend(path)
        self._shot_requeued = True
        logger.info(f"Re-queued the current shot ({path}).")

    def is_h5_file_dirty(self, path):
        """Determine if a shot hdf5 file needs to be cleaned before running it.

        When a shot is run some data is added to its hdf5 file. If the shot
        needs to be rerun, then that data needs to be stripped from the file
        first. This method checks if the specified hdf5 file has data which
        needs to be stripped.

        The criteria for determining if the shot file is dirty is based on the
        logic in `blacs.experiment_queue.QueueManager.process_request()`.

        Args:
            path (str): The path to the shot's hdf5 file.

        Returns:
            is_dirty (bool): Whether or not the shot hdf5 file needs to be
                cleaned before it can be run. If `True` then the file needs to
                be cleaned; if `False` then the file does not need to be
                cleaned.
        """
        with h5py.File(path, 'r') as h5_file:
            is_dirty = ('data' in h5_file['/'])
        logger.debug(
            f"Checked if {path} was dirty and got is_dirty = {is_dirty}"
        )
        return is_dirty

    def clean_h5_file(self, path):
        """Clean a shot's hdf5 file.

        This method removes some data from a shot's hdf5 file that is added when
        the shot is run. Removing this is necessary in order to re-run a shot.
        The steps taken to do this are based on those taken in the `if
        error_condition:` block in `experiment_queue.QueueManager.manage()`.

        This method will attempt to overwrite the file specified by the `path`
        argument with a clean copy of the file. If it cannot overwrite that
        file, then it will just create a new file and return the path to that
        file. Therefore make sure to use the value for `path` returned by this
        method after it runs; do NOT assume that the file specified by the
        input value of `path` will be clean after this method is run.

        Args:
            path (str): The path to the shot's hdf5 file.

        Returns:
            path (str): The path to the shot's clean hdf5 file. This ideally is
                the same path as provided for the method's argument of the same
                name. However the actual path of the clean hdf5 file may be
                different if this method fails to overwrite the original.
        """
        logger.debug(f"Cleaning shot hdf5 file {path}...")

        # Lazily import tempfilename if it hasn't been imported already.
        global tempfilename
        if tempfilename is None:
            import blacs.experiment_queue
            tempfilename = blacs.experiment_queue.tempfilename

        # Determine if this shot was a repeat.
        with h5py.File(path, 'r') as h5_file:
            repeat_number = h5_file.attrs.get('run repeat', 0)

        # Create a new clean h5 file.
        temp_path = tempfilename()
        self.queue_manager.clean_h5_file(
            path,
            temp_path,
            repeat_number=repeat_number,
        )

        # Try to overwrite the old shot file with the new clean shot file.
        try:
            shutil.move(temp_path, path)
            logger.debug(f"Successfully cleaned {path}.")
        except Exception:
            msg = ('Couldn\'t delete failed run file %s, ' % path +
                   'another process may be using it. Using alternate '
                   'filename for second attempt.')
            logger.warning(msg, exc_info=True)
            # Use a different name if necessary.
            path = path.replace('.h5', '_retry.h5')
            shutil.move(temp_path, path)

        return path

    def create_worker(self, import_path):
        """Create a worker for a locker instance.

        The new worker will be appended to `self.workers`.

        If a worker for the locker specified by import path already exists, then
        a warning will be issued and the method will return without creating a
        new worker. If the worker fails to initialize, the error will be logged
        and no new worker will be added to `self.workers`.

        Args:
            import_path (str): The import path of the locker instance. Note that
                this should be the import path of an instance of a locker class,
                not the class itself.
        """
        # Ensure this worker hasn't already been created.
        if import_path in self.locker_import_paths:
            logger.warning(
                f"Skipping creation of worker for {import_path} because a "
                "worker has already been created for it.",
            )
            return

        # This is a new locker, so try to create a worker.
        logger.info(f"Creating worker from import path: {import_path}...")
        try:
            worker = self._create_worker(import_path)
            logger.info(
                f"Finished creating worker from import path: {import_path}."
            )
        except Exception:
            logger.exception(
                f"Failed to create a worker from import path: {import_path}."
            )
        else:
            # Keep track of successfully created workers.
            self.workers.append(worker)
            self._worker_by_import_path_dict[import_path] = worker

    def _create_worker(self, import_path):
        # Create the worker.
        worker = LockMonitorWorker(
            output_redirection_port=self.tab.output_box.port,
        )
        # Note that attributes set here are only available in this process;
        # methods run with run_worker_methods() won't be able to access their
        # values unless the attribute is also set in the worker process, either
        # by run(), init(), or a method run with run_worker_method().
        worker.import_path = import_path

        # Start up the worker. Arguments and keyword arguments passed to
        # start() are sent along to the worker's run() method.
        worker.start(
            worker_name=import_path,
            device_name=module,
            extraargs={},
        )

        # Run the worker's worker_init() method. Note that this does NOT call
        # the init() method of the corresponding locker class; that will be done
        # later.
        self.run_worker_method(
            worker,
            'worker_init',
            import_path,
        )

        # Get the worker's display name and store it for use in this process.
        display_name = self.run_worker_method(
            worker,
            'get_display_name',
        )
        worker.display_name = display_name

        return worker

    @property
    def locker_import_paths(self):
        """The import paths of lockers for which a worker was created."""
        return [worker.import_path for worker in self.workers]

    def run_worker_method(self, worker, method_name, *args, **kwargs):
        """Instruct a worker to run one of its methods and retrieve the results.

        Typically the worker is one of the entries in `self.workers`. Note that
        the method will run in the worker's process, not this process.

        Args:
            worker (LockMonitorWorker): The worker, typically from
                `self.workers` which should run the specified method in its
                process.
            method_name (str): The name of the method which should be run.
            *args: Additional arguments are passed to the worker's method.
            **kwargs: Additional keyword arguments are passed to the worker's
                method.

        Raises:
            RuntimeError: A `RuntimeError` is raised if the worker does not
                acknowledge that it has received the command to run the method.
            RuntimeError: A `RuntimeError` is raised if the worker raises an
                error while running the requested method.

        Returns:
            results: The results returned by the worker's method are returned by
                this method.
        """
        # This method is based on blacs.tab_base_classes.Tab.mainloop().
        import_path = worker.import_path
        logger.debug(
            f"Running method {method_name} of locker {import_path}."
        )

        # Get queues for sending/receiving.
        to_worker = worker.to_child
        from_worker = worker.from_child

        # Put the instructions into the queue to the worker.
        instruction = (method_name, args, kwargs)
        to_worker.put(instruction)

        # Get the job acknowledgement from the worker. This just signals that
        # the worker got the instruction; it doesn't return the result from
        # running the method.
        success, message, results = from_worker.get()
        if not success:
            logger.error(
                f"Locker {import_path} worker reported failure to start job "
                f"'{method_name}', returned message: '{message}'."
            )
            raise RuntimeError(message)
        logger.debug(
            f"Received '{method_name}' job acknowledgement from worker for "
            f"locker {import_path}."
        )

        # Now get the result of running the method.
        success, message, results = from_worker.get()
        if not success:
            logger.error(
                f"Locker {import_path} worker failed to run job "
                f"'{method_name}', returned message: '{message}'."
            )
            raise RuntimeError(message)
        logger.debug(
            f"Successfully ran method {method_name} of locker {import_path}."
        )
        return results

    def _get_worker_by_import_path(self, import_path):
        """Get the worker for the locker specified by its import path.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            LockMonitorWorker: The worker created for the locker specified by
                `import_path`.
        """
        return self._worker_by_import_path_dict[import_path]

    def get_display_name_by_import_path(self, import_path):
        """Get the display name of the locker specified by its import path.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            str: The value of the `display_name` attribute of the specified
                locker instance.
        """
        worker = self._get_worker_by_import_path(import_path)
        return worker.display_name

    def get_menu_class(self):
        return None

    def get_notification_classes(self):
        return [LockFailureNotification]

    def get_setting_classes(self):
        return [Setting]

    def get_callbacks(self):
        callbacks = {
            'pre_transition_to_buffered': self.callback_pre_transition_to_buffered,
            'science_starting': self.callback_science_starting,
            'science_over': self.callback_science_over,
            'analysis_cancel_send': self.callback_analysis_cancel_send,
            'shot_ignore_repeat': self.callback_shot_ignore_repeat,
        }
        return callbacks

    def get_monitoring_enabled(self, import_path):
        """Get whether or not monitoring is enabled for a locker.

        When monitoring is enabled, the locker's callback methods will be run
        when a shot is executed so that it checks whether or not its laser is in
        lock. When monitoring is not enabled, the callbacks are not run.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            bool: Will return `True` if monitoring is enabled for the locker and
                `False` otherwise.
        """
        with self._monitoring_enabled_lock:
            return self._monitoring_enabled[import_path]

    def set_monitoring_enabled(self, import_path, enabled):
        """Set whether or not monitoring is enabled for a locker.

        When monitoring is enabled, the locker's callback methods will be run
        when a shot is executed so that it checks whether or not its laser is in
        lock. When monitoring is not enabled, the callbacks are not run.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): Whether or not monitoring should be enabled. Set to
                `True` to enable monitoring or `False` to disable it.
        """
        enabled = bool(enabled)
        if enabled:
            logger.info(f"Enabling monitoring for {import_path}")
        else:
            logger.info(f"Disabling monitoring for {import_path}")
        with self._monitoring_enabled_lock:
            self._monitoring_enabled[import_path] = enabled

    def get_locking_enabled(self, import_path):
        """Get whether or not automatic locking is enabled for a locker.

        When locking is enabled, the locker's `lock()` method will be called if
        the laser is found to be out of lock. If locking is not enabled and the
        laser is found to be out of lock, then `lock()` will NOT be called.
        Instead lock monitor will abort the shot, pause the queue, and requeue
        the shot.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            bool: Will return `True` if locking is enabled for the locker and
                `False` otherwise.
        """
        with self._locking_enabled_lock:
            return self._locking_enabled[import_path]

    def set_locking_enabled(self, import_path, enabled):
        """Set whether or not automatic locking is enabled for a locker.

        When locking is enabled, the locker's `lock()` method will be called if
        the laser is found to be out of lock. If locking is not enabled and the
        laser is found to be out of lock, then `lock()` will NOT be called.
        Instead lock monitor will abort the shot, pause the queue, and requeue
        the shot.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): Whether or not automatic locking should be enabled.
                Set to `True` to enable automatic locking or `False` to disable
                it.
        """
        enabled = bool(enabled)
        if enabled:
            logger.info(f"Enabling locking for {import_path}")
        else:
            logger.info(f"Disabling locking for {import_path}")
        with self._locking_enabled_lock:
            self._locking_enabled[import_path] = enabled

    def get_force_lock(self, import_path):
        """Get whether or not a locker is set to force lock.

        When force lock is enabled, the locker's `lock()` method will be called
        at the beginning of a shot whether or not the laser is determined to be
        out of lock.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            bool: Will return `True` if force lock is enabled for the locker and
                `False` otherwise.
        """
        with self._force_lock_lock:
            return self._force_lock[import_path]

    def set_force_lock(self, import_path, enabled):
        """Set whether or not a locker is set to force lock.

        When force lock is enabled, the locker's `lock()` method will be called
        at the beginning of a shot whether or not the laser is determined to be
        out of lock.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): Whether or not force lock should be enabled. Set to
                `True` to force locking or `False` to not force it.
        """
        enabled = bool(enabled)
        if enabled:
            logger.info(f"Flagging to force lock for {import_path}.")
        else:
            logger.info(f"Flagging NOT to force lock for {import_path}.")
        with self._force_lock_lock:
            self._force_lock[import_path] = enabled

    def get_restart_worker(self, import_path):
        """Get whether or not a locker is set to restart its worker.

        When restart worker is enabled, lock monitor will restart the worker for
        the locker at the beginning of the next shot.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            bool: Will return `True` if restart worker is enabled for the locker
                and `False` otherwise.
        """
        with self._restart_worker_lock:
            return self._restart_worker[import_path]

    def set_restart_worker(self, import_path, enabled):
        """Set whether or not a locker is set to restart its worker.

        When restart worker is enabled, lock monitor will restart the worker for
        the locker at the beginning of the next shot.

        Threading locks are used so it is safe to call this method at any time.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): Whether or not restart workers should be enabled.
                Set to `True` to instruct lock monitor to restart the worker or
                `False` to instruct lock monitor to forgo restarting the worker.
        """
        enabled = bool(enabled)
        if enabled:
            logger.info(f"Flagging to restart worker for {import_path}.")
        else:
            logger.info(f"Flagging NOT to restart worker for {import_path}.")
        with self._restart_worker_lock:
            self._restart_worker[import_path] = enabled

    def _run_callback_one_locker(self, worker, callback_name, path):
        """Run the specified callback of the worker if enabled.

        Note that calling this method does NOT guarantee that the specified
        callback is actually run. If the worker's locker has already failed to
        lock or if monitoring is disabled for the worker, then the callback is
        skipped and this method simply returns `True`. Also, if the worker does
        not have the specified callback, then this method just returns `True`.

        Args:
            worker (LockMonitorWorker): The worker instance, typically from
                `self.workers` for which to run the callback.
            callback_name (str): The name of the callback to run.
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            status_ok (bool or str): This method returns `True` if the callback
                is not run because the locker has already failed to lock, or
                because monitoring is disabled for the worker, or because the
                worker does not have a method for the specified callback. If the
                worker raises an error while running the callback, this method
                returns the string `'error'`. If the worker method is
                successfully run, then its result is returned, which should be
                `True` or `False` (assuming the user's code follows to API
                specified in the documentation).
        """
        import_path = worker.import_path
        # Don't run callback for any lockers that have failed to lock.
        if worker in self._failed_lockers:
            logger.debug(
                f"Skipping {callback_name}() for {import_path} because it "
                "already failed to lock."
            )
            return True

        # Don't run callback for any lockers that have their monitoring
        # disabled.
        if not self.get_monitoring_enabled(import_path):
            logger.debug(
                f"Skipping {callback_name}() for {import_path} because its "
                "monitoring is disabled."
            )
            return True

        # Call the locker's method for the specified callback_name.
        logger.debug(f"Running {callback_name}() for {import_path}...")
        try:
            status_ok = self.run_worker_method(worker, callback_name, path)
        except Exception:
            # If the callback raise an error, return 'error' to inform
            # _run_callback_all_lockers() of the issue.
            logger.exception(
                f"Callback {callback_name} for {import_path} raised an error."
            )
            return 'error'

        # Log if the locker doesn't support the callback.
        if status_ok == 'callback_not_supported':
            logger.debug(
                f"Skipped {callback_name}() for {import_path} because it "
                "doesn't support that callback."
            )
            return True
        else:
            logger.debug(
                f"Finished {callback_name}() for {import_path}, which returned "
                f"{status_ok}."
            )
            return status_ok

    def _run_callback_all_lockers(self, callback_name, path):
        """Run the specified callback for all of the lockers.

        Different threads will be used to run the callbacks so that they can run
        in parallel. Using different threads allows us to send commands to each
        worker before getting a response from the previous one. Each worker runs
        in a separate process, so the callbacks actually run in parallel.

        If a locker indicates that its laser is out of lock and automatic
        locking is enabled for that locker, then this method will call
        `self.lock_locker()` to attempt to lock the laser. If a laser is not and
        cannot be locked, then this method calls
        `self._handle_locking_failure()`.

        Args:
            callback_name (str): The name of the callback to run.
            path (str): The path to the hdf5 file of the currently running shot.
        """
        logger.info(f"Calling lockers' {callback_name}()...")
        # Send the commands to run the callbacks in different threads.
        with ThreadPoolExecutor() as executor:
            def map_function(worker):
                status_ok = self._run_callback_one_locker(
                    worker,
                    callback_name,
                    path,
                )
                return status_ok
            statuses = list(executor.map(map_function, self.workers))

        # Handle any status that isn't ok (indicated by True).
        for worker, status_ok in zip(self.workers, statuses):
            if status_ok == 'error':
                # If a callback raised an error, abort the shot and pause the
                # queue without trying to lock.
                failure_message = (
                    f"{worker.display_name}'s {callback_name} raised an error"
                )
                self._handle_locking_failure(worker, path, failure_message)
            elif not status_ok:
                # Try to lock the laser if set to do so, otherwise give up
                # immediately.
                if self.get_locking_enabled(worker.import_path):
                    self.lock_locker(worker, path)
                else:
                    failure_message = (
                        f"{worker.display_name} out of lock."
                    )
                    self._handle_locking_failure(worker, path, failure_message)

        self._update_failure_notification()
        logger.info(f"Finished calling lockers' {callback_name}().")

    def callback_pre_transition_to_buffered(self, path):
        """Call the method of the same name of each locker.

        This is the first callback run for a shot, so this method does some
        other steps as well. In particular it makes sure that the `init()`
        method of each locker has successfully finished running and it locks any
        lasers for which the laser has pressed the "Force Lock" control.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.
        """
        # This is the first callback when running a shot, so clear any info
        # related to lock failures from a previous iteration.
        self._failed_lockers = []
        self._shot_requeued = False
        self._lock_failure_messages = []
        self.notifications[LockFailureNotification].close()

        # Make sure all the locker init() threads have finished before a shot is
        # run.
        self._ensure_locker_init_threads_joined()

        # Restart any workers that are set to be restarted. Use a copy of the
        # list of workers to avoid editing the original while iterating over it.
        for worker in self.workers.copy():
            import_path = worker.import_path
            if self.get_restart_worker(import_path):
                # Clear the restart worker flag and update the control.
                self.set_restart_worker(import_path, False)
                self.tab.set_restart_worker_enabled(worker.import_path, False)
                logger.info(f"Restarting worker for {import_path}...")
                self.set_status(
                    f"Restarting Worker For\n{worker.display_name}..."
                )

                # Shutdown the worker and remove it from the list of workers.
                self._shutdown_worker(worker)
                self.workers.remove(worker)

                # Start up a new worker and wait for it to initialize.
                self.create_worker(import_path)
                worker = self._get_worker_by_import_path(import_path)
                self._run_locker_init(worker)
                logger.info(f"Restarted worker for {import_path}.")

        # Abort/pause/requeue if monitoring is enabled for any worker that had
        # its locker's init() method error out.
        for worker in self.workers:
            if self.get_monitoring_enabled(worker.import_path):
                if self._locker_init_errored[worker]:
                    failure_message = (
                        f"{worker.display_name}'s init() method errored."
                    )
                    self._handle_locking_failure(worker, path, failure_message)

        # Lock immediately if forced to lock.
        for worker in self.workers:
            if self.get_force_lock(worker.import_path):
                # Clear the force lock flag and update the control.
                self.set_force_lock(worker.import_path, False)
                self.tab.set_force_lock_enabled(worker.import_path, False)
                logger.info(
                    f"Locking {worker.import_path} because user forced it to "
                    "lock."
                )
                self.lock_locker(worker, path)

        # Finally run the callbacks for the lockers.
        self._run_callback_all_lockers(
            'callback_pre_transition_to_buffered',
            path,
        )

    def callback_science_starting(self, path):
        """Call the method of the same name of each locker.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.
        """
        self._run_callback_all_lockers('callback_science_starting', path)

    def callback_science_over(self, path):
        """Call the method of the same name of each locker.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.
        """
        self._run_callback_all_lockers('callback_science_over', path)

    def callback_analysis_cancel_send(self, path):
        """Call the method of the same name of each locker.

        This method also instructs blacs NOT to send a shot's hdf5 file to lyse
        if a laser was found to be out of lock.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.
        """
        self._run_callback_all_lockers('callback_analysis_cancel_send', path)

        # Cancel sending shot to lyse if the shot was requeued.
        if self._shot_requeued:
            # In this case the shot is going to be reattempted, so skip sending
            # the shot file to lyse.
            logger.info("Canceled sending shot to lyse.")
            return True
        else:
            # In this case there were no issues with the lockers, so return
            # False to allow blacs to send the shot file to lyse.
            return False

    def callback_shot_ignore_repeat(self, path):
        """Callback to avoid duplicating shots that are requeued.

        This method instructs blacs NOT to use its "repeat shot" function if
        lock monitor has already requeued the shot.

        Note that if a laser were to be found to be out of lock at this point,
        it would be too late to skip sending the shot to lyse. For that reason
        it does not call any locker callback methods.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.
        """
        # Don't use blacs's "repeat shot" feature if lock monitor already
        # requeued the shot.
        if self._shot_requeued:
            # In this case a locker failed to lock, so return True to avoid
            # repeating the shot an additional time.
            logger.info("Canceling repeating shot (to avoid duplicating it).")

            # If a shot is requeued during callback_science_over then the hdf5
            # file is cleaned but then dirtied again before it is rerun. This
            # callback should be run when that happens though, in which case we
            # can re-clean it. So ensure that the file is cleaned here.
            if self.is_h5_file_dirty(path):
                self.clean_h5_file(path)
            return True
        else:
            # In this case there were no issues with the lockers, so return
            # False to allow blacs to repeat the shot if it is set to do so.
            return False

    def lock_locker(self, worker, path):
        """Lock the laser, trying multiple times if necessary.

        This method calls the `lock()` method of the locker. If laser is
        successfully locked, then the shot is aborted and requeued. That is done
        so that the sot is still run with the lasers in lock even if they were
        found to be out of lock during one of the later callbacks which runs
        after the shot is executed.

        If the `lock()` method fails to lock the laser even after a few
        attempts, then `self._handle_locking_failure()` is called which will
        abort the shot, pause the queue, and requeue the shot.

        This method will connect to blacs's abort button, temporarily enabling
        it if necessary. Since interrupting the user-written code in a locker's
        `lock()` method is nontrivial to implement and probably a bad idea
        anyway, this method actually only aborts between locking attempts. Put
        another way, when the abort button is clicked this method will wait for
        the current lock attempt to finish, but won't start any new ones.

        Args:
            worker (LockMonitorWorker): The worker instance, typically from
                `self.workers`, of the laser to lock.
            path (str): The path to the hdf5 file of the currently running shot.
        """
        # Prepare some stuff for checking if the abort button was clicked. When
        # it is clicked, the string 'abort' will be put in the queue below,
        # which will signal that no new locking attempts should be started.
        abort_queue = Queue()

        def signal_abort():
            abort_queue.put('abort')
        inmain(
            self.BLACS['ui'].queue_abort_button.clicked.connect,
            signal_abort,
        )
        # Ensure that the abort button is enabled, recording its current state
        # so that it can be restored later.
        abort_button_was_enabled = inmain(
            self.BLACS['ui'].queue_abort_button.isEnabled,
        )
        inmain(self.BLACS['ui'].queue_abort_button.setEnabled, True)

        # Try to lock the laser.
        max_attempts = 5
        n_attempt = 1
        is_locked = False
        while n_attempt <= max_attempts and (not is_locked):
            # Check if the user hit the abort button, and don't start any more
            # locking attempts if they did.
            if not abort_queue.empty():
                # In this case abort was clicked.
                logger.info(
                    f"Locking {worker.import_path} was aborted by the user."
                )
                self.set_status(
                    f"Aborted Locking {worker.display_name}."
                )
                break

            # Log progress and update status indicator in blacs.
            logger.info(
                f"Locking {worker.import_path}, attempt #{n_attempt}..."
            )
            self.set_status(
                f"Locking {worker.display_name}\nAttempt #{n_attempt}..."
            )

            # Try to lock the laser.
            try:
                is_locked = self.run_worker_method(worker, 'lock')
            except Exception:
                logger.exception(
                    f"{worker.import_path}'s lock() raised an exception:"
                )
            n_attempt += 1

        # Set how blacs moves forward from this point.
        if not is_locked:
            # If the laser still isn't locked then abort, pause the queue, and
            # requeue the shot.
            failure_message = f"{worker.display_name} failed to lock."
            self._handle_locking_failure(worker, path, failure_message)
        else:
            # If the laser was successfully locked, abort and requeue the shot
            # but don't pause the queue. This is useful when the laser is found
            # to be out of lock after a shot has run, as this re-runs the shot
            # now that the laser is locked.
            self.set_status(f"Successfully Locked {worker.display_name}.")
            self.abort_shot()
            self.requeue_shot(path)

        # Disconnect from the abort button and disable it if it was disabled
        # before this method ran.
        inmain(
            self.BLACS['ui'].queue_abort_button.clicked.disconnect,
            signal_abort,
        )
        inmain(
            self.BLACS['ui'].queue_abort_button.setEnabled,
            abort_button_was_enabled,
        )

    def _handle_locking_failure(self, worker, path, failure_message):
        """Handle when a laser is not locked and cannot be locked.

        This method will abort the shot, pause the queue, then requeue the shot.

        Args:
            worker (LockMonitorWorker): The worker instance, typically from
                `self.workers`, of the laser to lock.
            path (str): The path to the hdf5 file of the currently running shot.
            failure_message (str): The message to display as the blacs status
                to indicate this locking failure.
        """
        logger.info(
            f"Handling locking failure of {worker.import_path} with message: "
            f"'{failure_message}'."
        )
        self.abort_shot()
        self.pause_queue()
        self.requeue_shot(path)
        self._lock_failure_messages.append(failure_message)
        self._failed_lockers.append(worker)

    def _update_failure_notification(self):
        """Display any lock failure messages in the notification."""
        logger.debug("_update_failure_notification() called.")
        if self._lock_failure_messages:
            logger.info("Displaying lock failure notification...")
            # Make a bulleted list of error messages.
            message = '<html><ul><li>'
            message = message + '</li><li>'.join(self._lock_failure_messages)
            message = message + '</li></ul></html>'

            # Set the notification error text and then display it.
            self.notifications[LockFailureNotification].error_text = message
            self.notifications[LockFailureNotification].show()
            logger.info(f"Lock failure messages: {self._lock_failure_messages}")
        else:
            logger.debug("No failure messages to display.")

    def set_menu_instance(self, menu):
        self.menu = menu

    def set_notification_instances(self, notifications):
        self.notifications = notifications

    def plugin_setup_complete(self, BLACS):
        """Do additional plugin setup after blacs has done more starting up.

        Plugins are initialized early on in blacs's start up. This method is
        called later on during blacs's startup once more things, such as the
        experiment queue, have been created. Therefore any setup that requires
        access to those other parts of blacs must be done here rather than in
        the plugin's `__init__()` method.

        Args:
            BLACS (dict): A dictionary where the keys are strings and the values
                are various parts of `blacs.__main__.BLACS`. For more details on
                exactly what is included in that dictionary, examine the code in
                `blacs.__main__.BLACS.__init__()` (there this dictionary, as of
                this writing, is called `blacs_data`).
        """
        logger.info("plugin_setup_complete() called.")
        self.BLACS = BLACS
        self.queue_manager = self.BLACS['experiment_queue']

        # Extract settings.
        settings = self.BLACS['settings']
        locker_import_paths = settings.get_value(Setting, 'import_paths')

        # Create the workers.
        for import_path in locker_import_paths:
            self.create_worker(import_path)

        # Set initial values of controls for workers that were successfully
        # created, which may be overwritten with saved values later.
        for import_path in self.locker_import_paths:
            self.set_monitoring_enabled(import_path, True)
            self.set_locking_enabled(import_path, True)
            self.set_force_lock(import_path, False)
            self.set_restart_worker(import_path, False)

        # Start running the init() methods of all of the lockers.
        self._start_locker_inits()

        # Update the GUI.
        self.tab.add_GUI_widgets()
        self.tab.apply_save_data()

    def get_tab_classes(self):
        return {'Lock Monitor': LockMonitorTab}

    def tabs_created(self, tabs_dict):
        # There is only one tab, so extract it for more convenient access.
        self.tabs = tabs_dict
        self.tab = list(tabs_dict.values())[0]

        # Give the tab a way to access this Plugin.
        self.tab.plugin = self

    def get_save_data(self):
        return {}

    def close(self):
        """Close the plugin.

        This method will also call the `close()` method of each locker.
        """
        logger.info("Shutting down workers...")
        with ThreadPoolExecutor() as executor:
            executor.map(self._shutdown_worker, self.workers)
        logger.info("Finished shutting down workers.")

    def _shutdown_worker(self, worker):
        """Shutdown a worker

        This method calls the locker's `close()` method then terminates the
        worker process.

        Args:
            worker (LockMonitorWorker): The worker instance to close, typically
                from `self.workers`.
        """
        import_path = worker.import_path
        logger.info(f"Shutting down worker for {import_path}...")
        try:
            # Instruct the worker to run its locker's close() method. Do this in
            # a separate thread to allow implementation of a timeout.
            logger.debug(f"Calling {import_path}.close()...")
            thread = threading.Thread(
                target=self._try_locker_close,
                args=(worker,),
                daemon=True,
            )
            thread.start()
            thread.join(60)  # 60 second timeout.

            # Log if the close() method timed out.
            if thread.is_alive():
                logger.error(f"{import_path}.close() timed out.")

            # Now terminate the worker.
            logger.debug(f"Calling worker.terminate() for {import_path}...")
            worker.terminate(wait_timeout=60)  # 60 second timeout.
            logger.debug(f"Finished worker.terminate() for {import_path}.")
            logger.info(f"Finished shutting down worker for {import_path}.")
        except Exception:
            logger.exception(f"Failed to shutdown worker for {import_path}.")

    def _try_locker_close(self, worker):
        """Run a locker's `close()` method and catch any errors.

        This method is written so that it can be run in a separate thread and
        catch any errors that running the locker's `close()` method throws.

        Args:
            worker (LockMonitorWorker): The worker instance to close, typically
                from `self.workers`.
        """
        try:
            self.run_worker_method(worker, 'close')
        except Exception:
            logger.exception(
                f"{worker.import_path}'s close() method raise an error."
            )


# class Menu(object):
    # pass


class LockFailureNotification():
    name = 'Lock failure'

    def __init__(self, BLACS):
        # Create the notification widget's main structure.
        self._ui = QFrame()
        self._layout = QVBoxLayout()
        self._ui.setLayout(self._layout)

        # Create the child widgets.
        self._title = QLabel(
            '<html><head/><body><span style=" font-weight:600; color:#ff0000;">'
            'Lock Failure:</span></body></html>'
        )
        self._error_text = QLabel()

        # Add the child widgets to the main notification widget.
        self._layout.addWidget(self._title)
        self._layout.addWidget(self._error_text)

    def get_widget(self):
        return self._ui

    @property
    @inmain_decorator(wait_for_return=True)
    def error_text(self):
        """The message of the error notification."""
        return self._error_text.text()

    @error_text.setter
    @inmain_decorator(wait_for_return=False)
    def error_text(self, text):
        self._error_text.setText(text)

    def get_properties(self):
        return {'can_hide': True, 'can_close': True}

    def set_functions(self, show_func, hide_func, close_func, get_state):
        self._show = show_func
        self._hide = hide_func
        self._close = close_func
        self._get_state = get_state

    @inmain_decorator(wait_for_return=False)
    def show(self):
        self._show()

    @inmain_decorator(wait_for_return=False)
    def hide(self):
        self._hide()

    @inmain_decorator(wait_for_return=False)
    def close(self):
        self._close()

    @inmain_decorator(wait_for_return=True)
    def get_state(self):
        self._get_state()

    def get_save_data(self):
        return {}


class Setting(object):
    name = name
    _NEW_ENTRY_TEXT = '<click here to add an entry>'

    def __init__(self, data):
        logger.info("Setting initialized.")
        self.data = data

    # Create the page, return the page and an icon to use on the label.
    def create_dialog(self, notebook):
        """Create the settings tab for this plugin.

        Note that this is the tab in the blacs preferences menu; not the blacs
        tab with the controls for the lockers.

        Args:
            notebook (labscript_utils.qtwidgets.fingertab.FingerTabWidget): The
                notebook of settings tabs.

        Returns:
            ui (qtutils.qt.QtWidgets.QWidget): The QT widget for the settings
                tab.
            icon (NoneType): The icon to use for the tab. As of this writing,
                adding an icon is not supported by blacs and so this method
                simply returns `None` for the icon.
        """
        # Load the ui.
        ui_path = os.path.join(PLUGINS_DIR, module, module + '_settings.ui')
        self.ui = UiLoader().load(ui_path)
        self.table_widget = self.ui.tableWidget

        # Fill out the table with the saved values. Do this before connecting
        # the callback below to avoid it interfering.
        self._pop_row(0)  # Get rid of row in UI file.
        import_paths = self.data.get('import_paths', [])
        for import_path in import_paths:
            self._append_row(import_path)
        self._append_row(self._NEW_ENTRY_TEXT)

        # Connect the callbacks.
        self.table_widget.itemChanged.connect(self.on_item_changed)

        return self.ui, None

    @property
    def n_rows(self):
        """The number of rows in the settings table."""
        return self.table_widget.rowCount()

    def on_item_changed(self, item):
        """The callback for when an entry in the settings table is changed.

        This method will sort the entries in the table, remove duplicates, store
        the values in `self.data`, and add a new row for the user to type in a
        new locker import path.

        Args:
            item (qtutils.qt.QtWidgets.QTableWidgetItem): The item which
                changed.
        """
        # Avoid infinite recursion since this method indirectly calls itself
        # because it changes the items in the table.
        self.table_widget.itemChanged.disconnect(self.on_item_changed)
        try:
            self._on_item_changed(item)
        except Exception as err:
            raise err
        finally:
            # Make sure to reconnect even if the method above errors.
            self.table_widget.itemChanged.connect(self.on_item_changed)

    def _on_item_changed(self, item):
        # Rebuild table from scratch rather than rearranging it because it's
        # easier.

        # Extract the import paths from the table. Iterate from bottom to top
        # removing rows as we go.
        import_paths = []
        row_indices = list(range(self.n_rows))
        row_indices.reverse()
        for index in row_indices:
            # Extract the import path from the row.
            import_path = self._pop_row(index)
            # Skip if empty or if the default entry text.
            if import_path and import_path != self._NEW_ENTRY_TEXT:
                import_paths.append(import_path)

        # Remove duplicates and sort the items.
        import_paths = sorted(set(import_paths))
        self.data['import_paths'] = import_paths

        # Rebuild table from scratch, including a row for the new entry.
        for import_path in import_paths:
            self._append_row(import_path)
        self._append_row(self._NEW_ENTRY_TEXT)

    def _pop_row(self, row_index):
        """Remove a row from `self.table_widget` and return its text.

        Args:
            row_index (int): The index of the row of the table.

        Returns:
            text (str): The text from the specified row of the table.
        """
        item = self.table_widget.item(row_index, 0)
        # If the entry doesn't exist, None is returned and this method will then
        # just return None as well.
        if item is None:
            return item

        # Get the text from the row then remove it.
        text = item.text()
        self.table_widget.removeRow(row_index)
        return text

    def _add_row(self, row_index, import_path):
        """Add a row to `self.table_widget`.

        Args:
            row_index (int): The index specifying where to add the row in the
                table.
            import_path (str): The import path to display in the row.
        """
        row = QTableWidgetItem(import_path)
        self.table_widget.insertRow(row_index)
        self.table_widget.setItem(row_index, 0, row)

    def _append_row(self, import_path):
        """Append a row to `self.table_widget`.

        Args:
            import_path (str): The import path to display in the row.
        """
        self._add_row(self.n_rows, import_path)

    def get_value(self, name):
        if name in self.data:
            return self.data[name]

        return None

    def save(self):
        logger.info("lock_monitor Setting saving.")
        return self.data

    def close(self):
        pass


class LockMonitorTab(PluginTab):
    # Constants for stuff displayed on the top of the tab.
    _tab_icon = ':/qtutils/fugue/lock'
    _tab_text_colour = 'black'
    _TERMINAL_ICON = ':/qtutils/fugue/terminal'

    # Constants specifying icons to display on controls.
    _ICON_MONITOR_ENABLE_TRUE = ':/qtutils/fugue/binocular--plus'
    _ICON_MONITOR_ENABLE_FALSE = ':/qtutils/fugue/binocular--minus'
    _ICON_LOCKING_ENABLE_TRUE = ':/qtutils/fugue/lock--plus'
    _ICON_LOCKING_ENABLE_FALSE = ':/qtutils/fugue/lock--minus'
    _ICON_FORCE_LOCK = ':/qtutils/fugue/lock'
    _ICON_RESTART_WORKER = ':/qtutils/fugue/arrow-circle'

    # Constants specifying text to display on controls
    _TEXT_MONITOR_ENABLE_TRUE = "Monitor Enabled"
    _TEXT_MONITOR_ENABLE_FALSE = "Monitor Disabled"
    _TEXT_LOCKING_ENABLE_TRUE = "Locking Enabled"
    _TEXT_LOCKING_ENABLE_FALSE = "Locking Disabled"
    _TEXT_FORCE_LOCK = "Force Lock"
    _TEXT_RESTART_WORKER = "Restart Worker"

    def __init__(self, *args, **kwargs):
        # Attribute to store saved settings that have been loaded from disk.
        self._saved_settings = {}

        # Call parent's __init__().
        super().__init__(*args, **kwargs)

        # Attributes that will be set later by the plugin.
        self.plugin = None

    @property
    def locker_import_paths(self):
        """The import paths of lockers for which a worker was created.

        The tab will have locker_import_paths and use them to tell the plugin
        which worker to adjust settings for etc. rather than having a list of
        the worker instances themselves here. This is to avoid the temptation to
        call worker methods directly from the LockMonitorTab class.
        """
        return self.plugin.locker_import_paths

    def initialise_GUI(self):
        # All of the locker controls will be created later by add_GUI_widgets(),
        # which will be run later once the plugin has figured out its
        # locker_import_paths and the display names have been retrieved. This
        # method prepares the GUI for the control widgets to be added later.

        # Set some attributes to access different parts of the GUI loaded from
        # the .ui file.
        # self.frame_layout is outermost/highest-level layout of the tab.
        self.frame_layout = self._ui.verticalLayout_2
        # self.top_horizontal_layout is the layout at the top with the text that
        # says "Locker Monitor [Plugin]" which will also contain the button to
        # show/hide the terminal output box.
        self.top_horizontal_layout = self._ui.horizontalLayout
        # Scroll area will contain all of the controls.
        self.scroll_area = self._ui.scrollArea
        self.scroll_area_layout = self._ui.device_layout

        # Change how the GUI is laid out to make room for an output box. This
        # lays out the tab in a manner that's a bit like a device tab rather
        # that a plugin tab. In particular this gives the tab an output box for
        # displaying text logged/printed by the workers and it adds a splitter
        # that allows adjusting how space is divided between the output box and
        # the controls.

        # Create the splitter which allows the user to adjust how space is split
        # between the terminal output box and the controls.
        self.splitter = QSplitter(Qt.Vertical)
        # Avoid letting the splitter collapse things completely when it is
        # dragged to the ends of its range, which is the behavior set for device
        # tabs. Note that this is overwritten for the scroll area only below.
        self.splitter.setChildrenCollapsible(False)

        # Put the splitter in the plugin's frame where the scrollArea is by
        # default, then add that scroll area back in as a child of the splitter.
        # This makes the tab laid out a bit more like device tabs where the
        # terminal output box has a given size and a scroll bar pops up next to
        # the the devices controls if there isn't enough room to display them
        # all at once.
        self.frame_layout.replaceWidget(self.scroll_area, self.splitter)
        self.splitter.addWidget(self.scroll_area)
        # Allow collapsing the scroll area when splitter is dragged all the way
        # to the top, which is the behavior that device tabs have.
        self.splitter.setCollapsible(self.splitter.count() - 1, True)

        # Add a toolpalettegroup, which will eventually contain one collapsible
        # toolpalette for each locker, to the scroll area.
        self.toolpalettegroup_widget = QWidget()
        self.toolpalettegroup = ToolPaletteGroup(self.toolpalettegroup_widget)
        self.scroll_area_layout.addWidget(self.toolpalettegroup_widget)

        # Add a spacer to fill up any extra blank vertical space in the scroll
        # area, otherwise Qt stretches the toolpalettes vertically which doesn't
        # look as nice.
        spacer_item = QSpacerItem(
            0,  # Preferred width.
            0,  # Preferred height.
            QSizePolicy.Minimum,  # Horizontal size policy.
            QSizePolicy.MinimumExpanding,  # Vertical size policy.
        )
        self.scroll_area_layout.addItem(spacer_item)

        # Add the output box which will display the text output from the
        # lockers.
        self.output_box = OutputBox(self.splitter)

        # Add a button to show/hide the output box.
        self.button_show_terminal = QToolButton()
        self.button_show_terminal.setIcon(QIcon(self._TERMINAL_ICON))
        self.button_show_terminal.setCheckable(True)
        self.button_show_terminal.toggled.connect(self._set_terminal_visible)
        self.button_show_terminal.setToolTip(
            "Show terminal output from the locker(s)."
        )
        self.top_horizontal_layout.addWidget(self.button_show_terminal)

    def _set_terminal_visible(self, visible):
        """Set whether or not the output box of text from lockers is displayed.

        This method is based on
        `blacs.tab_base_classes.Tab.set_terminal_visible`.

        Args:
            visible (bool): Set to `True` to display the terminal output box, or
                `False` to hide it.
        """
        if visible:
            self.output_box.output_textedit.show()
        else:
            self.output_box.output_textedit.hide()
        self.button_show_terminal.setChecked(visible)

    def add_GUI_widgets(self):
        """Create all of the controls for each locker."""
        # Start making the controls for all of the lockers.
        self.controls = {}
        for import_path in self.locker_import_paths:
            # Create controls.
            monitoring_enable_control = DigitalOutput(
                self._TEXT_MONITOR_ENABLE_TRUE,
            )
            locking_enable_control = DigitalOutput(
                self._TEXT_LOCKING_ENABLE_TRUE,
            )
            force_lock_control = DigitalOutput(
                self._TEXT_FORCE_LOCK,
            )
            restart_worker_control = DigitalOutput(
                self._TEXT_RESTART_WORKER,
            )

            # Add icons for controls.
            self._update_monitoring_enable_control(monitoring_enable_control)
            self._update_locking_enable_control(locking_enable_control)
            force_lock_control.setIcon(QIcon(self._ICON_FORCE_LOCK))
            restart_worker_control.setIcon(QIcon(self._ICON_RESTART_WORKER))

            # Set tooltips for controls.
            monitoring_enable_control.setToolTip(
                "Toggle whether or not the locker callbacks (which check if "
                "the laser is out of lock) are run."
            )
            locking_enable_control.setToolTip(
                "Toggle whether or not lock monitor will attempt to lock the "
                "laser if it is found to be out of lock.\n Monitoring must be "
                "enabled for this to have any effect."
            )
            force_lock_control.setToolTip(
                "Force lock monitor to lock the laser when the next shot is "
                "run.\nNote that the locking code won't run until a shot is "
                "run."
            )
            restart_worker_control.setToolTip(
                "Restart the worker process running the locker code when the "
                "next shot is run.\nNote that the worker won't be restarted "
                "until a shot is run."
            )

            # Connect controls to plugin methods.
            monitoring_enable_control.clicked.connect(
                self._make_set_monitoring_enabled(
                    import_path,
                    monitoring_enable_control,
                )
            )
            locking_enable_control.clicked.connect(
                self._make_set_locking_enabled(
                    import_path,
                    locking_enable_control,
                )
            )
            force_lock_control.clicked.connect(
                self._make_set_force_lock(
                    import_path,
                    force_lock_control,
                )
            )
            restart_worker_control.clicked.connect(
                self._make_set_restart_worker(
                    import_path,
                    restart_worker_control,
                )
            )

            # Store controls in a dictionary of dictionaries, with one
            # sub-dictionary for each laser.
            self.controls[import_path] = {
                'monitoring_enable': monitoring_enable_control,
                'locking_enable': locking_enable_control,
                'force_lock': force_lock_control,
                'restart_worker': restart_worker_control,
            }

        # Organize the controls, with one collapsible ToolPalette for each
        # locker, grouped together in one ToolPaletteGroup.
        for import_path, locker_controls in self.controls.items():
            display_name = self.get_display_name_by_import_path(import_path)
            toolpalette = self.toolpalettegroup.append_new_palette(display_name)
            for locker_control in locker_controls.values():
                toolpalette.addWidget(locker_control, force_relayout=True)

        # Set the icon and text color used at the top of the tab.
        self.set_tab_icon_and_colour()

    def get_display_name_by_import_path(self, import_path):
        """Get the display name of a locker from its import path.

        Args:
            import_path (str): The import path of the locker instance.

        Returns:
            display_name (str): The display name of the locker/laser.
        """
        return self.plugin.get_display_name_by_import_path(import_path)

    def _make_set_monitoring_enabled(self, import_path, control):
        """Create a callback for when the "Monitor Enable" control is clicked.

        For technical reasons associated with namespaces, the callback method is
        defined in this method instead of with a lambda function in
        `self.add_GUI_widgets()`.

        Args:
            import_path (str): The import path of the locker instance.
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control for which to create the callback.
        """
        def _set_monitoring_enabled():
            self.plugin.set_monitoring_enabled(import_path, control.state)
            self._update_monitoring_enable_control(control)
        return _set_monitoring_enabled

    def _make_set_locking_enabled(self, import_path, control):
        """Create a callback for when the "Locking Enable" control is clicked.

        For technical reasons associated with namespaces, the callback method is
        defined in this method instead of with a lambda function in
        `self.add_GUI_widgets()`.

        Args:
            import_path (str): The import path of the locker instance.
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control for which to create the callback.
        """
        def _set_locking_enabled():
            self.plugin.set_locking_enabled(import_path, control.state)
            self._update_locking_enable_control(control)
        return _set_locking_enabled

    def _make_set_force_lock(self, import_path, control):
        """Create a callback for when the "Force Lock" control is clicked.

        For technical reasons associated with namespaces, the callback method is
        defined in this method instead of with a lambda function in
        `self.add_GUI_widgets()`.

        Args:
            import_path (str): The import path of the locker instance.
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control for which to create the callback.
        """
        def _set_force_lock():
            self.plugin.set_force_lock(import_path, control.state)
        return _set_force_lock

    def _make_set_restart_worker(self, import_path, control):
        """Create a callback for when the "Restart Worker" control is clicked.

        For technical reasons associated with namespaces, the callback method is
        defined in this method instead of with a lambda function in
        `self.add_GUI_widgets()`.

        Args:
            import_path (str): The import path of the locker instance.
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control for which to create the callback.
        """
        def _set_restart_worker():
            self.plugin.set_restart_worker(import_path, control.state)
        return _set_restart_worker

    @inmain_decorator(wait_for_return=True)
    def _update_monitoring_enable_control(self, control):
        """Update the monitoring enable control to reflect its current state.

        This method changes the icon and text to reflect the current state of
        the control.

        Args:
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control to update, which should be the monitoring enable control
                for a locker.
        """
        if control.state:
            control.setIcon(QIcon(self._ICON_MONITOR_ENABLE_TRUE))
            control.setText(self._TEXT_MONITOR_ENABLE_TRUE)
        else:
            control.setIcon(QIcon(self._ICON_MONITOR_ENABLE_FALSE))
            control.setText(self._TEXT_MONITOR_ENABLE_FALSE)

    @inmain_decorator(wait_for_return=True)
    def _update_locking_enable_control(self, control):
        """Update the locking enable control to reflect its current state.

        This method changes the icon and text to reflect the current state of
        the control.

        Args:
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control to update, which should be the locking enable control
                for a locker.
        """
        if control.state:
            control.setIcon(QIcon(self._ICON_LOCKING_ENABLE_TRUE))
            control.setText(self._TEXT_LOCKING_ENABLE_TRUE)
        else:
            control.setIcon(QIcon(self._ICON_LOCKING_ENABLE_FALSE))
            control.setText(self._TEXT_LOCKING_ENABLE_FALSE)

    @inmain_decorator(wait_for_return=True)
    def set_force_lock_enabled(self, import_path, enabled):
        """Set the state of the force lock control for a locker.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): The desired state of the control.
        """
        # Get the force lock control for the locker.
        control = self.controls[import_path]['force_lock']
        # Set its state to the desired value.
        control.state = enabled

    @inmain_decorator(wait_for_return=True)
    def set_restart_worker_enabled(self, import_path, enabled):
        """Set the state of the restart worker control for a locker.

        Args:
            import_path (str): The import path of the locker instance.
            enabled (bool): The desired state of the control.
        """
        # Get the force lock control for the locker.
        control = self.controls[import_path]['restart_worker']
        # Set its state to the desired value.
        control.state = enabled

    def get_save_data(self):
        # Save data for controls as a dictionary of dictionaries, with one
        # sub-dictionary for each laser. Each laser's dictionary will store the
        # current value of its controls.
        plugin = self.plugin
        save_data = {}
        for import_path in self.locker_import_paths:
            locker_data = {}

            # Monitoring enable control.
            control = self.controls[import_path]['monitoring_enable']
            is_enabled = plugin.get_monitoring_enabled(import_path)
            is_locked = not control.isEnabled()
            locker_data['monitoring_enable_state'] = is_enabled
            locker_data['monitoring_enable_locked'] = is_locked

            # Locking enable control.
            control = self.controls[import_path]['locking_enable']
            is_enabled = plugin.get_locking_enabled(import_path)
            is_locked = not control.isEnabled()
            locker_data['locking_enable_state'] = is_enabled
            locker_data['locking_enable_locked'] = is_locked

            # Force lock control.
            control = self.controls[import_path]['force_lock']
            is_locked = not control.isEnabled()
            locker_data['force_lock_locked'] = is_locked

            # Restart worker control.
            control = self.controls[import_path]['restart_worker']
            is_locked = not control.isEnabled()
            locker_data['restart_worker_locked'] = is_locked

            save_data[import_path] = locker_data

        # Store the visibility state of the output box and the position of the
        # splitter. Based on blacs.tab_base_classes.Tab.get_builtin_save_data().
        save_data['terminal_visible'] = self.button_show_terminal.isChecked()
        save_data['splitter_sizes'] = self.splitter.sizes()
        return save_data

    def restore_save_data(self, data):
        # Store the saved data for self.apply_save_data(). The settings for the
        # controls will be restored there once the plugin has set some necessary
        # tab attribute values.
        self._saved_settings = data

        # Restore settings for the terminal output box and splitter. Based on
        # blacs.tab_base_classes.Tab.restore_builtin_save_data().
        terminal_visible = data.get('terminal_visible', False)
        self._set_terminal_visible(terminal_visible)
        if 'splitter_sizes' in data:
            self.splitter.setSizes(data['splitter_sizes'])

    def apply_save_data(self):
        for import_path in self.locker_import_paths:
            # Get this laser's saved settings, defaulting to an empty dict if
            # they are not available.
            locker_data = self._saved_settings.get(import_path, {})
            controls = self.controls[import_path]

            # Monitoring enable control.
            control = controls['monitoring_enable']
            # Restore state for monitoring_enable, defaulting to True if its
            # value wasn't loaded.
            setting = 'monitoring_enable_state'
            setting_value = bool(locker_data.get(setting, True))
            control.state = setting_value
            self._update_monitoring_enable_control(control)
            self.plugin.set_monitoring_enabled(import_path, setting_value)
            # Restore whether or not the control is locked, defaulting to False
            # if its value wasn't loaded.
            setting = 'monitoring_enable_locked'
            setting_value = bool(locker_data.get(setting, False))
            self._set_control_locked_state(control, setting_value)

            # Locking enable control.
            control = controls['locking_enable']
            # Restore state for locking_enable, defaulting to True if its value
            # wasn't loaded.
            setting = 'locking_enable_state'
            setting_value = bool(locker_data.get(setting, True))
            control.state = setting_value
            self._update_locking_enable_control(control)
            self.plugin.set_locking_enabled(import_path, setting_value)
            # Restore whether or not the control is locked, defaulting to False
            # if its value wasn't loaded.
            setting = 'locking_enable_locked'
            setting_value = bool(locker_data.get(setting, False))
            self._set_control_locked_state(control, setting_value)

            # Force lock control.
            control = controls['force_lock']
            # Restore whether or not the control is locked, defaulting to False
            # if its value wasn't loaded.
            setting = 'force_lock_locked'
            setting_value = bool(locker_data.get(setting, False))
            self._set_control_locked_state(control, setting_value)

            # Restart worker control.
            control = controls['restart_worker']
            # Restore whether or not the control is locked, defaulting to False
            # if its value wasn't loaded.
            setting = 'restart_worker_locked'
            setting_value = bool(locker_data.get(setting, False))
            self._set_control_locked_state(control, setting_value)

    def _set_control_locked_state(self, control, lock):
        """Set whether or not a control is "locked".

        When a control is "locked" it ignores left mouse clicks. This is not the
        same meaning of lock as "locking a laser".

        Args:
            control (labscript_utils.qtwidgets.digitaloutput.DigitalOutput): The
                control for which to set the "locked" state.
            lock (bool): Whether or not the control should be locked. Set to
                `True` to lock the control so that it ignores inputs that would
                change its value. Set to `False` to make it respond to attempts
                to change its value.
        """
        if lock:
            control.lock()
        else:
            control.unlock()

    def close_tab(self, **kwargs):
        self.output_box.shutdown()
        return super().close_tab(**kwargs)


class LockMonitorWorker(Worker):
    def worker_init(self, import_path):
        """Initialize the worker.

        Note that this method does NOT call the `init()` method of the locker.
        If simply imports the locker instance and requests its `display_name`.

        Args:
            import_path (str): The import path of the locker instance.
        """
        # Don't call lockers' init() method here. We want this to return asap so
        # that the value of display_name can be returned for use in the GUI. The
        # plugin will call locker_init() to actually run the init() method of
        # the locker later since that method may take a while.
        self.import_path = import_path
        # Split the import path at the last dot. Everything before that is the
        # module and the part after it is the name of the locker. For example
        # 'module.submodule.locker_instance' would be split into
        # 'module.submodule' and 'locker_instance'. Then module.submodule would
        # be imported and self.locker would be set to
        # module.submodule.locker_instance.
        module_name, locker_name = import_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
        self.locker = getattr(module, locker_name)
        self.display_name = self.locker.get_display_name()

    def get_display_name(self):
        """Get the display name of the locker.

        Returns:
            str: The display name for the locker.
        """
        return self.display_name

    def locker_init(self):
        """Call the locker's `init()` method."""
        return self.locker.init()

    def _run_locker_callback(self, callback_name, path):
        """Run the specified callback method of the locker.

        Args:
            callback_name (str): The name of the callback to run.
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            bool: The value returned by the locker's callback method.
        """
        try:
            callback = getattr(self.locker, callback_name)
        except AttributeError:
            return 'callback_not_supported'
        else:
            return callback(path)

    def callback_pre_transition_to_buffered(self, path):
        """Run the locker's `callback_pre_transition_to_buffered()` method.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            bool: The value returned by the locker's callback method.
        """
        result = self._run_locker_callback(
            'callback_pre_transition_to_buffered',
            path,
        )
        return result

    def callback_science_starting(self, path):
        """Run the locker's `callback_science_starting()` method.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            bool: The value returned by the locker's callback method.
        """
        result = self._run_locker_callback(
            'callback_science_starting',
            path,
        )
        return result

    def callback_science_over(self, path):
        """Run the locker's `callback_science_over()` method.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            bool: The value returned by the locker's callback method.
        """
        result = self._run_locker_callback(
            'callback_science_over',
            path,
        )
        return result

    def callback_analysis_cancel_send(self, path):
        """Run the locker's `callback_analysis_cancel_send()` method.

        Args:
            path (str): The path to the hdf5 file of the currently running shot.

        Returns:
            bool: The value returned by the locker's callback method.
        """
        result = self._run_locker_callback(
            'callback_analysis_cancel_send',
            path,
        )
        return result

    def lock(self):
        """Run the locker's `lock()` method.

        Returns:
            bool: The value returned by the locker's `lock()` method. That
                should be set to `True` if the laser was successfully locked and
                `False` otherwise.
        """
        return self.locker.lock()

    def close(self):
        """Run the locker's `close()` method."""
        self.locker.close()


logger.info("Imported lock_monitor.")
