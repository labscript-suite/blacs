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
from zprocess import Process, Interruptor, Interrupted
from zprocess.utils import TimeoutError
import time
import sys
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

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from qtutils import *
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
            
class StateQueue(object):
    # NOTE:
    #
    # It is theoretically possible to remove the dependency on the Qt Mainloop (remove inmain decorators and fnuction calls)
    # by introducing a local lock object instead. However, be aware that right now, the Qt inmain lock is preventing the 
    # statemachine loop (Tab.mainloop) from getting any states uot of the queue until after the entire tab is initialised 
    # and the Qt mainloop starts.
    #
    # This is particularly important because we exploit this behaviour to make sure that Tab._initialise_worker is placed at the
    # start of the StateQueue, and so the Tab.mainloop method is guaranteed to get this initialisation method as the first state 
    # regardless of whether the mainloop is started before the state is inserted (the state should always be inserted as part of  
    # the call to Tab.create_worker, in DeviceTab.initialise_workers in DeviceTab.__init__ )
    #
    
    def __init__(self,device_name):
        self.logger = logging.getLogger('BLACS.%s.state_queue'%(device_name))
        self.logging_enabled = False
        if self.logging_enabled:
            self.logger.debug("started")
        
        self.list_of_states = []
        self._last_requested_state = None
        # A queue that blocks the get(requested_state) method until an entry in the queue has a state that matches the requested_state
        self.get_blocking_queue = queue.Queue()

    @property
    @inmain_decorator(True)    
    # This is always done in main so that we avoid a race condition between the get method and
    # the put method accessing this property
    def last_requested_state(self):
        return self._last_requested_state
    
    @last_requested_state.setter
    @inmain_decorator(True)
    def last_requested_state(self, value):
        self._last_requested_state = value
     
    def log_current_states(self):
        if self.logging_enabled:
            self.logger.debug('Current items in the state queue: %s'%str(self.list_of_states))
     
    # this should only happen in the main thread, as my implementation is not thread safe!
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
        # if this state is one the get command is waiting for, notify it!
        if self.last_requested_state is not None and allowed_states&self.last_requested_state:
            self.get_blocking_queue.put('new item')
        
        if self.logging_enabled:
            if not isinstance(data[0],str):
                self.logger.debug('New state queued up. Allowed modes: %d, queue state indefinitely: %s, delete stale states: %s, function: %s'%(allowed_states,str(queue_state_indefinitely),str(delete_stale_states),data[0].__name__))
        self.log_current_states()
    
    # this should only happen in the main thread, as my implementation is not thread safe!
    @inmain_decorator(True)
    def check_for_next_item(self,state):
        # We reset the queue here, as we are about to traverse the tree, which contains any new items that
        # are described in messages in this queue, so let's not keep those messages around anymore.
        # Put another way, we want to block until a new item is added, if we don't find an item in this function
        # So it's best if the queue is empty now!
        if self.logging_enabled:
            self.logger.debug('Re-initialsing self._get_blocking_queue')
        self.get_blocking_queue = queue.Queue()

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
        return success,data    
        
    # this method should not be called in the main thread, because it will block until something is found...
    # Please, only have one thread ever accessing this...I have no idea how it will behave if multiple threads are trying to get
    # items from the queue...
    #
    # This method will block until a item found in the queue is found to be allowed during the specified 'state'.
    def get(self,state):
        if self.last_requested_state:
            raise Exception('You have multiple threads trying to get from this queue at the same time. I won\'t allow it!')
    
        self.last_requested_state = state
        while True:
            if self.logging_enabled:
                self.logger.debug('requesting next item in queue with mode %d'%state)
                inmain(self.log_current_states)
            status,data = self.check_for_next_item(state)
            if not status:
                # we didn't find anything useful, so we'll wait until a useful state is added!
                self.get_blocking_queue.get()
            else:
                self.last_requested_state = None
                return data


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
        self._tab_text_colour = 'black'

        # Create instance variables
        self._not_responding_error_message = ''
        self._error = ''
        self._state = ''
        self._time_of_last_state_change = time.time()
        self.not_responding_for = 0
        self.hide_not_responding_error_until = 0
        self._timeouts = set()
        self._timeout_ids = {}
        self._force_full_buffered_reprogram = True
        self.event_queue = StateQueue(self.device_name)
        self.workers = {}
        self._supports_smart_programming = False
        self._restart_receiver = []
        self.shutdown_workers_complete = False

        self.remote_process_client = self._get_remote_configuration()
        self.BLACS_connection = self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection

        # Load the UI
        self._ui = UiLoader().load(os.path.join(BLACS_DIR, 'tab_frame.ui'))
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
        self._update_error_and_tab_icon()
        self.supports_smart_programming(False)
        
        # Restore settings:
        self.restore_builtin_save_data(self.settings.get('saved_data', {}))

        # This should be done beofre the main_loop starts or else there is a race condition as to whether the 
        # self._mode variable is even defined!
        # However it must be done after the UI is created!
        self.mode = MODE_MANUAL
        self.state = 'idle'
        
        # Setup the not responding timeout
        self._timeout = QTimer()
        self._timeout.timeout.connect(self.check_time)
        self._timeout.start(1000)
                
        # Launch the mainloop
        self._mainloop_thread = threading.Thread(target = self.mainloop)
        self._mainloop_thread.daemon = True
        self._mainloop_thread.start()
                
        # Add the tab to the notebook
        self.notebook.addTab(self._ui,self.device_name)
        self._ui.show()
    
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

    def get_all_save_data(self):
        save_data = self.get_builtin_save_data()
        if hasattr(self, 'get_save_data'):
            tab_save_data = self.get_save_data()
            if isinstance(tab_save_data, dict):
                save_data.update(tab_save_data)
            else:
                self.logger.warning('Incorrect format for tab save data from the get_save_data() method. Data should be a dict. Data was: %s'%tab_save_data)
        return save_data

    def restore_builtin_save_data(self, data):
        """Restore builtin settings to be restored like whether the terminal is
        visible. Not to be overridden."""
        self.set_terminal_visible(data.get('_terminal_visible', False))
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
        self._ui.error_message.setHtml(prefix+self._not_responding_error_message+self._error+suffix)
        if self._error or self._not_responding_error_message:
            self._ui.notresponding.show()
            self._tab_text_colour = 'red'
            if self.error_message:
                if self.state == 'fatal error':
                    self._tab_icon = self.ICON_FATAL_ERROR
                else: 
                    self._tab_icon = self.ICON_ERROR
        else:
            self._ui.notresponding.hide()
            self._tab_text_colour = 'black'
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
            icon = QIcon(self._tab_icon)
            self.notebook.tabBar().setTabIcon(currentpage, icon)
            self.notebook.tabBar().setTabTextColor(currentpage, QColor(self._tab_text_colour))
    
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
        self._update_state_label()
        self._update_error_and_tab_icon()
    
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
        be started once the state machine mainloop begins running. This way errors in
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
        """Close the tab, terminate subprocesses and join the mainloop thread. If
        finalise=False, then do not terminate subprocesses or join the mainloop. In this
        case, callers must manually call finalise_close_tab() to perform these
        potentially blocking operations"""
        self.logger.info('close_tab called')
        self._timeout.stop()
        for worker, to_worker, from_worker in self.workers.values():
            # If the worker is still starting up, interrupt any blocking operations:
            worker.interrupt_startup()
            # Interrupt the read and write queues in case the mainloop is blocking on
            # sending or receiving from them:
            if to_worker is not None:
                to_worker.interrupt()
                from_worker.interrupt()
        # In case the mainloop is blocking on the event queue, post a message to that
        # queue telling it to quit:
        if self._mainloop_thread.is_alive():
            self.event_queue.put(MODE_MANUAL|MODE_BUFFERED|MODE_TRANSITION_TO_BUFFERED|MODE_TRANSITION_TO_MANUAL,True,False,['_quit',None],priority=-1)
        self.notebook = self._ui.parentWidget().parentWidget()
        currentpage = None
        if self.notebook:
            #currentpage = self.notebook.get_current_page()
            currentpage = self.notebook.indexOf(self._ui)
            self.notebook.removeTab(currentpage)
            temp_widget = QLabel("Waiting for tab mainloop and worker(s) to exit")
            temp_widget.setAlignment(Qt.AlignCenter)
            self.notebook.insertTab(currentpage, temp_widget, '[%s]' % self.device_name)
            self.notebook.tabBar().setTabIcon(currentpage, QIcon(self.ICON_BUSY))
            self.notebook.tabBar().setTabTextColor(currentpage, QColor('grey'))
            self.notebook.setCurrentWidget(temp_widget)  
        if finalise:
            self.finalise_close_tab(currentpage)
        return currentpage
    
    def finalise_close_tab(self, currentpage):
        TERMINATE_TIMEOUT = 2
        self._mainloop_thread.join(TERMINATE_TIMEOUT)
        if self._mainloop_thread.is_alive():
            self.logger.warning("mainloop thread of %s did not stop", self.device_name)
        kwargs = {'wait_timeout': TERMINATE_TIMEOUT}  # timeout passed to .wait()
        if self.remote_process_client is not None:
            # Set up a zprocess.Interruptor to interrupt communication with the remote
            # process server if the timeout is reached:
            interruptor = Interruptor()
            kwargs['get_interruptor'] = interruptor
            timer = inmain(QTimer)
            inmain(timer.singleShot, int(TERMINATE_TIMEOUT * 1000), interruptor.set)
        try:
            # Delete the workers from the dict as we go, ensuring their __del__ method
            # will be called. This is important so that the remote process server, if
            # any, knows we have deleted the object:
            for name in self.workers.copy():
                worker, _, _ = self.workers.pop(name)
                worker.terminate(**kwargs)
        except Interrupted:
            self.logger.warning(
                "Terminating workers of %s timed out", self.device_name
            )
            return
        finally:
             # Shutdown the output box by joining its thread:
            self._output_box.shutdown()
            if self.remote_process_client is not None:
                inmain(timer.stop)
        

    def connect_restart_receiver(self,function):
        if function not in self._restart_receiver:
            self._restart_receiver.append(function)
            
    def disconnect_restart_receiver(self,function):
        if function in self._restart_receiver:
            self._restart_receiver.remove(function)
    
    def restart(self,*args):
        # notify all connected receivers:
        for f in self._restart_receiver:
            try:
                f(self.device_name)
            except Exception:
                self.logger.exception('Could not notify a connected receiver function')
                
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
        self._tab_text_colour = 'black'
        self.set_tab_icon_and_colour()
            
    def check_time(self):
        if self.state in ['idle','fatal error']:
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
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.mainloop'%(self.settings['device_name']))   
        logger.debug('Starting')
        
        # Store a reference to the state queue and workers, this way if the tab is restarted, we won't ever get access to the new state queue created then
        event_queue = self.event_queue
        workers = self.workers
        
        try:
            while True:
                # Get the next task from the event queue:
                logger.debug('Waiting for next event')
                func, data = event_queue.get(self.mode)
                if func == '_quit':
                    # The user has requested a restart:
                    logger.debug('Received quit signal')
                    break
                args,kwargs = data
                logger.debug('Processing event %s' % func.__name__)
                self.state = '%s (GUI)'%func.__name__
                # Run the task with the GUI lock, catching any exceptions:
                #func = getattr(self,funcname)
                # run the function in the Qt main thread
                generator = inmain(func,self,*args,**kwargs)
                # Do any work that was queued up:(we only talk to the worker if work has been queued up through the yield command)
                if type(generator) == GeneratorType:
                    # We need to call next recursively, queue up work and send the results back until we get a StopIteration exception
                    generator_running = True
                    # get the data from the first yield function
                    worker_process,worker_function,worker_args,worker_kwargs = inmain(generator.__next__)
                    # Continue until we get a StopIteration exception, or the user requests a restart
                    while generator_running:
                        try:
                            logger.debug('Instructing worker %s to do job %s'%(worker_process,worker_function) )
                            if worker_function == 'init':
                                # Start the worker process before running its init() method:
                                self.state = '%s (%s)'%('Starting worker process', worker_process)
                                worker, _, _ = self.workers[worker_process]
                                to_worker, from_worker = worker.start(*worker_args)
                                self.workers[worker_process] = (worker, to_worker, from_worker)
                                worker_args = ()
                                del worker # Do not gold a reference indefinitely
                            worker_arg_list = (worker_function,worker_args,worker_kwargs)
                            # This line is to catch if you try to pass unpickleable objects.
                            try:
                                pickle.dumps(worker_arg_list)
                            except Exception:
                                self.error_message += 'Attempt to pass unserialisable object to child process:'
                                raise
                            # Send the command to the worker
                            to_worker = workers[worker_process][1]
                            from_worker = workers[worker_process][2]
                            try:
                                to_worker.put(worker_arg_list, 30)
                                self.state = '%s (%s)'%(worker_function,worker_process)
                                # Confirm that the worker got the message:
                                logger.debug('Waiting for worker to acknowledge job request')
                                success, message, results = from_worker.get(30)
                            except TimeoutError:
                                logger.info('Connection timed out. Trying again.')
                                try:
                                    to_worker.put(worker_arg_list, 30)
                                    self.state = '%s (%s)'%(worker_function,worker_process)
                                    # Confirm that the worker got the message:
                                    logger.debug('Waiting for worker to acknowledge job request')
                                    success, message, results = from_worker.get(30)
                                except TimeoutError:
                                    raise TimeoutError('BLACs Device thread timed out talking to worker.')
                            if not success:
                                logger.info('Worker reported failure to start job')
                                raise Exception(message)
                            # Wait for and get the results of the work:
                            logger.debug('Worker reported job started, waiting for completion')
                            
                            success,message,results = from_worker.get()
                            if not success:
                                logger.info('Worker reported exception during job')
                                now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
                                self.error_message += ('Exception in worker - %s:<br />' % now +
                                               '<FONT COLOR=\'#ff0000\'>%s</FONT><br />'%escape(message).replace(' ','&nbsp;').replace('\n','<br />'))
                            else:
                                logger.debug('Job completed')
                            
                            # Reset the hide_not_responding_error_until, since we have now heard from the child                        
                            self.hide_not_responding_error_until = 0
                                
                            # Send the results back to the GUI function
                            logger.debug('returning worker results to function %s' % func.__name__)
                            self.state = '%s (GUI)'%func.__name__
                            next_yield = inmain(generator.send,results) 
                            # If there is another yield command, put the data in the required variables for the next loop iteration
                            if next_yield:
                                worker_process,worker_function,worker_args,worker_kwargs = next_yield
                        except StopIteration:
                            # The generator has finished. Ignore the error, but stop the loop
                            logger.debug('Finalising function')
                            generator_running = False
                self.state = 'idle'
        except Interrupted:
            # User requested a restart
            logger.debug('Interrupted by tab restart, quitting mainloop')
            return
        except Exception:
            # Some unhandled error happened. Inform the user, and give the option to restart
            message = traceback.format_exc()
            logger.critical('A fatal exception happened:\n %s'%message)
            now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
            self.error_message += ('Fatal exception in main process - %s:<br /> '%now +
                           '<FONT COLOR=\'#ff0000\'>%s</FONT><br />'%escape(message).replace(' ','&nbsp;').replace('\n','<br />'))
                            
            self.state = 'fatal error'
            # do this in the main thread
            inmain(self._ui.button_close.setEnabled,False)
        logger.info('Exiting')
        
        
