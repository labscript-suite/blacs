#####################################################################
#                                                                   #
# /experiment_queue.py                                                         #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import logging
import os
import platform
import Queue
import threading
import time
import sys

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

import zprocess
import zprocess.locking, labscript_utils.h5_lock, h5py
zprocess.locking.set_client_process_name('BLACS.queuemanager')

from qtutils import *

from labscript_utils.qtwidgets.elide_label import elide_label
from labscript_utils.connections import ConnectionTable

from blacs.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  

FILEPATH_COLUMN = 0

class QueueTreeview(QTreeView):
    def __init__(self,*args,**kwargs):
        QTreeView.__init__(self,*args,**kwargs)
        self.header().setStretchLastSection(True)
        self.setAutoScroll(False)
        self.add_to_queue = None
        self.delete_selection = None
        self._logger = logging.getLogger('BLACS.QueueManager') 

    def keyPressEvent(self,event):
        if event.key() == Qt.Key_Delete:
            event.accept()
            if self.delete_selection:
                self.delete_selection()
        QTreeView.keyPressEvent(self,event)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            
            for url in event.mimeData().urls():
                path = str(url.toLocalFile())
                if path.endswith('.h5') or path.endswith('.hdf5'):
                    self._logger.info('Acceptable file dropped. Path is %s'%path)
                    if self.add_to_queue:
                        self.add_to_queue(str(path))
                    else:
                        self._logger.info('Dropped file not added to queue because there is no access to the neccessary add_to_queue method')
                else:
                    self._logger.info('Invalid file dropped. Path was %s'%path)
        else:
            event.ignore()

