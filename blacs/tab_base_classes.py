#####################################################################
#                                                                   #
# /tab_base_classes.py                                              #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
from zprocess import Process, Interruptor, Interrupted, interrupt_main_thread
import time
import sys
import signal
import threading
import traceback
import logging
import warnings
import queue
import pickle
from html import escape
import os
from types import GeneratorType
from bisect import insort

from qtutils.qt.QtCore import Qt, QTimer
from qtutils.qt.QtGui import QIcon, QColor, QPalette
from qtutils.qt.QtWidgets import QLabel, QWidget, QPushButton, QApplication, QVBoxLayout

from qtutils import inmain_decorator, inmain, inmain_later, inthread, UiLoader
from labscript_utils.qtwidgets.outputbox import OutputBox
import qtutils.icons

from labscript_utils.qtwidgets.elide_label import elide_label
from labscript_utils.ls_zprocess import ProcessTree, RemoteProcessClient
from labscript_utils.shared_drive import path_to_local
from blacs import BLACS_DIR

process_tree = ProcessTree.instance()
from labscript_utils import dedent


class Counter(object):
    """A class with a single method that 
    returns a different integer each time it's called."""
    def __init__(self):
        self.i = 0
    def get(self):
        self.i += 1
        return self.i
        
        
MODE_MANUAL = 1
MODE_TRANSITION_TO_BUFFERED = 2
MODE_TRANSITION_TO_MANUAL = 4
MODE_BUFFERED = 8  

# Duration in seconds for which a worker that has been told to quit waits for its
# interrupted job to stop:
WORKER_ABORT_TIMEOUT = 5
# Duration in seconds for which a worker with a job that did not stop waits for its HDF5
# files to be closed before it exits:
WORKER_KILL_LOCK_TIMEOUT = 60
# Duration in seconds for which a tab waits for a worker to exit before killing it:
WORKER_QUIT_TIMEOUT = WORKER_ABORT_TIMEOUT + WORKER_KILL_LOCK_TIMEOUT + 5
            
class StateQueue(object):
    """The queued states of a tab, in order of priority and then of insertion. Only the
    main thread accesses the queue; put() called from another thread runs in the main
    thread."""

    def __init__(self, device_name, on_put):
        self.logger = logging.getLogger('BLACS.%s.state_queue'%(device_name))
        self.logging_enabled = False
        if self.logging_enabled:
            self.logger.debug("started")
        
        self.list_of_states = []
        self._on_put = on_put

    def log_current_states(self):
        if self.logging_enabled:
            self.logger.debug('Current items in the state queue: %s', self.list_of_states)

    @inmain_decorator(True)
    def put(self, allowed_states, queue_state_indefinitely, delete_stale_states, data, priority=0):
        """Add a state to the queue. Lower number for priority indicates the state will
        be executed before any states with higher numbers for their priority"""
        # State data starts with priority, and then with a unique id that monotonically
        # increases. This way, sorting the queue will sort first by priority and then by
        # order added.
        state_data = [priority, get_unique_id(), allowed_states, queue_state_indefinitely, delete_stale_states,data]
        # Insert the task into the queue, retaining sort order first by priority and then by order added:
        insort(self.list_of_states, state_data)
        if self.logging_enabled:
            if not isinstance(data[0],str):
                self.logger.debug('New state queued up. Allowed modes: %d, queue state indefinitely: %s, delete stale states: %s, function: %s', allowed_states, queue_state_indefinitely, delete_stale_states, data[0].__name__)
        self.log_current_states()
        self._on_put()

    def get(self, state):
        """Remove and return the data of the first state that is allowed in the given
        mode, or None if there is none. States that are not queued indefinitely and come
        before it are removed."""
        # traverse the list
        delete_index_list = []
        success = False
        for i,item in enumerate(self.list_of_states):
            priority, unique_id, allowed_states, queue_state_indefinitely, delete_stale_states, data = item
            if self.logging_enabled:
                self.logger.debug('iterating over states in queue')
            if allowed_states&state:
                # We have found one! Remove it from the list
                delete_index_list.append(i)
                
                if self.logging_enabled:
                    self.logger.debug('requested state found in queue')
                
                # If we are to delete stale states, see if the next state is the same statefunction.
                # If it is, use that one, or whichever is the latest entry without encountering a different statefunction,
                # and delete the rest
                if delete_stale_states:
                    state_function = data[0]
                    i+=1
                    while i < len(self.list_of_states) and state_function == self.list_of_states[i][5][0]:
                        if self.logging_enabled:
                            self.logger.debug('requesting deletion of stale state')
                        priority, unique_id, allowed_states, queue_state_indefinitely, delete_stale_states, data = self.list_of_states[i]
                        delete_index_list.append(i)
                        i+=1
                
                success = True
                break
            elif not queue_state_indefinitely:
                if self.logging_enabled:
                    self.logger.debug('state should not be queued indefinitely')
                delete_index_list.append(i)
        
        # do this in reverse order so that the first delete operation doesn't mess up the indices of subsequent ones
        for index in reversed(sorted(delete_index_list)):
            if self.logging_enabled:
                self.logger.debug('deleting state')
            del self.list_of_states[index]
            
        if not success:
            data = None
        return data