class Worker(Process):
    def init(self):
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
        while True:
            # Get the next task to be done:
            self.logger.debug('Waiting for next job request')
            funcname, args, kwargs = self.from_parent.get()
            self.logger.debug('Got job request %s' % funcname)
            try:
                # See if we have a method with that name:
                func = getattr(self,funcname)
                success = True
                message = ''
            except AttributeError:
                success = False
                message = traceback.format_exc()
                self.logger.error('Couldn\'t start job:\n %s'%message)
            # Report to the parent whether method lookup was successful or not:
            try:
                self.to_parent.put((success,message,None), 30)
            except TimeoutError:
                self.logger.info('Connection timed out. Trying again.')
                try:
                    self.to_parent.put((success,message,None), 30)
                except TimeoutError:
                    raise TimeoutError('Communication timed out in worker.')
            if success:
                # Try to do the requested work:
                self.logger.debug('Starting job %s'%funcname)
                try:
                    results = func(*args,**kwargs)
                    success = True
                    message = ''
                    self.logger.debug('Job complete')
                except Exception:
                    results = None
                    success = False
                    traceback_lines = traceback.format_exception(*sys.exc_info())
                    del traceback_lines[1]
                    message = ''.join(traceback_lines)
                    self.logger.error('Exception in job:\n%s'%message)
                # Check if results object is serialisable:
                try:
                    pickle.dumps(results)
                except Exception:
                    message = traceback.format_exc()
                    self.logger.error('Job returned unserialisable datatypes, cannot pass them back to parent.\n' + message)
                    message = 'Attempt to pass unserialisable object %s to parent process:\n' % str(results) + message
                    success = False
                    results = None
                # Report to the parent whether work was successful or not,
                # and what the results were:
                try:
                    self.to_parent.put((success,message,results), 30)
                except TimeoutError:
                    self.logger.info('Connection timed out. Trying again.')
                    try:
                        self.to_parent.put((success,message,results), 30)
                    except TimeoutError:
                        raise TimeoutError('Communication timed out in worker.')


class PluginTab(object):
    def __init__(self, notebook, settings):
        # Store important parameters
        self.notebook = notebook
        self.settings = settings
        self._tab_name = self.settings["tab_name"]

        # Load the UI
        self._ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'plugin_tab_frame.ui'))
        self._layout = self._ui.device_layout

        self._ui.device_name.setText("<b>%s</b> [Plugin]" % (str(self.tab_name)))
        elide_label(self._ui.device_name, self._ui.horizontalLayout, Qt.ElideRight)

        # Add the tab to the notebook
        self.notebook.addTab(self._ui, self.tab_name)

        self._ui.show()

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
    def foo(self):
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
    def bar(self):
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
    def baz_unpickleable(self):
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
        self.logger.info('got x! %d' % self.x)
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
        self.logger.debug('working on baz: time is %s'%repr(time.time()))
        time.sleep(0.5)
        if kwargs['return_queue']:
            return queue.Queue()
        return 'results%d!!!'%zzz

if __name__ == '__main__':
    import sys
    import logging.handlers
    # Setup logging:
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
        app.exec_()
        tab1.close_tab()
        tab2.close_tab()
    sys.exit(run())