class QueueManager(object):
    
    REPEAT_ALL = 0
    REPEAT_LAST = 1

    ICON_REPEAT = ':qtutils/fugue/arrow-repeat'
    ICON_REPEAT_LAST = ':qtutils/fugue/arrow-repeat-once'

    def __init__(self, BLACS, ui):
        self._ui = ui
        self.BLACS = BLACS
        self.last_opened_shots_folder = BLACS.exp_config.get('paths', 'experiment_shot_storage')
        self._manager_running = True
        self._manager_paused = False
        self._manager_repeat = False
        self._manager_repeat_mode = self.REPEAT_ALL
        self.master_pseudoclock = self.BLACS.connection_table.master_pseudoclock
        
        self._logger = logging.getLogger('BLACS.QueueManager')   
        
        # Create listview model
        self._model = QStandardItemModel()
        self._create_headers()
        self._ui.treeview.setModel(self._model)
        self._ui.treeview.add_to_queue = self.process_request
        self._ui.treeview.delete_selection = self._delete_selected_items
        
        # set up buttons
        self._ui.queue_pause_button.toggled.connect(self._toggle_pause)
        self._ui.queue_repeat_button.toggled.connect(self._toggle_repeat)
        self._ui.queue_delete_button.clicked.connect(self._delete_selected_items)
        self._ui.queue_clear_button.clicked.connect(self._toggle_clear)
        self._ui.actionAdd_to_queue.triggered.connect(self.on_add_shots_triggered)
        self._ui.queue_add_button.setDefaultAction(self._ui.actionAdd_to_queue)
        self._ui.queue_push_up.clicked.connect(self._move_up)
        self._ui.queue_push_down.clicked.connect(self._move_down)
        self._ui.queue_push_to_top.clicked.connect(self._move_top)
        self._ui.queue_push_to_bottom.clicked.connect(self._move_bottom)

        # Set the elision of the status labels:
        elide_label(self._ui.queue_status, self._ui.queue_status_verticalLayout, Qt.ElideRight)
        elide_label(self._ui.running_shot_name, self._ui.queue_status_verticalLayout, Qt.ElideLeft)
        
        # Set up repeat mode button menu:
        self.repeat_mode_menu = QMenu(self._ui)

        self.action_repeat_all = QAction(QIcon(self.ICON_REPEAT), 'Repeat all', self._ui)
        self.action_repeat_last = QAction(QIcon(self.ICON_REPEAT_LAST), 'Repeat last', self._ui)

        self.action_repeat_all.triggered.connect(lambda *args: setattr(self, 'manager_repeat_mode', self.REPEAT_ALL))
        self.action_repeat_last.triggered.connect(lambda *args: setattr(self, 'manager_repeat_mode', self.REPEAT_LAST))

        self.repeat_mode_menu.addAction(self.action_repeat_all)
        self.repeat_mode_menu.addAction(self.action_repeat_last)

        self._ui.repeat_mode_select_button.setMenu(self.repeat_mode_menu)

        # The button already has an arrow indicating a menu, don't draw another one:
        self._ui.repeat_mode_select_button.setStyleSheet("QToolButton::menu-indicator{width: 0;}")

        self.manager = threading.Thread(target = self.manage)
        self.manager.daemon=True
        self.manager.start()

        self._callbacks = None

    def _create_headers(self):
        self._model.setHorizontalHeaderItem(FILEPATH_COLUMN, QStandardItem('Filepath'))
        
    def get_save_data(self):
        # get list of files in the queue
        file_list = []
        for i in range(self._model.rowCount()):
            file_list.append(self._model.item(i).text())
        # get button states
        return {'manager_paused':self.manager_paused,
                'manager_repeat':self.manager_repeat,
                'manager_repeat_mode':self.manager_repeat_mode,
                'files_queued':file_list,
                'last_opened_shots_folder': self.last_opened_shots_folder
               }
    
    def restore_save_data(self,data):
        if 'manager_paused' in data:
            self.manager_paused = data['manager_paused']
        if 'manager_repeat' in data:
            self.manager_repeat = data['manager_repeat']
        if 'manager_repeat_mode' in data:
            self.manager_repeat_mode = data['manager_repeat_mode']
        if 'files_queued' in data:
            file_list = list(data['files_queued'])
            self._model.clear()
            self._create_headers()
            for file in file_list:
                self.process_request(str(file))
        if 'last_opened_shots_folder' in data:
            self.last_opened_shots_folder = data['last_opened_shots_folder']
        
    @property
    @inmain_decorator(True)
    def manager_running(self):
        return self._manager_running
        
    @manager_running.setter
    @inmain_decorator(True)
    def manager_running(self,value):
        value = bool(value)
        self._manager_running = value
        
    def _toggle_pause(self,checked):    
        self.manager_paused = checked

    def _toggle_clear(self):
        self._model.clear()
        self._create_headers()

    @property
    @inmain_decorator(True)
    def manager_paused(self):
        return self._manager_paused
    
    @manager_paused.setter
    @inmain_decorator(True)
    def manager_paused(self,value):
        value = bool(value)
        self._manager_paused = value
        if value != self._ui.queue_pause_button.isChecked():
            self._ui.queue_pause_button.setChecked(value)
    
    def _toggle_repeat(self,checked):    
        self.manager_repeat = checked
        
    @property
    @inmain_decorator(True)
    def manager_repeat(self):
        return self._manager_repeat

    @manager_repeat.setter
    @inmain_decorator(True)
    def manager_repeat(self,value):
        value = bool(value)
        self._manager_repeat = value
        if value != self._ui.queue_repeat_button.isChecked():
            self._ui.queue_repeat_button.setChecked(value)

    @property
    @inmain_decorator(True)
    def manager_repeat_mode(self):
        return self._manager_repeat_mode

    @manager_repeat_mode.setter
    @inmain_decorator(True)
    def manager_repeat_mode(self, value):
        assert value in [self.REPEAT_LAST, self.REPEAT_ALL]
        self._manager_repeat_mode = value
        button = self._ui.queue_repeat_button
        if value == self.REPEAT_ALL:
            button.setIcon(QIcon(self.ICON_REPEAT))
        elif value == self.REPEAT_LAST:
            button.setIcon(QIcon(self.ICON_REPEAT_LAST))

    @inmain_decorator(True)
    def get_callbacks(self, name, update_cache=False):
        if update_cache or self._callbacks is None:
            self._callbacks = {}
            try:
                for plugin in self.BLACS.plugins.values():
                    callbacks = plugin.get_callbacks()
                    if isinstance(callbacks, dict):
                        for callback_name, callback in callbacks.items():
                            if callback_name not in self._callbacks:
                                self._callbacks[callback_name] = []
                            self._callbacks[callback_name].append(callback)
            except Exception as e:
                self._logger.exception('A Error occurred during get_callbacks.')

        if name in self._callbacks:
            return self._callbacks[name]
        else:
            return []

    def on_add_shots_triggered(self):
        shot_files = QFileDialog.getOpenFileNames(self._ui, 'Select shot files',
                                                  self.last_opened_shots_folder,
                                                  "HDF5 files (*.h5)")
        if isinstance(shot_files, tuple):
            shot_files, _ = shot_files

        if not shot_files:
            # User cancelled selection
            return
        # Convert to standard platform specific path, otherwise Qt likes forward slashes:
        shot_files = [os.path.abspath(str(shot_file)) for shot_file in shot_files]

        # Save the containing folder for use next time we open the dialog box:
        self.last_opened_shots_folder = os.path.dirname(shot_files[0])
        # Queue the files to be opened:
        for filepath in shot_files:
            if filepath.endswith('.h5'):
                self.process_request(str(filepath))

    def _delete_selected_items(self):
        index_list = self._ui.treeview.selectedIndexes()
        while index_list:
            self._model.takeRow(index_list[0].row())
            index_list = self._ui.treeview.selectedIndexes()
    
    def _move_up(self):        
        # Get the selection model from the treeview
        selection_model = self._ui.treeview.selectionModel()    
        # Create a list of select row indices
        selected_row_list = [index.row() for index in sorted(selection_model.selectedRows())]
        # For each row selected
        for i,row in enumerate(selected_row_list):
            # only move the row if it is not element 0, and the row above it is not selected
            # (note that while a row above may have been initially selected, it should by now, be one row higher
            # since we start moving elements of the list upwards starting from the lowest index)
            if row > 0 and (row-1) not in selected_row_list:
                # Remove the selected row
                items = self._model.takeRow(row)
                # Add the selected row into a position one above
                self._model.insertRow(row-1,items)
                # Since it is now a newly inserted row, select it again
                selection_model.select(self._model.indexFromItem(items[0]),QItemSelectionModel.SelectCurrent)
                # reupdate the list of selected indices to reflect this change
                selected_row_list[i] -= 1
       
    def _move_down(self):
        # Get the selection model from the treeview
        selection_model = self._ui.treeview.selectionModel()    
        # Create a list of select row indices
        selected_row_list = [index.row() for index in reversed(sorted(selection_model.selectedRows()))]
        # For each row selected
        for i,row in enumerate(selected_row_list):
            # only move the row if it is not the last element, and the row above it is not selected
            # (note that while a row below may have been initially selected, it should by now, be one row lower
            # since we start moving elements of the list upwards starting from the highest index)
            if row < self._model.rowCount()-1 and (row+1) not in selected_row_list:
                # Remove the selected row
                items = self._model.takeRow(row)
                # Add the selected row into a position one above
                self._model.insertRow(row+1,items)
                # Since it is now a newly inserted row, select it again
                selection_model.select(self._model.indexFromItem(items[0]),QItemSelectionModel.SelectCurrent)
                # reupdate the list of selected indices to reflect this change
                selected_row_list[i] += 1
        
    def _move_top(self):
        # Get the selection model from the treeview
        selection_model = self._ui.treeview.selectionModel()    
        # Create a list of select row indices
        selected_row_list = [index.row() for index in sorted(selection_model.selectedRows())]
        # For each row selected
        for i,row in enumerate(selected_row_list):
            # only move the row while it is not element 0, and the row above it is not selected
            # (note that while a row above may have been initially selected, it should by now, be one row higher
            # since we start moving elements of the list upwards starting from the lowest index)
            while row > 0 and (row-1) not in selected_row_list:
                # Remove the selected row
                items = self._model.takeRow(row)
                # Add the selected row into a position one above
                self._model.insertRow(row-1,items)
                # Since it is now a newly inserted row, select it again
                selection_model.select(self._model.indexFromItem(items[0]),QItemSelectionModel.SelectCurrent)
                # reupdate the list of selected indices to reflect this change
                selected_row_list[i] -= 1
                row -= 1
              
    def _move_bottom(self):
        selection_model = self._ui.treeview.selectionModel()    
        # Create a list of select row indices
        selected_row_list = [index.row() for index in reversed(sorted(selection_model.selectedRows()))]
        # For each row selected
        for i,row in enumerate(selected_row_list):
            # only move the row while it is not the last element, and the row above it is not selected
            # (note that while a row below may have been initially selected, it should by now, be one row lower
            # since we start moving elements of the list upwards starting from the highest index)
            while row < self._model.rowCount()-1 and (row+1) not in selected_row_list:
                # Remove the selected row
                items = self._model.takeRow(row)
                # Add the selected row into a position one above
                self._model.insertRow(row+1,items)
                # Since it is now a newly inserted row, select it again
                selection_model.select(self._model.indexFromItem(items[0]),QItemSelectionModel.SelectCurrent)
                # reupdate the list of selected indices to reflect this change
                selected_row_list[i] += 1
                row += 1
    
    @inmain_decorator(True)
    def append(self, h5files):
        for file in h5files:
            item = QStandardItem(file)
            item.setToolTip(file)
            self._model.appendRow(item)
    
    @inmain_decorator(True)
    def prepend(self,h5file):
        if not self.is_in_queue(h5file):
            self._model.insertRow(0,QStandardItem(h5file))
    
    def process_request(self,h5_filepath):
        # check connection table
        try:
            new_conn = ConnectionTable(h5_filepath, logging_prefix='BLACS')
        except Exception:
            return "H5 file not accessible to Control PC\n"
        result,error = inmain(self.BLACS.connection_table.compare_to,new_conn)
        if result:
            # Has this run file been run already?
            with h5py.File(h5_filepath) as h5_file:
                if 'data' in h5_file['/']:
                    rerun = True
                else:
                    rerun = False
            if rerun or self.is_in_queue(h5_filepath):
                self._logger.debug('Run file has already been run! Creating a fresh copy to rerun')
                new_h5_filepath, repeat_number = self.new_rep_name(h5_filepath)
                # Keep counting up until we get a filename that isn't in the filesystem:
                while os.path.exists(new_h5_filepath):
                    new_h5_filepath, repeat_number = self.new_rep_name(new_h5_filepath)
                success = self.clean_h5_file(h5_filepath, new_h5_filepath, repeat_number=repeat_number)
                if not success:
                   return 'Cannot create a re run of this experiment. Is it a valid run file?'
                self.append([new_h5_filepath])
                message = "Experiment added successfully: experiment to be re-run\n"
            else:
                self.append([h5_filepath])
                message = "Experiment added successfully\n"
            if self.manager_paused:
                message += "Warning: Queue is currently paused\n"
            if not self.manager_running:
                message = "Error: Queue is not running\n"
            return message
        else:
            # TODO: Parse and display the contents of "error" in a more human readable format for analysis of what is wrong!
            message =  ("Connection table of your file is not a subset of the experimental control apparatus.\n"
                       "You may have:\n"
                       "    Submitted your file to the wrong control PC\n"
                       "    Added new channels to your h5 file, without rewiring the experiment and updating the control PC\n"
                       "    Renamed a channel at the top of your script\n"
                       "    Submitted an old file, and the experiment has since been rewired\n"
                       "\n"
                       "Please verify your experiment script matches the current experiment configuration, and try again\n"
                       "The error was %s\n"%error)
            return message
            
    def new_rep_name(self, h5_filepath):
        basename, ext = os.path.splitext(h5_filepath)
        if '_rep' in basename and ext == '.h5':
            reps = basename.split('_rep')[-1]
            try:
                reps = int(reps)
            except ValueError:
                # not a rep
                pass
            else:
                return ''.join(basename.split('_rep')[:-1]) + '_rep%05d.h5' % (reps + 1), reps + 1
        return basename + '_rep%05d.h5' % 1, 1
        
    def clean_h5_file(self, h5file, new_h5_file, repeat_number=0):
        try:
            with h5py.File(h5file,'r') as old_file:
                with h5py.File(new_h5_file,'w') as new_file:
                    groups_to_copy = ['devices', 'calibrations', 'script', 'globals', 'connection table', 
                                      'labscriptlib', 'waits']
                    for group in groups_to_copy:
                        if group in old_file:
                            new_file.copy(old_file[group], group)
                    for name in old_file.attrs:
                        new_file.attrs[name] = old_file.attrs[name]
                    new_file.attrs['run repeat'] = repeat_number
        except Exception as e:
            #raise
            self._logger.exception('Clean H5 File Error.')
            return False
            
        return True
    
    @inmain_decorator(wait_for_return=True)    
    def is_in_queue(self,path):                
        item = self._model.findItems(path,column=FILEPATH_COLUMN)
        if item:
            return True
        else:
            return False

    @inmain_decorator(wait_for_return=True)
    def set_status(self, queue_status, shot_filepath=None):
        self._ui.queue_status.setText(str(queue_status))
        if shot_filepath is not None:
            self._ui.running_shot_name.setText('<b>%s</b>'% str(os.path.basename(shot_filepath)))
        else:
            self._ui.running_shot_name.setText('')
        
    @inmain_decorator(wait_for_return=True)
    def get_status(self):
        return self._ui.queue_status.text()
            
    @inmain_decorator(wait_for_return=True)
    def get_next_file(self):
        return str(self._model.takeRow(0)[0].text())
    
    @inmain_decorator(wait_for_return=True)    
    def transition_device_to_buffered(self, name, transition_list, h5file, restart_receiver):
        tab = self.BLACS.tablist[name]
        if self.get_device_error_state(name,self.BLACS.tablist):
            return False
        tab.connect_restart_receiver(restart_receiver)
        tab.transition_to_buffered(h5file,self.current_queue)
        transition_list[name] = tab
        return True
    
    @inmain_decorator(wait_for_return=True)
    def get_device_error_state(self,name,device_list):
        return device_list[name].error_message
       
     
    def manage(self):
        logger = logging.getLogger('BLACS.queue_manager.thread')   
        # While the program is running!
        logger.info('starting')
        
        # HDF5 prints lots of errors by default, for things that aren't
        # actually errors. These are silenced on a per thread basis,
        # and automatically silenced in the main thread when h5py is
        # imported. So we'll silence them in this thread too:
        h5py._errors.silence_errors()
        
        # This name stores the queue currently being used to
        # communicate with tabs, so that abort signals can be put
        # to it when those tabs never respond and are restarted by
        # the user.
        self.current_queue = Queue.Queue()
        
        #TODO: put in general configuration
        timeout_limit = 300 #seconds
        self.set_status("Idle")
        
        while self.manager_running:
            # If the pause button is pushed in, sleep
            if self.manager_paused:
                if self.get_status() == "Idle":
                    logger.info('Paused')
                    self.set_status("Queue paused") 
                time.sleep(1)
                continue
            
            # Get the top file
            try:
                path = self.get_next_file()
                self.set_status('Preparing shot...', path)
                logger.info('Got a file: %s'%path)
            except:
                # If no files, sleep for 1s,
                self.set_status("Idle")
                time.sleep(1)
                continue
            
            devices_in_use = {}
            transition_list = {}   
            start_time = time.time()
            self.current_queue = Queue.Queue()   
            
            # Function to be run when abort button is clicked
            def abort_function():
                try:
                    # Set device name to "Queue Manager" which will never be a labscript device name
                    # as it is not a valid python variable name (has a space in it!)
                    self.current_queue.put(['Queue Manager', 'abort'])
                except Exception:
                    logger.exception('Could not send abort message to the queue manager')
        
            def restart_function(device_name):
                try:
                    self.current_queue.put([device_name, 'restart'])
                except Exception:
                    logger.exception('Could not send restart message to the queue manager for device %s'%device_name)
        
            ##########################################################################################################################################
            #                                                       transition to buffered                                                           #
            ########################################################################################################################################## 
            try:  
                # A Queue for event-based notification when the tabs have
                # completed transitioning to buffered:        
                
                timed_out = False
                error_condition = False
                abort = False
                restarted = False
                self.set_status("Transitioning to buffered...", path)
                
                # Enable abort button, and link in current_queue:
                inmain(self._ui.queue_abort_button.clicked.connect,abort_function)
                inmain(self._ui.queue_abort_button.setEnabled,True)
                                
                
                with h5py.File(path,'r') as hdf5_file:
                    h5_file_devices = hdf5_file['devices/'].keys()
                
                for name in h5_file_devices: 
                    try:
                        # Connect restart signal from tabs to current_queue and transition the device to buffered mode
                        success = self.transition_device_to_buffered(name,transition_list,path,restart_function)
                        if not success:
                            logger.error('%s has an error condition, aborting run' % name)
                            error_condition = True
                            break
                    except Exception as e:
                        logger.exception('Exception while transitioning %s to buffered mode.'%(name))
                        error_condition = True
                        break
                        
                devices_in_use = transition_list.copy()

                while transition_list and not error_condition:
                    try:
                        # Wait for a device to transtition_to_buffered:
                        logger.debug('Waiting for the following devices to finish transitioning to buffered mode: %s'%str(transition_list))
                        device_name, result = self.current_queue.get(timeout=2)
                        
                        #Handle abort button signal
                        if device_name == 'Queue Manager' and result == 'abort':
                            # we should abort the run
                            logger.info('abort signal received from GUI')
                            abort = True
                            break
                            
                        if result == 'fail':
                            logger.info('abort signal received during transition to buffered of %s' % device_name)
                            error_condition = True
                            break
                        elif result == 'restart':
                            logger.info('Device %s was restarted, aborting shot.'%device_name)
                            restarted = True
                            break
                            
                        logger.debug('%s finished transitioning to buffered mode' % device_name)
                        
                        # The tab says it's done, but does it have an error condition?
                        if self.get_device_error_state(device_name,transition_list):
                            logger.error('%s has an error condition, aborting run' % device_name)
                            error_condition = True
                            break
                            
                        del transition_list[device_name]                   
                    except Queue.Empty:
                        # It's been 2 seconds without a device finishing
                        # transitioning to buffered. Is there an error?
                        for name in transition_list:
                            if self.get_device_error_state(name,transition_list):
                                error_condition = True
                                break
                                
                        if error_condition:
                            break
                            
                        # Has programming timed out?
                        if time.time() - start_time > timeout_limit:
                            logger.error('Transitioning to buffered mode timed out')
                            timed_out = True
                            break

                # Handle if we broke out of loop due to timeout or error:
                if timed_out or error_condition or abort or restarted:
                    # Pause the queue, re add the path to the top of the queue, and set a status message!
                    # only if we aren't responding to an abort click
                    if not abort:
                        self.manager_paused = True
                        self.prepend(path)                
                    if timed_out:
                        self.set_status("Programming timed out\nQueue paused")
                    elif abort:
                        self.set_status("Aborted")
                    elif restarted:
                        self.set_status("Device restarted in transition to\nbuffered. Aborted. Queue paused.")
                    else:
                        self.set_status("Device(s) in error state\nQueue Paused")
                        
                    # Abort the run for all devices in use:
                    # need to recreate the queue here because we don't want to hear from devices that are still transitioning to buffered mode
                    self.current_queue = Queue.Queue()
                    for tab in devices_in_use.values():                        
                        # We call abort buffered here, because if each tab is either in mode=BUFFERED or transition_to_buffered failed in which case
                        # it should have called abort_transition_to_buffered itself and returned to manual mode
                        # Since abort buffered will only run in mode=BUFFERED, and the state is not queued indefinitely (aka it is deleted if we are not in mode=BUFFERED)
                        # this is the correct method call to make for either case
                        tab.abort_buffered(self.current_queue)
                        # We don't need to check the results of this function call because it will either be successful, or raise a visible error in the tab.
                        
                        # disconnect restart signal from tabs
                        inmain(tab.disconnect_restart_receiver,restart_function)
                        
                    # disconnect abort button and disable
                    inmain(self._ui.queue_abort_button.clicked.disconnect,abort_function)
                    inmain(self._ui.queue_abort_button.setEnabled,False)
                    
                    # Start a new iteration
                    continue
                
            
            
                ##########################################################################################################################################
                #                                                             SCIENCE!                                                                   #
                ##########################################################################################################################################
            
                # Get front panel data, but don't save it to the h5 file until the experiment ends:
                states,tab_positions,window_data,plugin_data = self.BLACS.front_panel_settings.get_save_data()
                self.set_status("Running (program time: %.3fs)..."%(time.time() - start_time), path)
                    
                # A Queue for event-based notification of when the experiment has finished.
                experiment_finished_queue = Queue.Queue()               
                logger.debug('About to start the master pseudoclock')
                run_time = time.localtime()
                #TODO: fix potential race condition if BLACS is closing when this line executes?
                self.BLACS.tablist[self.master_pseudoclock].start_run(experiment_finished_queue)
                
                                                
                # Wait for notification of the end of run:
                abort = False
                restarted = False
                done = False
                while not (abort or restarted or done):
                    try:
                        done = experiment_finished_queue.get(timeout=0.5) == 'done'
                    except Queue.Empty:
                        pass
                    try:
                        # Poll self.current_queue for abort signal from button or device restart
                        device_name, result = self.current_queue.get_nowait()
                        if (device_name == 'Queue Manager' and result == 'abort'):
                            abort = True
                        if result == 'restart':
                            restarted = True
                        # Check for error states in tabs
                        for device_name, tab in devices_in_use.items():
                            if self.get_device_error_state(device_name,devices_in_use):
                                restarted = True
                    except Queue.Empty:
                        pass
                        
                if abort or restarted:
                    for devicename, tab in devices_in_use.items():
                        if tab.mode == MODE_BUFFERED:
                            tab.abort_buffered(self.current_queue)
                        # disconnect restart signal from tabs 
                        inmain(tab.disconnect_restart_receiver,restart_function)
                                            
                # Disable abort button
                inmain(self._ui.queue_abort_button.clicked.disconnect,abort_function)
                inmain(self._ui.queue_abort_button.setEnabled,False)
                
                if restarted:                    
                    self.manager_paused = True
                    self.prepend(path)  
                    self.set_status("Device restarted during run.\nAborted. Queue paused")
                elif abort:
                    self.set_status("Aborted")
                    
                if abort or restarted:
                    # after disabling the abort button, we now start a new iteration
                    continue                
                
                logger.info('Run complete')
                self.set_status("Saving data...", path)
            # End try/except block here
            except Exception:
                logger.exception("Error in queue manager execution. Queue paused.")

                # Raise the error in a thread for visibility
                zprocess.raise_exception_in_thread(sys.exc_info())
                # clean up the h5 file
                self.manager_paused = True
                # is this a repeat?
                try:
                    with h5py.File(path, 'r') as h5_file:
                        repeat_number = h5_file.attrs.get('run repeat', 0)
                except:
                    repeat_numer = 0
                # clean the h5 file:
                self.clean_h5_file(path, 'temp.h5', repeat_number=repeat_number)
                try:
                    os.remove(path)
                    os.rename('temp.h5', path)
                except WindowsError if platform.system() == 'Windows' else None:
                    logger.warning('Couldn\'t delete failed run file %s, another process may be using it. Using alternate filename for second attempt.'%path)
                    os.rename('temp.h5', path.replace('.h5','_retry.h5'))
                    path = path.replace('.h5','_retry.h5')
                # Put it back at the start of the queue:
                self.prepend(path)
                
                # Need to put devices back in manual mode
                self.current_queue = Queue.Queue()
                for devicename, tab in devices_in_use.items():
                    if tab.mode == MODE_BUFFERED or tab.mode == MODE_TRANSITION_TO_BUFFERED:
                        tab.abort_buffered(self.current_queue)
                    # disconnect restart signal from tabs 
                    inmain(tab.disconnect_restart_receiver,restart_function)
                self.set_status("Error in queue manager\nQueue paused")

                # disconnect and disable abort button
                inmain(self._ui.queue_abort_button.clicked.disconnect,abort_function)
                inmain(self._ui.queue_abort_button.setEnabled,False)
                
                # Start a new iteration
                continue
                             
            ##########################################################################################################################################
            #                                                           SCIENCE OVER!                                                                #
            ##########################################################################################################################################
            
            
            
            ##########################################################################################################################################
            #                                                       Transition to manual                                                             #
            ##########################################################################################################################################
            # start new try/except block here                   
            try:
                with h5py.File(path,'r+') as hdf5_file:
                    self.BLACS.front_panel_settings.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,plugin_data,save_conn_table = False)
                with h5py.File(path,'r+') as hdf5_file:
                    data_group = hdf5_file['/'].create_group('data')
                    # stamp with the run time of the experiment
                    hdf5_file.attrs['run time'] = time.strftime('%Y%m%dT%H%M%S',run_time)
        
                # A Queue for event-based notification of when the devices have transitioned to static mode:
                # Shouldn't need to recreate the queue: self.current_queue = Queue.Queue()    
                    
                # TODO: unserialise this if everything is using zprocess.locking
                # only transition one device to static at a time,
                # since writing data to the h5 file can potentially
                # happen at this stage:
                error_condition = False
                
                # This is far more complicated than it needs to be once transition_to_manual is unserialised!
                response_list = {}
                for device_name, tab in devices_in_use.items():
                    if device_name not in response_list:
                        tab.transition_to_manual(self.current_queue)               
                        while True:
                            # TODO: make the call to current_queue.get() timeout 
                            # and periodically check for error condition on the tab
                            got_device_name, result = self.current_queue.get()
                            # if the response is not for this device, then save it for later!
                            if device_name != got_device_name:
                                response_list[got_device_name] = result
                            else:
                                break
                    else:
                        result = response_list[device_name]
                    # Check for abort signal from device restart
                    if result == 'fail':
                        error_condition = True
                    if result == 'restart':
                        error_condition = True
                    if self.get_device_error_state(device_name,devices_in_use):
                        error_condition = True
                    # Once device has transitioned_to_manual, disconnect restart signal
                    inmain(tab.disconnect_restart_receiver,restart_function)
                    
                if error_condition:                
                    self.set_status("Error in transtion to manual\nQueue Paused")
                                       
            except Exception as e:
                error_condition = True
                logger.exception("Error in queue manager execution. Queue paused.")
                self.set_status("Error in queue manager\nQueue paused")

                # Raise the error in a thread for visibility
                zprocess.raise_exception_in_thread(sys.exc_info())
                
            if error_condition:                
                # clean up the h5 file
                self.manager_paused = True
                # is this a repeat?
                try:
                    with h5py.File(path, 'r') as h5_file:
                        repeat_number = h5_file.attrs.get('run repeat', 0)
                except:
                    repeat_number = 0
                # clean the h5 file:
                self.clean_h5_file(path, 'temp.h5', repeat_number=repeat_number)
                try:
                    os.remove(path)
                    os.rename('temp.h5', path)
                except WindowsError if platform.system() == 'Windows' else None:
                    logger.warning('Couldn\'t delete failed run file %s, another process may be using it. Using alternate filename for second attempt.'%path)
                    os.rename('temp.h5', path.replace('.h5','_retry.h5'))
                    path = path.replace('.h5','_retry.h5')
                # Put it back at the start of the queue:
                self.prepend(path)
                
                # Need to put devices back in manual mode. Since the experiment is over before this try/except block begins, we can 
                # safely call transition_to_manual() on each device tab
                # TODO: Not serialised...could be bad with older BIAS versions :(
                self.current_queue = Queue.Queue()
                for devicename, tab in devices_in_use.items():
                    if tab.mode == MODE_BUFFERED:
                        tab.transition_to_manual(self.current_queue)
                    # disconnect restart signal from tabs 
                    inmain(tab.disconnect_restart_receiver,restart_function)
                
                continue
            
            ##########################################################################################################################################
            #                                                        Analysis Submission                                                             #
            ########################################################################################################################################## 
            logger.info('All devices are back in static mode.')  

            # check for analysis Filters in Plugins
            send_to_analysis = True
            for callback in self.get_callbacks('analysis_cancel_send'):
                try:
                    if callback(path):
                        send_to_analysis = False
                        break
                except Exception:
                    logger.exception("Plugin callback raised an exception")

            # Submit to the analysis server
            if send_to_analysis:
                self.BLACS.analysis_submission.get_queue().put(['file', path])

            ##########################################################################################################################################
            #                                                        Plugin callbacks                                                                #
            ########################################################################################################################################## 
            for plugin in self.BLACS.plugins.values():
                callbacks = plugin.get_callbacks()
                if isinstance(callbacks, dict) and 'shot_complete' in callbacks:
                    try:
                        callbacks['shot_complete'](path)
                    except Exception:
                        logger.exception("Plugin callback raised an exception")

            ##########################################################################################################################################
            #                                                        Repeat Experiment?                                                              #
            ##########################################################################################################################################
            # check for repeat Filters in Plugins
            repeat_shot = self.manager_repeat
            for callback in self.get_callbacks('shot_ignore_repeat'):
                try:
                    if callback(path):
                        repeat_shot = False
                        break
                except Exception:
                    logger.exception("Plugin callback raised an exception")

            if repeat_shot:
                if ((self.manager_repeat_mode == self.REPEAT_ALL) or
                    (self.manager_repeat_mode == self.REPEAT_LAST and inmain(self._model.rowCount) == 0)):
                    # Resubmit job to the bottom of the queue:
                    try:
                        message = self.process_request(path)
                    except Exception:
                        # TODO: make this error popup for the user
                        self.logger.exception('Failed to copy h5_file (%s) for repeat run'%s)
                    logger.info(message)      

            self.set_status("Idle")
        logger.info('Stopping')