class StateMachine(object):
    """Runs the queued states of a tab in the main thread, one at a time. A state
    function that is a generator yields jobs for the workers. A job thread sends each
    job to its worker and waits for the result, and the result is sent into the
    generator in the main thread."""

    def __init__(self, tab):
        self.tab = tab
        self.logger = logging.getLogger('BLACS.%s.mainloop' % tab.device_name)
        self.event_queue = StateQueue(tab.device_name, self.schedule)
        self.workers = tab.workers
        self.closed = False
        self.failed = False
        self._scheduled = False
        self._state_name = None
        self._generator = None
        self._job = None
        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._job_loop, daemon=True)
        self._thread.start()
        self.logger.debug('Waiting for next event')

    def schedule(self):
        """Run the next state in a later iteration of the event loop. Called in the main
        thread."""
        if not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(0, self._run_next_state)

    def _run_next_state(self):
        self._scheduled = False
        if self.closed or self.failed or self._state_name is not None:
            return
        data = self.event_queue.get(self.tab.mode)
        if data is None:
            return
        func, (args, kwargs) = data
        self._state_name = func.__name__
        self._job = None
        self.logger.debug('Processing event %s', self._state_name)
        self.tab.state = '%s (GUI)' % self._state_name
        try:
            generator = func(self.tab, *args, **kwargs)
        except Exception:
            self._fatal_error(traceback.format_exc())
            return
        if isinstance(generator, GeneratorType):
            self._generator = generator
            self._advance(generator.__next__)
        else:
            self._state_finished()

    def _advance(self, step, *args):
        """Run the generator of the current state to its next yield, and pass the job
        that it yields to the job thread. A yield of None after the first yield repeats
        the previous job."""
        try:
            job = step(*args)
            if job or self._job is None:
                self._job = job
            worker_name, worker_function, _, _ = self._job
        except StopIteration:
            self.logger.debug('Finalising function')
            self._generator = None
            self._state_finished()
            return
        except Exception:
            self._fatal_error(traceback.format_exc())
            return
        self.logger.debug('Instructing worker %s to do job %s', worker_name, worker_function)
        if worker_function == 'init':
            self.tab.state = 'Starting worker process (%s)' % worker_name
        else:
            self.tab.state = '%s (%s)' % (worker_function, worker_name)
        self._jobs.put(self._job)

    def _state_finished(self):
        self._state_name = None
        if self.closed:
            return
        self.tab.state = 'idle'
        self.logger.debug('Waiting for next event')
        self.schedule()

    def _job_loop(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                result = self._do_job(*job)
            except Interrupted:
                self.logger.debug('Interrupted by tab restart, quitting job thread')
                return
            except Exception:
                inmain_later(self._fatal_error, traceback.format_exc())
                return
            inmain_later(self._job_done, *result)

    def _do_job(self, worker_name, worker_function, args, kwargs):
        """Send a job to a worker and return its success, error message and results.
        Runs in the job thread."""
        if worker_function == 'init':
            # Start the worker process before running its init() method:
            worker, _, _ = self.workers[worker_name]
            to_worker, from_worker = worker.start(*args)
            self.workers[worker_name] = (worker, to_worker, from_worker)
            args = ()
            del worker # Do not hold a reference indefinitely
            inmain_later(self._set_state, 'init (%s)' % worker_name)
        worker_arg_list = (worker_function, args, kwargs)
        try:
            pickle.dumps(worker_arg_list)
        except Exception as e:
            raise RuntimeError('Attempt to pass unserialisable object to child process') from e
        _, to_worker, from_worker = self.workers[worker_name]
        to_worker.put(worker_arg_list)
        self.logger.debug('Waiting for worker to acknowledge job request')
        success, message, results = from_worker.get()
        if not success:
            self.logger.info('Worker reported failure to start job')
            raise RuntimeError(message)
        self.logger.debug('Worker reported job started, waiting for completion')
        success, message, results = from_worker.get()
        if success:
            self.logger.debug('Job completed')
        else:
            self.logger.info('Worker reported exception during job')
        return success, message, results

    def _set_state(self, state):
        if not self.closed:
            self.tab.state = state

    def _job_done(self, success, message, results):
        if self.closed or self.failed:
            return
        tab = self.tab
        if not success:
            now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
            tab.error_message += ('Exception in worker - %s:<br />' % now +
                           '<FONT COLOR=\'#ff0000\'>%s</FONT><br />'%escape(message).replace(' ','&nbsp;').replace('\n','<br />'))
        # Reset the hide_not_responding_error_until, since we have now heard from the child
        tab.hide_not_responding_error_until = 0
        self.logger.debug('returning worker results to function %s', self._state_name)
        tab.state = '%s (GUI)' % self._state_name
        self._advance(self._generator.send, results)

    def _fatal_error(self, message):
        """Stop running states and show the error. Called in the main thread."""
        if self.closed or self.failed:
            return
        self.failed = True
        self._generator = None
        self.logger.critical('A fatal exception happened:\n %s', message)
        tab = self.tab
        now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
        tab.error_message += ('Fatal exception in main process - %s:<br /> '%now +
                       '<FONT COLOR=\'#ff0000\'>%s</FONT><br />'%escape(message).replace(' ','&nbsp;').replace('\n','<br />'))
        tab.state = 'fatal error'
        tab._ui.button_close.setEnabled(False)
        self.logger.info('Exiting')
        inthread(tab._end_workers)

    def close(self):
        """Stop running states, interrupt any communication with the workers, and stop
        the job thread. Called in the main thread."""
        if self.closed:
            return
        self.closed = True
        self._generator = None
        for worker, to_worker, from_worker in self.workers.values():
            # If the worker is still starting up, interrupt any blocking operations:
            worker.interrupt_startup()
            # Interrupt the read and write queues in case the job thread is blocking on
            # sending or receiving from them:
            if to_worker is not None:
                to_worker.interrupt()
                from_worker.interrupt()
        self._jobs.put(None)

    def join(self, timeout):
        self._thread.join(timeout)
        return not self._thread.is_alive()


# A counter for uniqely numbering timeouts and numbering queued states monotinically,
# such that sort order coresponds to the order the state was added to the queue:
get_unique_id = Counter().get

def define_state(allowed_modes,queue_state_indefinitely,delete_stale_states=False):
    def wrap(function):
        unescaped_name = function.__name__
        escapedname = '_' + function.__name__
        if allowed_modes < 1 or allowed_modes > 15:
            raise RuntimeError('Function %s has been set to run in unknown states. Please make sure allowed states is one or more of MODE_MANUAL,'%unescaped_name+
            'MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL and MODE_BUFFERED (or-ed together using the | symbol, eg MODE_MANUAL|MODE_BUFFERED')
        def f(self,*args,**kwargs):
            function.__name__ = escapedname
            #setattr(self,escapedname,function)
            self.event_queue.put(allowed_modes,queue_state_indefinitely,delete_stale_states,[function,[args,kwargs]])
        f.__name__ = unescaped_name
        f._allowed_modes = allowed_modes
        return f        
    return wrap
    
        
class Tab(object):

    ICON_OK = ':/qtutils/fugue/tick'
    ICON_BUSY = ':/qtutils/fugue/hourglass'
    ICON_ERROR = ':/qtutils/fugue/exclamation'
    ICON_FATAL_ERROR = ':/qtutils/fugue/exclamation-red'
    ICON_STOPPED = ':/qtutils/fugue/control-stop-square'
    ICON_START = ':/qtutils/fugue/control'

    # Duration in seconds for which a restart or stop waits for the workers' shutdown()
    # methods to return before it ends the workers:
    SHUTDOWN_TIMEOUT = 2

    def __init__(self,notebook,settings,restart=False):  
        # Store important parameters
        self.notebook = notebook
        self.settings = settings
        self._device_name = self.settings["device_name"]
        
        # Setup logging
        self.logger = logging.getLogger('BLACS.%s'%(self.device_name))   
        self.logger.debug('Started')          
        
        # Setup the timer for updating that tab text label when the tab is not 
        # actively part of a notebook
        self._tab_icon_and_colour_timer = QTimer()
        self._tab_icon_and_colour_timer.timeout.connect(self.set_tab_icon_and_colour)
        self._tab_icon = self.ICON_OK
        # The notebook, tab index, icon and text colour last set on the tab:
        self._applied_tab_icon_and_colour = None

        # Create instance variables
        self._not_responding_error_message = ''
        self._error = ''
        self._error_html = None
        self._state = ''
        self._time_of_last_state_change = time.time()
        self.not_responding_for = 0
        self.hide_not_responding_error_until = 0
        self._timeouts = set()
        self._timeout_ids = {}
        self._force_full_buffered_reprogram = True
        self.workers = {}
        self._supports_smart_programming = False
        self._restart_receiver = []
        self.shutdown_workers_complete = False
        self._end_workers_lock = threading.Lock()

        self.remote_process_client = self._get_remote_configuration()
        self.BLACS_connection = self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection

        # Load the UI
        self._ui = UiLoader().load(os.path.join(BLACS_DIR, 'tab_frame.ui'))
        # set tab text color from palette to respect OS theme changes
        self._tab_text_colour = self._ui.palette().color(QPalette.ColorRole.Text)
        self._layout = self._ui.device_layout
        self._device_widget = self._ui.device_controls
        self._changed_widget = self._ui.changed_widget
        self._changed_layout = self._ui.changed_layout
        self._changed_widget.hide()        
        
        conn_str = self.BLACS_connection
        if self.remote_process_client is not None:
            conn_str += " via %s:%d" % (self.remote_process_client.host, self.remote_process_client.port)
        
        self._ui.device_name.setText(
            "<b>%s</b> [conn: %s]" % (str(self.device_name), conn_str)
        )
        elide_label(self._ui.device_name, self._ui.horizontalLayout, Qt.ElideRight)
        elide_label(self._ui.state_label, self._ui.state_label_layout, Qt.ElideRight)

        # Insert an OutputBox into the splitter, initially hidden:
        self._output_box = OutputBox(self._ui.splitter)
        self._ui.splitter.setCollapsible(self._ui.splitter.count() - 2, True)
        self._output_box.output_textedit.hide()

        # connect signals
        self._ui.button_clear_smart_programming.clicked.connect(self.on_force_full_buffered_reprogram)
        self._ui.button_clear_smart_programming.setEnabled(False)
        self.force_full_buffered_reprogram = True
        self._ui.button_show_terminal.toggled.connect(self.set_terminal_visible)
        self._ui.button_close.clicked.connect(self.hide_error)
        self._ui.button_restart.clicked.connect(self.restart)
        self._ui.button_stop.clicked.connect(self._on_stop_clicked)
        self._update_error_and_tab_icon()
        self.supports_smart_programming(False)
        
        # Restore settings:
        self.restore_builtin_save_data(self.settings.get('saved_data', {}))

        # This must be done after the UI is created:
        self._state_display_update_pending = False
        self.mode = MODE_MANUAL
        self.state = 'idle'
        
        # Setup the not responding timeout
        self._timeout = QTimer()
        self._timeout.timeout.connect(self.check_time)
        self._timeout.start(1000)
                
        self._statemachine = StateMachine(self)
        self.event_queue = self._statemachine.event_queue
                
        # Add the tab to the notebook
        self.notebook.addTab(self._ui,self.device_name)
    
    def _get_remote_configuration(self):
        # Create and return zprocess remote process client, if the device is configured
        # as a remote device, else None:
        PRIMARY_BLACS = '__PrimaryBLACS'
        table = self.settings['connection_table']
        properties = table.find_by_name(self.device_name).properties
        if properties.get('gui', PRIMARY_BLACS) != PRIMARY_BLACS:
            msg = "Remote BLACS GUIs not yet supported by BLACS"
            raise NotImplementedError(msg)
        remote_server_name = properties.get('worker', PRIMARY_BLACS)
        if remote_server_name != PRIMARY_BLACS:
            remote_server_device = table.find_by_name(remote_server_name)
            if remote_server_device.parent.name != PRIMARY_BLACS:
                msg = "Multi-hop remote workers not yet supported by BLACS"
                raise NotImplementedError(msg) 
            remote_host, remote_port = remote_server_device.parent_port.rsplit(':', 1)
            remote_port = int(remote_port)
            return RemoteProcessClient(remote_host, remote_port)
        return None

    def get_builtin_save_data(self):
        """Get builtin settings to be restored like whether the terminal is
        visible. Not to be overridden."""
        return {'_terminal_visible': self._ui.button_show_terminal.isChecked(),
                '_splitter_sizes': self._ui.splitter.sizes()}

    def get_device_save_data(self):
        """Get the settings returned by the get_save_data() method of the subclass,
        such as camera acquisition settings."""
        if hasattr(self, 'get_save_data'):
            tab_save_data = self.get_save_data()
            if isinstance(tab_save_data, dict):
                return tab_save_data
            self.logger.warning('Incorrect format for tab save data from the get_save_data() method. Data should be a dict. Data was: %s', tab_save_data)
        return {}

    def get_all_save_data(self):
        save_data = self.get_builtin_save_data()
        save_data.update(self.get_device_save_data())
        return save_data

    def restore_builtin_save_data(self, data):
        """Restore builtin settings to be restored like whether the terminal is
        visible. Not to be overridden. Settings missing from data are not changed."""
        if '_terminal_visible' in data:
            self.set_terminal_visible(data['_terminal_visible'])
        if '_splitter_sizes' in data:
            self._ui.splitter.setSizes(data['_splitter_sizes'])

    def update_from_settings(self, settings):
        self.restore_builtin_save_data(settings['saved_data'])

    def supports_smart_programming(self,support):
        self._supports_smart_programming = bool(support)
        if self._supports_smart_programming:
            self._ui.button_clear_smart_programming.show()
        else:
            self._ui.button_clear_smart_programming.hide()
    
    def on_force_full_buffered_reprogram(self):
        self.force_full_buffered_reprogram = True

    @property
    def force_full_buffered_reprogram(self):
        return self._force_full_buffered_reprogram
        
    @force_full_buffered_reprogram.setter
    def force_full_buffered_reprogram(self,value):
        self._force_full_buffered_reprogram = bool(value)
        self._ui.button_clear_smart_programming.setEnabled(not bool(value))
    
    @property
    @inmain_decorator(True)
    def error_message(self):
        return self._error
    
    @error_message.setter
    @inmain_decorator(True)
    def error_message(self,message):
        #print message
        #print self._error
        if message != self._error:
            self._error = message
            self._update_error_and_tab_icon()
    
    @inmain_decorator(True)
    def _update_error_and_tab_icon(self):
        """Udate and show the error message for the tab, and update the icon
        and text colour on the tab"""
        prefix = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">\n<html><head><meta name="qrichtext" content="1" /><style type="text/css">\np, li { white-space: pre-wrap; }\n</style></head><body style=" font-family:"MS Shell Dlg 2"; font-size:7.8pt; font-weight:400; font-style:normal;">'
        suffix = '</body></html>'
        #print threading.current_thread().name
        error_html = prefix+self._not_responding_error_message+self._error+suffix
        if error_html != self._error_html:
            self._error_html = error_html
            self._ui.error_message.setHtml(error_html)
        if self.state in ('stopping', 'stopped'):
            self._ui.notresponding.show()
            self._tab_text_colour = QColor('grey')
            if self.state == 'stopped':
                self._tab_icon = self.ICON_STOPPED
            else:
                self._tab_icon = self.ICON_BUSY
        elif self._error or self._not_responding_error_message:
            self._ui.notresponding.show()
            self._tab_text_colour = QColor('red')
            if self.error_message:
                if self.state == 'fatal error':
                    self._tab_icon = self.ICON_FATAL_ERROR
                else: 
                    self._tab_icon = self.ICON_ERROR
        else:
            self._ui.notresponding.hide()
            # set tab text color from palette to respect OS theme changes
            self._tab_text_colour = self._ui.palette().color(QPalette.ColorRole.Text)
            if self.state == 'idle':
                self._tab_icon = self.ICON_OK
            else:
                self._tab_icon = self.ICON_BUSY
        self.set_tab_icon_and_colour()
    
    @inmain_decorator(True)
    def set_tab_icon_and_colour(self):
        """Set the tab icon and the colour of its text to the values of
        self._tab_icon and self._tab_text_colour respectively"""
        if self._ui.parentWidget() is None:
            return
        self.notebook = self._ui.parentWidget().parentWidget()
        if self.notebook is not None:
            currentpage = self.notebook.indexOf(self._ui)
            if currentpage == -1:
                # shutting down:
                return
            applied = (self.notebook, currentpage, self._tab_icon, QColor(self._tab_text_colour))
            if applied == self._applied_tab_icon_and_colour:
                return
            self._applied_tab_icon_and_colour = applied
            icon = QIcon(self._tab_icon)
            self.notebook.tabBar().setTabIcon(currentpage, icon)
            self.notebook.tabBar().setTabTextColor(currentpage, self._tab_text_colour)
    
    def get_tab_layout(self):
        return self._layout
    
    @property
    def device_name(self):
        return self._device_name
    
    # sets the mode, switches between MANUAL, BUFFERED, TRANSITION_TO_BUFFERED and TRANSITION_TO_STATIC
    @property
    def mode(self):
        return self._mode
    
    @mode.setter
    def mode(self,mode):
        self._mode = mode
        self._update_state_label()
        
    @property
    def state(self):
        return self._state
        
    @state.setter
    def state(self,state):
        self._state = state        
        self._time_of_last_state_change = time.time()
        self._queue_state_display_update()

    def _queue_state_display_update(self):
        """Post an update of the state label and tab icon to the main thread without
        waiting for it to run. An update requested while one is already posted is
        merged into it."""
        if self._state_display_update_pending:
            return
        self._state_display_update_pending = True
        inmain_later(self._update_state_display)

    def _update_state_display(self):
        # Runs in the main thread. The pending flag is cleared before the state is
        # read, so that a state set after this point posts another update.
        self._state_display_update_pending = False
        self._update_state_label()
        self._update_error_and_tab_icon()
        self._update_stop_button()

    def _update_stop_button(self):
        """Show the stop button as a start button while the workers are not running"""
        if self.state in ('stopped', 'fatal error'):
            icon = self.ICON_START
            tooltip = 'Start the worker processes and initialise the device'
        else:
            icon = self.ICON_STOPPED
            tooltip = 'Stop the worker processes and release the device'
        if self._ui.button_stop.toolTip() != tooltip:
            self._ui.button_stop.setIcon(QIcon(icon))
            self._ui.button_stop.setToolTip(tooltip)
    
    @inmain_decorator(True)
    def _update_state_label(self):
        if self.mode == 1:
            mode = 'Manual'
        elif self.mode == 2:
            mode = 'Transitioning to buffered'
        elif self.mode == 4:
            mode = 'Transitioning to manual'
        elif self.mode == 8:
            mode = 'Buffered'
        else:
            raise RuntimeError('self.mode for device %s is invalid. It must be one of MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL or MODE_BUFFERED'%(self.device_name))
    
        self._ui.state_label.setText('<b>%s mode</b> - State: %s'%(mode,self.state))
        
        # Todo: Update icon in tab
    
    def create_worker(self,name,WorkerClass,workerargs=None):
        """Set up a worker process. WorkerClass can either be a subclass of Worker, or a
        string containing a fully qualified import path to a worker. The latter is
        useful if the worker class is in a separate file with global imports or other
        import-time behaviour that is undesirable to have run in the main process, for
        example if the imports may not be available to the main process (as may be the
        case once remote worker processes are implemented and the worker may be on a
        separate computer). The worker process will not be started immediately, it will
        be started when the state machine runs its first state. This way errors in
        startup will be handled using the normal state machine machinery."""

        if workerargs is None:
            workerargs = {}
        # Add all connection table properties, if they were not already specified in
        # workerargs:
        conntable = self.settings['connection_table']
        for key, value in conntable.find_by_name(self.device_name).properties.items():
            workerargs.setdefault(key, value)
        workerargs['is_remote'] = self.remote_process_client is not None

        if name in self.workers:
            raise Exception('There is already a worker process with name: %s'%name) 
        if name == 'GUI':
            # This is here so that we can display "(GUI)" in the status bar and have the user confident this is actually happening in the GUI,
            # not in a worker process named GUI
            raise Exception('You cannot call a worker process "GUI". Why would you want to? Your worker process cannot interact with the BLACS GUI directly, so you are just trying to confuse yourself!')
        
        if isinstance(WorkerClass, type):
            worker = WorkerClass(
                process_tree,
                output_redirection_port=self._output_box.port,
                remote_process_client=self.remote_process_client,
                startup_timeout=30
                )
        elif isinstance(WorkerClass, str):
            # If we were passed a string for the WorkerClass, it is an import path
            # for where the Worker class can be found. Pass it to zprocess.Process,
            # which will do the import in the subprocess only.
            worker = Process(
                process_tree,
                output_redirection_port=self._output_box.port,
                remote_process_client=self.remote_process_client,
                startup_timeout=30,
                subclass_fullname=WorkerClass
            )
        else:
            raise TypeError(WorkerClass)
        self.workers[name] = (worker,None,None)
        self.event_queue.put(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True,False,[Tab._initialise_worker,[(name, workerargs),{}]], priority=-1)
       
    def _initialise_worker(self, worker_name, workerargs):
        yield (self.queue_work(worker_name, 'init', worker_name, self.device_name, workerargs))
        if self.error_message:
            raise Exception('Device failed to initialise')
               
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)  
    def _timeout_add(self,delay,execute_timeout):
        QTimer.singleShot(delay,execute_timeout)
    
    def statemachine_timeout_add(self,delay,statefunction,*args,**kwargs):
        # Add the timeout to our set of registered timeouts. Timeouts
        # can thus be removed by the user at ay time by calling
        # self.timeouts.remove(function)
        self._timeouts.add(statefunction)
        # Here's a function which executes the timeout once, then queues
        # itself up again after a delay:
        def execute_timeout():
            # queue up the state function, but only if it hasn't been
            # removed from self.timeouts:
            if statefunction in self._timeouts and self._timeout_ids[statefunction] == unique_id:
                # Only queue up the state if we are in an allowed mode
                if statefunction._allowed_modes&self.mode:
                    statefunction(*args, **kwargs)
                # queue up another call to this function (execute_timeout)
                # after the delay time:
                self._timeout_add(delay,execute_timeout)
            
        # Store a unique ID for this timeout so that we don't confuse 
        # other timeouts for this one when checking to see that this
        # timeout hasn't been removed:
        unique_id = get_unique_id()
        self._timeout_ids[statefunction] = unique_id
        # queue the first run:
        #QTimer.singleShot(delay,execute_timeout)    
        execute_timeout()
        
    # Returns True if the timeout was removed
    def statemachine_timeout_remove(self,statefunction):
        if statefunction in self._timeouts:
            self._timeouts.remove(statefunction)
            return True
        return False
    
    # returns True if at least one timeout was removed, else returns False
    def statemachine_timeout_remove_all(self):
        # As a consistency check, we overwrite self._timeouts to an empty set always
        # This must be done after the check to see if it is empty (if self._timeouts) so do not refactor this code!
        if self._timeouts:
            self._timeouts = set()
            return True
        else:
            self._timeouts = set()
            return False        
    
    @define_state(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True)
    def shutdown_workers(self):
        """Ask all workers to shutdown"""
        for worker_name in self.workers:
            yield(self.queue_work(worker_name, 'shutdown'))
        self.shutdown_workers_complete = True

    def close_tab(self, finalise=True):
        """Close the tab, terminate subprocesses and join the job thread. If
        finalise=False, then do not terminate subprocesses or join the job thread. In this
        case, callers must manually call finalise_close_tab() to perform these
        potentially blocking operations"""
        self.logger.info('close_tab called')
        self._timeout.stop()
        self._statemachine.close()
        self.notebook = self._ui.parentWidget().parentWidget()
        currentpage = None
        if self.notebook:
            #currentpage = self.notebook.get_current_page()
            currentpage = self.notebook.indexOf(self._ui)
            self.notebook.removeTab(currentpage)
            temp_widget = QLabel("Waiting for worker(s) to exit")
            temp_widget.setAlignment(Qt.AlignCenter)
            self.notebook.insertTab(currentpage, temp_widget, '[%s]' % self.device_name)
            self.notebook.tabBar().setTabIcon(currentpage, QIcon(self.ICON_BUSY))
            self.notebook.tabBar().setTabTextColor(currentpage, QColor('grey'))
            self.notebook.setCurrentWidget(temp_widget)  
        if finalise:
            self.finalise_close_tab(currentpage)
        return currentpage
    
    def finalise_close_tab(self, currentpage):
        JOB_THREAD_TIMEOUT = 2
        if not self._statemachine.join(JOB_THREAD_TIMEOUT):
            self.logger.warning("job thread of %s did not stop", self.device_name)
        try:
            self._end_workers()
        finally:
             # Shutdown the output box by joining its thread:
            self._output_box.shutdown()

    def _end_workers(self):
        """Tell the workers to quit, and kill each one that has not exited after
        WORKER_QUIT_TIMEOUT seconds. A worker interrupts the job that it is running, and
        if the job has not stopped after WORKER_ABORT_TIMEOUT seconds, exits when it has
        no HDF5 file open for writing, or after WORKER_KILL_LOCK_TIMEOUT seconds. A
        worker that has not finished starting up is killed at once. A second call waits
        for the first to return."""
        with self._end_workers_lock:
            self._end_workers_locked()

    def _end_workers_locked(self):
        if self.remote_process_client is not None:
            # Timeout for requests to the remote process server:
            kwargs = {'get_timeout': 5}
        else:
            kwargs = {}
        # Delete the workers from the dict, so that their __del__ methods are called
        # when this method returns. This is important so that the remote process server,
        # if any, knows we have deleted the objects:
        workers = [self.workers.pop(name) for name in list(self.workers)]
        children = []
        for worker, to_worker, _ in workers:
            worker.interrupt_startup()
            if worker.child is None:
                continue
            if to_worker is not None:
                try:
                    # The queue's own interruptor is set when the state machine closes:
                    to_worker.put('quit', timeout=1, interruptor=Interruptor())
                except TimeoutError:
                    pass
                else:
                    children.append(worker.child)
                    continue
            try:
                worker.child.kill(**kwargs)
            except (OSError, TimeoutError):
                # The process has exited, or the remote process server is unreachable
                pass
        deadline = time.monotonic() + WORKER_QUIT_TIMEOUT
        for child in children:
            try:
                while child.poll(**kwargs) is None:
                    if time.monotonic() > deadline:
                        self.logger.warning(
                            "A worker of %s did not exit, killing it", self.device_name
                        )
                        child.kill(**kwargs)
                        break
                    time.sleep(0.05)
            except (OSError, TimeoutError):
                pass

    def connect_restart_receiver(self,function):
        if function not in self._restart_receiver:
            self._restart_receiver.append(function)
            
    def disconnect_restart_receiver(self,function):
        if function in self._restart_receiver:
            self._restart_receiver.remove(function)
    
    def _notify_restart_receivers(self):
        for f in self._restart_receiver:
            try:
                f(self.device_name)
            except Exception:
                self.logger.exception('Could not notify a connected receiver function')

    def _shut_down_workers_then(self, callback):
        """Run the workers' shutdown() methods before any other state, and then call
        callback in the main thread, or call it after SHUTDOWN_TIMEOUT seconds if the
        shutdown() methods have not returned. If the state machine is not running,
        call callback at once. Called in the main thread."""
        if self._statemachine.closed or self._statemachine.failed:
            callback()
            return
        callbacks = [callback]

        def call_once():
            if callbacks:
                callbacks.pop()()

        self.event_queue.put(
            MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,
            True,
            False,
            [Tab._shut_down_workers, [(call_once,), {}]],
            priority=-1,
        )
        QTimer.singleShot(int(self.SHUTDOWN_TIMEOUT * 1000), call_once)

    def _shut_down_workers(self, callback):
        for worker_name in self.workers:
            yield (self.queue_work(worker_name, 'shutdown'))
        callback()

    def _on_stop_clicked(self):
        if self.state in ('stopped', 'fatal error'):
            self.restart()
        else:
            self.stop()

    def stop(self):
        """Run the workers' shutdown() methods and end the worker processes. The tab
        stays open with its state machine stopped until it is restarted."""
        self._notify_restart_receivers()
        self._ui.button_stop.setEnabled(False)
        self._ui.button_restart.setEnabled(False)
        self._shut_down_workers_then(self._stop_after_shutdown)

    def _stop_after_shutdown(self):
        self.logger.info('***STOP***')
        self._statemachine.close()
        now = time.strftime('%a %b %d, %H:%M:%S', time.localtime())
        self.error_message += (
            'Worker processes stopped - %s<br />' % now
            + 'Click the start button to start them and initialise the device.<br />'
        )
        self._ui.button_close.setEnabled(False)
        self.state = 'stopping'
        inthread(self._end_workers_for_stop)

    def _end_workers_for_stop(self):
        self._end_workers()
        inmain_later(self._stopped)

    def _stopped(self):
        self.state = 'stopped'
        self._ui.button_stop.setEnabled(True)
        self._ui.button_restart.setEnabled(True)

    def restart(self,*args):
        self._notify_restart_receivers()
        self._ui.button_stop.setEnabled(False)
        self._ui.button_restart.setEnabled(False)
        self._shut_down_workers_then(self._restart_after_shutdown)

    def _restart_after_shutdown(self):
        currentpage = self.close_tab(finalise=False)
        self.logger.info('***RESTART***')
        self.settings['saved_data'] = self.get_all_save_data()
        self._restart_thread = inthread(self.continue_restart, currentpage)
        
    def continue_restart(self, currentpage):
        """Called in a thread for the stages of restarting that may be blocking, so as to
        not block the main thread. Calls subsequent GUI operations in the main thread once
        finished blocking."""
        self.finalise_close_tab(currentpage)
        inmain(self.clean_ui_on_restart)
        inmain(self.finalise_restart, currentpage)
        
    def clean_ui_on_restart(self):
        # Clean up UI
        ui = self._ui
        self._ui = None
        ui.setParent(None)
        ui.deleteLater()
        del ui
        
    def finalise_restart(self, currentpage):
        widget = self.notebook.widget(currentpage)
        widget.setParent(None)
        widget.deleteLater()
        del widget
    
        # Note: the following function call will break if the user hasn't
        # overridden the __init__ function to take these arguments. So
        # make sure you do that!
        self.__init__(self.notebook, self.settings,restart=True)
        
        # The init method is going to place this device tab at the end of the notebook specified
        # Let's remove it from there, and place it the poition it used to be!
        self.notebook = self._ui.parentWidget().parentWidget()
        self.notebook.removeTab(self.notebook.indexOf(self._ui))
        self.notebook.insertTab(currentpage,self._ui,self.device_name)
        self.notebook.setCurrentWidget(self._ui)
        self._applied_tab_icon_and_colour = None
        self.set_tab_icon_and_colour()
            
        # If BLACS is waiting on this tab for something, tell it to abort!
        # self.BLACS.current_queue.put('abort')
    
    def queue_work(self,worker_process,worker_function,*args,**kwargs):
        return worker_process,worker_function,args,kwargs
        
    def set_terminal_visible(self, visible):
        if visible:
            self._output_box.output_textedit.show()
        else:
            self._output_box.output_textedit.hide()
        self._ui.button_show_terminal.setChecked(visible)

    def hide_error(self):
        # dont show the error again until the not responding time has doubled:
        self.hide_not_responding_error_until = 2*self.not_responding_for
        self._ui.notresponding.hide()  
        self.error_message = ''
        self._tab_text_colour = self._ui.palette().color(QPalette.ColorRole.Text)
        self.set_tab_icon_and_colour()
            
    def check_time(self):
        if self.state in ['idle','fatal error','stopped']:
            self.not_responding_for = 0
            if self._not_responding_error_message:
                self._not_responding_error_message = ''
                self._update_error_and_tab_icon()
        else:
            self.not_responding_for = time.time() - self._time_of_last_state_change
        if self.not_responding_for > 5 + self.hide_not_responding_error_until:
            self.hide_not_responding_error_for = 0
            self._ui.notresponding.show()
            hours, remainder = divmod(int(self.not_responding_for), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                s = '%s hours'%hours
            elif minutes:
                s = '%s minutes'%minutes
            else:
                s = '%s seconds'%seconds
            self._not_responding_error_message = 'The hardware process has not responded for %s.<br /><br />'%s
            self._update_error_and_tab_icon()
        return True


class Worker(Process):
    def init(self):
        # To be overridden by subclasses
        pass

    def shutdown(self):
        # To be overridden by subclasses
        pass
    
    def run(self, worker_name, device_name, extraargs):
        self.worker_name = worker_name
        self.device_name = device_name
        from labscript_utils.setup_logging import setup_logging
        setup_logging('BLACS')
        log_name = 'BLACS.%s_%s.worker'%(self.device_name,self.worker_name)
        self.logger = logging.getLogger(log_name)
        self.logger.debug('Starting')
        import labscript_utils.excepthook
        labscript_utils.excepthook.install()
        labscript_utils.excepthook.set_logger(self.logger)
        from labscript_utils.ls_zprocess import ProcessTree
        process_tree = ProcessTree.instance()
        import labscript_utils.h5_lock
        process_tree.zlock_client.set_process_name(log_name)
        for name, value in extraargs.items():
            if hasattr(self, name):
                msg = """attribute `{}` overwrites an attribute of the Worker base class
                    with the same name. This may cause unexpected behaviour. Consider
                    renaming it."""
                warnings.warn(dedent(msg).format(name), RuntimeWarning)
            else:
                setattr(self, name, value)
        self.mainloop()

    def _transition_to_buffered(self, device_name, h5_file, front_panel_values, fresh):
        # The h5_file arg was converted to network-agnostic before being sent to us.
        # Convert it to a local path before calling the subclass's
        # transition_to_buffered() method
        h5_file = path_to_local(h5_file)
        return self.transition_to_buffered(
            device_name, h5_file, front_panel_values, fresh
        )

    def mainloop(self):
        """Run jobs in the main thread. A thread receives the job requests from the
        parent, so that a request to quit is received while a job is running."""
        self._job_requests = queue.Queue()
        # Set while no job is running:
        self._idle = threading.Event()
        self._idle.set()
        # Set while the main thread is running a job. _on_sigint() raises
        # KeyboardInterrupt only while this is set, so that the interrupt is raised in
        # the job and not in the code that runs after it:
        self._job_running = False
        signal.signal(signal.SIGINT, self._on_sigint)
        threading.Thread(target=self._receive, daemon=True).start()
        while True:
            # Get the next task to be done:
            self.logger.debug('Waiting for next job request')
            funcname, args, kwargs = self._job_requests.get()
            self._idle.clear()
            self.logger.debug('Got job request %s', funcname)
            try:
                # See if we have a method with that name:
                func = getattr(self,funcname)
                success = True
                message = ''
            except AttributeError:
                success = False
                message = traceback.format_exc()
                self.logger.error("Couldn't start job:\n %s", message)
            # Report to the parent whether method lookup was successful or not:
            self.to_parent.put((success,message,None))
            if success:
                # Try to do the requested work:
                self.logger.debug('Starting job %s', funcname)
                try:
                    try:
                        self._job_running = True
                        results = func(*args,**kwargs)
                    finally:
                        self._job_running = False
                    success = True
                    message = ''
                    self.logger.debug('Job complete')
                except (Exception, KeyboardInterrupt):
                    results = None
                    success = False
                    traceback_lines = traceback.format_exception(*sys.exc_info())
                    del traceback_lines[1]
                    message = ''.join(traceback_lines)
                    self.logger.error('Exception in job:\n%s', message)
                # Check if results object is serialisable:
                try:
                    pickle.dumps(results)
                except Exception:
                    message = traceback.format_exc()
                    self.logger.error('Job returned unserialisable datatypes, cannot pass them back to parent.\n%s', message)
                    message = 'Attempt to pass unserialisable object %s to parent process:\n' % str(results) + message
                    success = False
                    results = None
                # Report to the parent whether work was successful or not,
                # and what the results were:
                self.to_parent.put((success,message,results))
            self._idle.set()

    def _receive(self):
        while True:
            request = self.from_parent.get()
            if request == 'quit':
                self._quit()
            self._job_requests.put(request)

    def _quit(self):
        """Interrupt the job that is running, if any, and exit. If the job has not
        stopped after WORKER_ABORT_TIMEOUT seconds, exit when no HDF5 file is open for
        writing, or after WORKER_KILL_LOCK_TIMEOUT seconds."""
        if not self._idle.is_set():
            interrupt_main_thread()
            if not self._idle.wait(WORKER_ABORT_TIMEOUT):
                print(
                    'The job did not stop after %d seconds. The worker will exit when '
                    'it has no HDF5 file open for writing, or after %d seconds.'
                    % (WORKER_ABORT_TIMEOUT, WORKER_KILL_LOCK_TIMEOUT),
                    file=sys.stderr,
                )
        sys.stdout.flush()
        sys.stderr.flush()
        self.kill_lock.exit_when_released(status=0, timeout=WORKER_KILL_LOCK_TIMEOUT)

    def _on_sigint(self, signum, frame):
        if self._job_running:
            raise KeyboardInterrupt


class PluginTab(object):
    def __init__(self, notebook, settings):
        # Store important parameters
        self.notebook = notebook
        self.settings = settings
        self._tab_name = self.settings["tab_name"]

        # Load the UI
        self._ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'plugin_tab_frame.ui'))
        self._layout = self._ui.device_layout
        self._tab_icon = ''
        self._tab_text_colour = self._ui.palette().color(QPalette.ColorRole.Text)

        self._ui.device_name.setText("<b>%s</b> [Plugin]" % (str(self.tab_name)))
        elide_label(self._ui.device_name, self._ui.horizontalLayout, Qt.ElideRight)

        # Add the tab to the notebook
        self.notebook.addTab(self._ui, self.tab_name)

        # Call the initialise GUI function
        self.initialise_GUI()
        self.restore_save_data(self.settings['saved_data'] if 'saved_data' in self.settings else {})

    @inmain_decorator(True)
    def set_tab_icon_and_colour(self):
        """Set the tab icon and the colour of its text to the values of
        self._tab_icon and self._tab_text_colour respectively"""
        if self._ui.parentWidget() is None:
            return
        self.notebook = self._ui.parentWidget().parentWidget()
        if self.notebook is not None:
            currentpage = self.notebook.indexOf(self._ui)
            if currentpage == -1:
                # shutting down:
                return
            icon = QIcon(self._tab_icon)
            self.notebook.tabBar().setTabIcon(currentpage, icon)
            self.notebook.tabBar().setTabTextColor(currentpage, QColor(self._tab_text_colour))

    @property
    def tab_name(self):
        return self._tab_name

    def get_tab_layout(self):
        return self._layout

    def close_tab(self, **kwargs):
        self.notebook = self._ui.parentWidget().parentWidget()
        currentpage = None
        if self.notebook:
            #currentpage = self.notebook.get_current_page()
            currentpage = self.notebook.indexOf(self._ui)
            self.notebook.removeTab(currentpage)
            temp_widget = QWidget()
            self.notebook.insertTab(currentpage, temp_widget, self.tab_name)
            self.notebook.setCurrentWidget(temp_widget)
        return currentpage

    def initialise_GUI(self):
        return

    # This method should be overridden in your plugin class if you want to save any data
    # This method should return a dictionary, and this dictionary will be passed to the restore_save_data()
    # method when the tab is initialised
    def get_save_data(self):
        return {}
        
    def get_all_save_data(self):
        save_data = self.get_builtin_save_data()
        if hasattr(self, 'get_save_data'):
            tab_save_data = self.get_save_data()
            if isinstance(tab_save_data, dict):
                save_data.update(tab_save_data)
        return save_data


    # This method should be overridden in your plugin class if you want to restore data
    # (saved by get_save_data()) when the tab is initialised.
    # You will be passed a dictionary of the form specified by your get_save_data() method
    #
    # Note: You must handle the case where the data dictionary is empty (or one or more keys are missing)
    #       This case will occur the first time BLACS is started on a PC, or if the BLACS datastore is destroyed
    def restore_save_data(self,data):
        return

    def update_from_settings(self,settings):
        self.restore_save_data(settings['saved_data'])

    def get_builtin_save_data(self):
        return {}

# Example code! Two classes are defined below, which are subclasses
# of the ones defined above.  They show how to make a Tab class,
# and a Worker class, and get the Tab to request work to be done by
# the worker in response to GUI events.
class MyTab(Tab):
    def __init__(self,notebook,settings,restart=False): # restart will be true if __init__ was called due to a restart
        Tab.__init__(self,notebook,settings,restart) # Make sure to call this first in your __init__!
        self.create_worker('My worker',MyWorker,{'x':7})
        self.initUI()
        
    def initUI(self):
        self.layout = self.get_tab_layout()
        
        foobutton = QPushButton('foo, 10 seconds!')
        barbutton = QPushButton('bar, 10 seconds, then error!')
        bazbutton = QPushButton('baz, 0.5 seconds!')
        addbazbutton = QPushButton('add 2 second timeout to baz')
        removebazbutton = QPushButton('remove baz timeout')
        bazunpickleable= QPushButton('try to pass baz a threading.Lock()')
        fatalbutton = QPushButton('fatal error, forgot to add @define_state to callback!')
        
        self.checkbutton = QPushButton('have baz\nreturn a Queue')
        self.checkbutton.setCheckable(True)
        
        #self.device_widget.addWidget(layout)
        self.layout.addWidget(foobutton)
        self.layout.addWidget(barbutton)
        self.layout.addWidget(bazbutton)
        self.layout.addWidget(addbazbutton)
        self.layout.addWidget(removebazbutton)
        self.layout.addWidget(bazunpickleable)
        self.layout.addWidget(fatalbutton)
        self.layout.addWidget(self.checkbutton)
        
        foobutton.clicked.connect(self.foo)
        barbutton.clicked.connect(self.bar)
        bazbutton.clicked.connect(self.baz)
        fatalbutton.clicked.connect(self.fatal )
        addbazbutton.clicked.connect(self.add_baz_timeout)
        removebazbutton.clicked.connect(self.remove_baz_timeout)
        bazunpickleable.clicked.connect(self.baz_unpickleable)

    # It is critical that you decorate your callbacks with @define_state
    # as below. This makes the function get queued up and executed
    # in turn by our state machine instead of immediately by the
    # GTK mainloop. Only don't decorate if you're certain that your
    # callback can safely happen no matter what state the system is
    # in (for example, adjusting the axis range of a plot, or other
    # appearance settings). You should never be calling queue_work
    # or do_after from un undecorated callback.
    @define_state(MODE_MANUAL,True)  
    def foo(self,button=None):
        self.logger.debug('entered foo')
        #self.toplevel.set_sensitive(False)
        # Here's how you instruct the worker process to do
        # something. When this callback returns, the worker will be
        # requested to do whatever you ask in queue_work (in this
        # case, MyWorker.foo(5,6,7,x='x') ). Then, no events will
        # be processed until that work is done. Once the work is
        # done, whatever has been set with do_after will be executed
        # (in this case self.leave_foo(1,2,3,bar=baz) ).
        results = yield(self.queue_work('My worker','foo', 5,6,7,x='x'))

        #self.toplevel.set_sensitive(True)
        self.logger.debug('leaving foo')
    
    # Here's what's NOT to do: forgetting to decorate a callback with @define_state
    # when it's not something that can safely be done asynchronously
    # to the state machine:
    def fatal(self):
        # This bug could be hard to track because nothing will happen
        # when you click the button -- only once you do some other,
        # correcly decorated callback will it become apparant that
        # something is wrong. So don't make this mistake!
        self.queue_work('My worker','foo', 5,6,7,x='x')
        
    @define_state(MODE_MANUAL,True)  
    def bar(self, button=None):
        self.logger.debug('entered bar')
        results = yield(self.queue_work('My worker','bar', 5,6,7,x=5))
      
        self.logger.debug('leaving bar')
        
    @define_state(MODE_MANUAL,True)  
    def baz(self, button=None):
        print(threading.current_thread().name)
        self.logger.debug('entered baz')
        results = yield(self.queue_work('My worker','baz', 5,6,7,x='x',return_queue=self.checkbutton.isChecked()))
        print(results)
        print(threading.current_thread().name)
        results = yield(self.queue_work('My worker','baz', 4,6,7,x='x',return_queue=self.checkbutton.isChecked()))
        print(results)
        print(threading.current_thread().name)
        self.logger.debug('leaving baz')
        
    # This event shows what happens if you try to send a unpickleable
    # event through a queue to the subprocess:
    @define_state(MODE_MANUAL,True)  
    def baz_unpickleable(self, button=None):
        self.logger.debug('entered baz_unpickleable')
        results = yield(self.queue_work('My worker','baz', 5,6,7,x=threading.Lock()))
        self.logger.debug('leaving baz_unpickleable')
    
    # You don't need to decorate with @define_state if all you're
    # doing is adding a timeout -- adding a timeout can safely be done
    # asynchronously. But you can still decorate if you want, and you
    # should if you're doing other work in the same function call which
    # can't be done asynchronously.
    def add_baz_timeout(self):
        self.statemachine_timeout_add(2000,self.baz)
    
    # Similarly, no @define_state is required here -- same applies as above.    
    def remove_baz_timeout(self):
        self.statemachine_timeout_remove(self.baz)
    
        
class MyWorker(Worker):
    def init(self):
        # You read correctly, this isn't __init__, it's init. It's the
        # first thing that will be called in the new process. You should
        # do imports here, define instance variables, that sort of thing. You
        # shouldn't import the hardware modules at the top of your file,
        # because then they will be imported in both the parent and
        # the child processes and wont be cleanly restarted when the subprocess
        # is restarted. Since we're inside a method call though, you'll
        # have to use global statements for the module imports, as shown
        # below. Either that or you can make them instance variables, ie:
        # import module; self.module = module. Up to you, I prefer
        # the former.
        global serial; import serial
        self.logger.info('got x! %d', self.x)
        # randomly fail this on init, but only occasionally
        import random
        if random.random() < 0.15:
            raise Exception('bad import!')
        
    # Here's a function that will be called when requested by the parent
    # process. There's nothing special about it really. Its return
    # value will be passed as a keyword argument _results to the
    # function which was queued with do_after, if there was one.
    def foo(self,*args,**kwargs):
        self.logger.debug('working on foo!')
        time.sleep(10)
        return 'results!!!'
        
    def bar(self,*args,**kwargs):
        self.logger.debug('working on bar!')
        time.sleep(10)
        raise Exception('error!')
        return 'results!!!'
        
    def baz(self,zzz,*args,**kwargs):
        self.logger.debug('working on baz: time is %r', time.time())
        time.sleep(0.5)
        if kwargs['return_queue']:
            return queue.Queue()
        return 'results%d!!!'%zzz

if __name__ == '__main__':
    import sys
    import logging.handlers
    # Setup logging:
    from labscript_utils.setup_logging import setup_logging
    setup_logging('BLACS')
    logger = logging.getLogger('BLACS')
    handler = logging.handlers.RotatingFileHandler(os.path.join(BLACS_DIR, 'BLACS.log'), maxBytes=1024**2, backupCount=0)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if sys.stdout is not None and sys.stdout.isatty():
        terminalhandler = logging.StreamHandler(sys.stdout)
        terminalhandler.setFormatter(formatter)
        terminalhandler.setLevel(logging.INFO)
        logger.addHandler(terminalhandler)
    else:
        sys.stdout = sys.stderr = open(os.devnull)
    logger.setLevel(logging.DEBUG)
    logger.info('\n\n===============starting===============\n')

if __name__ == '__main__':
    from labscript_utils.qtwidgets.dragdroptab import DragDropTabWidget
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout(window)
    notebook = DragDropTabWidget()
    layout.addWidget(notebook)
    
    class FakeConnection(object):
        def __init__(self):
            self.BLACS_connection = 'None'
            self.properties = {}
    class FakeConnectionTable(object):
        def __init__(self):
            pass
        
        def find_by_name(self, device_name):
            return FakeConnection()
    
    connection_table = FakeConnectionTable()
    
    tab1 = MyTab(notebook,settings = {'device_name': 'Example', 'connection_table':connection_table})
    tab2 = MyTab(notebook,settings = {'device_name': 'Example2', 'connection_table':connection_table})
    
    window.show()
    def run():
        app.exec()
        tab1.close_tab()
        tab2.close_tab()
    sys.exit(run())
