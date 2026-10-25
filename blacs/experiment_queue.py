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
import queue
import logging
import os
import re
import threading
import time
import datetime
import sys
import shutil
import uuid
from collections import defaultdict
from tempfile import gettempdir
from binascii import hexlify

from qtutils.qt.QtCore import Qt, QItemSelectionModel
from qtutils.qt.QtGui import QIcon, QAction, QStandardItemModel, QStandardItem
from qtutils.qt.QtWidgets import (
    QTreeView,
    QMenu,
    QFileDialog,
)

import zprocess
from labscript_utils.ls_zprocess import ProcessTree
process_tree = ProcessTree.instance()
import labscript_utils.h5_lock, h5py

from qtutils import inmain_decorator, inmain, inmain_later

from labscript_utils.qtwidgets.elide_label import elide_label
from labscript_utils.connections import ConnectionTable
import labscript_utils.properties

import blacs.plugins as plugins


def tempfilename(prefix='BLACS-temp-', suffix='.h5'):
    """Return a filepath appropriate for use as a temporary file"""
    random_hex = hexlify(os.urandom(16)).decode()
    return os.path.join(gettempdir(), prefix + random_hex + suffix)


FILEPATH_COLUMN = 0
# The item data role of the start and stop orders of the devices of a queued shot:
DEVICE_ORDERS_ROLE = Qt.UserRole + 1


class DeviceOrders(object):
    """Dictionaries of the start_order and stop_order of each device in an open shot
    file"""

    def __init__(self, h5_file):
        self.start_order = {}
        self.stop_order = {}
        for name, group in h5_file['devices'].items():
            for orders, key in [(self.start_order, 'start_order'), (self.stop_order, 'stop_order')]:
                if key in group.attrs:
                    orders[name] = labscript_utils.properties.get_attribute(group, key)
                else:
                    orders[name] = None


def device_status(names, description):
    """Return "Device <name> <description>", listing the names if there are several"""
    names = sorted(names)
    if not names:
        return 'Device(s) ' + description
    noun = 'Device' if len(names) == 1 else 'Devices'
    return '%s %s %s' % (noun, ', '.join(names), description)

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
        self._requeue_aborted_shot = False
        self._manager_paused = False
        self._manager_repeat = False
        self._manager_repeat_mode = self.REPEAT_ALL
        self.master_pseudoclock = self.BLACS.connection_table.master_pseudoclock
        
        self._logger = logging.getLogger('BLACS.QueueManager')   
        # The shot being run, accessed only in the main thread:
        self._shot = None
        # Set in the main thread when the queue manager thread may have a shot to run:
        self._wakeup = threading.Event()

        # Paths of the files in the queue, and paths of files being added to it by
        # process_request(). Accessed from any thread with self._queued_lock held, and
        # updated in the main thread when rows are inserted or removed:
        self._queued = set()
        self._adding = set()
        self._queued_lock = threading.Lock()
        # Files and their DeviceOrders to be appended to the queue in the main thread:
        self._appends = []
        self._appends_posted = False

        # Create listview model
        self._model = QStandardItemModel()
        self._create_headers()
        self._model.rowsInserted.connect(self._on_rows_inserted)
        self._model.rowsRemoved.connect(self._update_queued)
        self._model.modelReset.connect(self._update_queued)
        self._ui.treeview.setModel(self._model)
        self._ui.treeview.add_to_queue = self.process_request
        self._ui.treeview.delete_selection = self._delete_selected_items
        
        # set up buttons
        self._ui.queue_pause_button.toggled.connect(self._toggle_pause)
        self._ui.queue_repeat_button.toggled.connect(self._toggle_repeat)
        self._ui.queue_delete_button.clicked.connect(self._delete_selected_items)
        self._ui.queue_clear_button.clicked.connect(self._toggle_clear)
        self._ui.queue_abort_button.clicked.connect(self._on_abort_clicked)
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
    def manager_running(self):
        return self._manager_running
        
    @manager_running.setter
    @inmain_decorator(True)
    def manager_running(self,value):
        value = bool(value)
        self._manager_running = value
        self._wakeup.set()
        
    def _toggle_pause(self,checked):    
        self.manager_paused = checked

    def _toggle_clear(self):
        self._model.clear()
        self._create_headers()

    @property
    def manager_paused(self):
        return self._manager_paused
    
    @manager_paused.setter
    @inmain_decorator(True)
    def manager_paused(self,value):
        value = bool(value)
        self._manager_paused = value
        self._wakeup.set()
        if value != self._ui.queue_pause_button.isChecked():
            self._ui.queue_pause_button.setChecked(value)
    
    def _toggle_repeat(self,checked):    
        self.manager_repeat = checked
        
    @property
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
    
    def _update_queued(self, *args):
        """Set self._queued to the paths in the model. Runs in the main thread."""
        items = [self._model.item(row) for row in range(self._model.rowCount())]
        with self._queued_lock:
            self._queued = {item.text() for item in items if item is not None}

    def _on_rows_inserted(self, parent, first, last):
        self._update_queued()
        self._wakeup.set()

    def _start_adding(self, path):
        """Record that a file is being added to the queue, unless it is in the queue or
        being added already. Return whether it was recorded."""
        with self._queued_lock:
            if path in self._queued or path in self._adding:
                return False
            self._adding.add(path)
            return True

    def queue_length(self):
        """Return the number of files in the queue or being added to it"""
        with self._queued_lock:
            return len(self._queued) + len(self._adding)

    def _add(self, path, device_orders):
        """Append a file recorded by _start_adding() to the queue. Called from the main
        thread, the file is appended before returning; from another thread, it is
        appended by the main thread later, together with any others added meanwhile."""
        with self._queued_lock:
            self._appends.append((path, device_orders))
            post = not self._appends_posted
            self._appends_posted = True
        if threading.current_thread() is threading.main_thread():
            self._append_added()
        elif post:
            inmain_later(self._append_added)

    def _append_added(self):
        with self._queued_lock:
            appends = self._appends
            self._appends = []
            self._appends_posted = False
        for path, device_orders in appends:
            item = QStandardItem(path)
            item.setToolTip(path)
            item.setData(device_orders, DEVICE_ORDERS_ROLE)
            self._model.appendRow(item)
            with self._queued_lock:
                self._adding.discard(path)

    @inmain_decorator(True)
    def stop(self):
        """Stop the queue manager. A shot that is being programmed or run is aborted
        and put back at the top of the queue. A shot that is being saved is completed.
        The queue manager thread ends once the current shot, if any, is done."""
        self._requeue_aborted_shot = True
        self.manager_running = False
        if self._shot is not None:
            self._shot.abort()

    @inmain_decorator(True)
    def prepend(self,h5file):
        if not self.is_in_queue(h5file):
            self._model.insertRow(0,QStandardItem(h5file))
    
    def process_request(self,h5_filepath):
        """Check a shot file and add it to the queue, or a copy of it if it has been run
        or is in the queue. May be called from any thread. Returns a message for the
        user."""
        try:
            h5_file = h5py.File(h5_filepath, 'r')
        except Exception:
            return "H5 file not accessible to Control PC\n"
        with h5_file:
            # check connection table
            try:
                new_conn = ConnectionTable(h5_file, logging_prefix='BLACS')
            except Exception:
                return "H5 file not accessible to Control PC\n"
            result,error = self.BLACS.connection_table.compare_to(new_conn)
            if not result:
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
            device_orders = DeviceOrders(h5_file)
            # Has this run file been run already?
            if 'data' not in h5_file['/'] and self._start_adding(h5_filepath):
                queued_path = h5_filepath
                message = "Experiment added successfully\n"
            else:
                self._logger.debug('Run file has already been run! Creating a fresh copy to rerun')
                queued_path, repeat_number = self.new_rep_name(h5_filepath)
                # Keep counting up until we get a filename that isn't in the filesystem
                # or the queue:
                while os.path.exists(queued_path) or not self._start_adding(queued_path):
                    queued_path, repeat_number = self.new_rep_name(queued_path)
                success = self.clean_h5_file(h5_file, queued_path, repeat_number=repeat_number)
                if not success:
                    with self._queued_lock:
                        self._adding.discard(queued_path)
                    return 'Cannot create a re run of this experiment. Is it a valid run file?'
                message = "Experiment added successfully: experiment to be re-run\n"
        self._add(queued_path, device_orders)
        if self.manager_paused:
            message += "Warning: Queue is currently paused\n"
        if not self.manager_running:
            message = "Error: Queue is not running\n"
        return message
            
    def new_rep_name(self, h5_filepath):
        """Return the path of the next repeat of a shot file and its repeat number.
        A trailing _rep<digits> suffix in the file name is replaced; the directory is
        unchanged."""
        directory, filename = os.path.split(h5_filepath)
        basename, ext = os.path.splitext(filename)
        match = re.match(r'^(.*)_rep(\d+)$', basename)
        if match is not None and ext == '.h5':
            basename = match.group(1)
            reps = int(match.group(2)) + 1
        else:
            reps = 1
        return os.path.join(directory, basename + '_rep%05d.h5' % reps), reps
        
    def clean_h5_file(self, old_file, new_h5_file, repeat_number=0):
        """Write a copy of an open shot file to a new file, without the groups and the
        run time attribute that are written when the shot is run. The copy is made in
        memory and written to the new file at once, without a zlock, since no other
        program knows of the new file. Returns whether the copy was written."""
        groups_to_copy = [
            'devices',
            'calibrations',
            'script',
            'globals',
            'connection table',
            'labscriptlib',
            'waits',
            'time_markers',
            'shot_properties',
        ]
        try:
            fapl = h5py.h5p.create(h5py.h5p.FILE_ACCESS)
            fapl.set_fapl_core(backing_store=False)
            # The name must differ from that of any open file. A file opened from an
            # identifier is not locked with zlock.
            memory_name = ('blacs_copy_%s' % uuid.uuid4()).encode()
            with h5py.File(h5py.h5f.create(memory_name, fapl=fapl)) as new_file:
                for group in groups_to_copy:
                    if group in old_file:
                        new_file.copy(old_file[group], group)
                for name in old_file.attrs:
                    if name != 'run time':
                        new_file.attrs[name] = old_file.attrs[name]
                new_file.attrs['run repeat'] = repeat_number
                new_file.flush()
                image = new_file.id.get_file_image()
            with open(new_h5_file, 'wb') as f:
                f.write(image)
        except Exception:
            self._logger.exception('Clean H5 File Error.')
            return False
        return True
    
    def is_in_queue(self, path):
        """Return whether a file is in the queue or being added to it"""
        with self._queued_lock:
            return path in self._queued or path in self._adding

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
            

    def _requeue_failed_shot(self, path, logger):
        """Replace the shot file with a copy that excludes the run data, and put it
        back at the top of the queue. Returns the requeued path and whether the file
        was replaced. If the shot file cannot be read or replaced, the original path
        is requeued."""
        cleaned = False
        try:
            # is this a repeat?
            temp_path = tempfilename()
            with h5py.File(path, 'r') as h5_file:
                repeat_number = h5_file.attrs.get('run repeat', 0)
                cleaned = self.clean_h5_file(h5_file, temp_path, repeat_number=repeat_number)
            if cleaned:
                try:
                    shutil.move(temp_path, path)
                except Exception:
                    msg = ('Couldn\'t delete failed run file %s, ' % path +
                           'another process may be using it. Using alternate '
                           'filename for second attempt.')
                    logger.warning(msg, exc_info=True)
                    shutil.move(temp_path, path.replace('.h5','_retry.h5'))
                    path = path.replace('.h5','_retry.h5')
        except Exception:
            logger.exception('Could not clean up the failed run file %s. Queue paused.' % path)
            cleaned = False
        self.prepend(path)
        return path, cleaned

    def _take_next_shot(self):
        """Remove the first file from the queue and return a Shot for it, or None if the
        queue is paused or empty. Runs in the main thread."""
        self._wakeup.clear()
        if not self._manager_running:
            return None
        if self._manager_paused:
            if self.get_status() == "Idle":
                self._logger.info('Paused')
                self.set_status("Queue paused")
            return None
        if not self._model.rowCount():
            self.set_status("Idle")
            return None
        item = self._model.takeRow(0)[0]
        path = str(item.text())
        self._shot = Shot(self, path, item.data(DEVICE_ORDERS_ROLE))
        self.set_status("Transitioning to buffered...", path)
        self._ui.queue_abort_button.setEnabled(True)
        return self._shot

    def _wait_for_next_shot(self):
        """Return a Shot for the next file in the queue, waiting until there is one and
        the queue is not paused. Returns None if the queue manager is stopped."""
        while self.manager_running:
            shot = inmain(self._take_next_shot)
            if shot is not None:
                return shot
            self._wakeup.wait()
        return None

    def _end_shot(self, shot):
        """Disconnect the restart receivers of the shot's tabs and disable the abort
        button. Runs in the main thread."""
        for tab in shot.tabs.values():
            tab.disconnect_restart_receiver(self._on_tab_restart)
        self._ui.queue_abort_button.setEnabled(False)
        if self._shot is shot:
            self._shot = None

    def _on_abort_clicked(self):
        if self._shot is not None:
            self._shot.abort()

    def _on_tab_restart(self, device_name):
        if self._shot is not None:
            inmain_later(self._shot.tab_restarted, device_name)

    def _wait_for_event(self, shot, logger, deadline=None):
        """Return the next event of the shot as a tuple (kind, data). Every 2 seconds
        without an event, the tabs are checked for error states. A shot that has not
        had an event by the deadline (a time.time() value) is timed out."""
        while True:
            try:
                return shot.events.get(timeout=2)
            except queue.Empty:
                inmain(shot.check_error_states)
                if deadline is not None and time.time() > deadline:
                    logger.error('Transitioning to buffered mode timed out')
                    inmain(shot.time_out)

    def _abort_shot(self, shot):
        """Abort the buffered run of every tab of the shot. Runs in the main thread."""
        shot.finish(None)
        for tab in shot.tabs.values():
            # abort_buffered runs only in MODE_BUFFERED and is not queued indefinitely,
            # so it is dropped by a tab that has returned to manual mode, and it runs in
            # a tab that is still transitioning to buffered once the transition is done.
            tab.abort_buffered(queue.Queue())
        self._end_shot(shot)

    def manage(self):
        logger = logging.getLogger('BLACS.queue_manager.thread')
        process_tree.zlock_client.set_thread_name('queue_manager')
        logger.info('starting')

        # HDF5 prints lots of errors by default, for things that aren't
        # actually errors. These are silenced on a per thread basis,
        # and automatically silenced in the main thread when h5py is
        # imported. So we'll silence them in this thread too:
        h5py._errors.silence_errors()

        self.set_status("Idle")
        while True:
            try:
                shot = self._wait_for_next_shot()
                if shot is None:
                    break
                logger.info('Got a file: %s' % shot.path)
                self._run_shot(shot, logger)
            except Exception:
                logger.exception("Unhandled error in the queue manager. Queue paused.")
                zprocess.raise_exception_in_thread(sys.exc_info())
                self.manager_paused = True
                self.set_status("Error in queue manager\nQueue paused")
        logger.info('Stopping')

    def _run_shot(self, shot, logger):
        """Run one shot. The main thread transitions the tabs through each phase. This
        thread starts each phase, runs the plugin callbacks between them, reads and
        writes the shot file, and handles the outcome of each phase."""
        #TODO: put in general configuration
        timeout_limit = 300 #seconds
        path = shot.path
        try:
            try:
                for callback in plugins.get_callbacks('pre_transition_to_buffered'):
                    try:
                        callback(path)
                    except Exception:
                        logger.exception("Plugin callback raised an exception")

                device_orders = shot.device_orders
                if device_orders is None:
                    with h5py.File(path, 'r') as hdf5_file:
                        device_orders = DeviceOrders(hdf5_file)
                start_time = time.time()
                inmain(shot.transition_to_buffered, device_orders, start_time)
                kind, data = self._wait_for_event(shot, logger, start_time + timeout_limit)
                if kind == 'buffered':
                    for callback in plugins.get_callbacks('science_starting'):
                        try:
                            callback(path)
                        except Exception:
                            logger.exception("Plugin callback raised an exception")
                    inmain(shot.start_run)
                    kind, data = self._wait_for_event(shot, logger)

                if kind != 'running':
                    # Pause the queue and put the file back at the top of the queue,
                    # unless the shot was aborted with the abort button:
                    if kind != 'abort':
                        self.manager_paused = True
                        self.prepend(path)
                    elif self._requeue_aborted_shot:
                        self.prepend(path)
                    if kind == 'timeout':
                        self.set_status(device_status(data, 'timed out programming') + "\nQueue paused")
                    elif kind == 'abort' and self._requeue_aborted_shot:
                        self.set_status("Aborted, shot requeued")
                    elif kind == 'abort':
                        self.set_status("Aborted")
                    elif kind == 'restart':
                        self.set_status(device_status(data, 'restarted in transition to buffered') + "\nQueue paused")
                    else:
                        self.set_status(device_status(data, 'in error state') + "\nQueue paused")
                    inmain(self._abort_shot, shot)
                    return

                save_error = None
                try:
                    with h5py.File(path, 'r+') as hdf5_file:
                        self.BLACS.front_panel_settings.store_front_panel_in_h5(
                            hdf5_file, *shot.front_panel_data, save_conn_table=False, save_queue_data=False
                        )
                        hdf5_file['/'].require_group('data')
                        # stamp with the run time of the experiment
                        hdf5_file.attrs['run time'] = shot.run_time.strftime('%Y%m%dT%H%M%S.%f')
                except Exception as e:
                    save_error = e
                inmain_later(shot.front_panel_saved, save_error is None)

                kind, data = self._wait_for_event(shot, logger)
                if kind in ('abort', 'restart'):
                    inmain(self._abort_shot, shot)
                    if kind == 'abort' and self._requeue_aborted_shot:
                        self._requeue_failed_shot(path, logger)
                        self.set_status("Aborted, shot requeued")
                    elif kind == 'abort':
                        self.set_status("Aborted")
                    else:
                        restarted_devices, error_devices = data
                        self.manager_paused = True
                        self._requeue_failed_shot(path, logger)
                        if error_devices:
                            self.set_status(device_status(error_devices, 'in error state during run') + "\nQueue paused")
                        else:
                            self.set_status(device_status(restarted_devices, 'restarted during run') + "\nQueue paused")
                    return
                if save_error is not None:
                    raise save_error
            finally:
                for callback in plugins.get_callbacks('science_over'):
                    try:
                        callback(path)
                    except Exception:
                        logger.exception("Plugin callback raised an exception")
            inmain(shot.transition_to_manual)
            kind, error_devices = self._wait_for_event(shot, logger)
        except Exception:
            logger.exception("Error in queue manager execution. Queue paused.")
            # Raise the error in a thread for visibility
            zprocess.raise_exception_in_thread(sys.exc_info())
            self.manager_paused = True
            inmain(self._abort_shot, shot)
            path, cleaned = self._requeue_failed_shot(path, logger)
            if cleaned:
                self.set_status("Error in queue manager\nQueue paused")
            else:
                self.set_status("Shot file inaccessible\nQueue paused")
            return

        if error_devices:
            self.set_status(device_status(error_devices, 'failed to transition to manual') + "\nQueue paused")
            self.manager_paused = True
            path, cleaned = self._requeue_failed_shot(path, logger)
            if not cleaned:
                self.set_status("Shot file inaccessible\nQueue paused")
            return

        logger.info('All devices are back in static mode.')

        # check for analysis Filters in Plugins
        send_to_analysis = True
        for callback in plugins.get_callbacks('analysis_cancel_send'):
            try:
                if callback(path):
                    send_to_analysis = False
                    break
            except Exception:
                logger.exception("Plugin callback raised an exception")

        # Submit to the analysis server
        if send_to_analysis:
            self.BLACS.analysis_submission.get_queue().put(['file', path])

        for callback in plugins.get_callbacks('shot_complete'):
            try:
                callback(path)
            except Exception:
                logger.exception("Plugin callback raised an exception")

        # check for repeat Filters in Plugins
        repeat_shot = self.manager_repeat
        for callback in plugins.get_callbacks('shot_ignore_repeat'):
            try:
                if callback(path):
                    repeat_shot = False
                    break
            except Exception:
                logger.exception("Plugin callback raised an exception")

        if repeat_shot:
            if ((self.manager_repeat_mode == self.REPEAT_ALL) or
                (self.manager_repeat_mode == self.REPEAT_LAST and self.queue_length() == 0)):
                # Resubmit job to the bottom of the queue:
                try:
                    message = self.process_request(path)
                    logger.info(message)
                except Exception:
                    # TODO: make this error popup for the user
                    logger.exception('Failed to copy h5_file (%s) for repeat run' % path)


class MainThreadNotifier(object):
    """An object with the put() method of a queue, for the tabs to notify the queue
    manager with. Each item is passed to a function that is called in the main thread
    from the Qt event loop."""

    def __init__(self, function):
        self._function = function

    def put(self, item, *args, **kwargs):
        inmain_later(self._function, item)


class Shot(object):
    """The tabs of the shot that the queue manager is running, and the phase of the
    shot. Methods other than those of the events queue are called in the main thread.

    The phase is one of 'preparing', 'buffered', 'starting', 'running', 'done',
    'manual', or None once the shot has ended. When a phase ends, a tuple (kind, data)
    is put to the events queue, which the queue manager thread reads. The kinds are:

    'buffered': all tabs are in buffered mode. The queue manager thread runs the
        science_starting callbacks and calls start_run().
    'running': the master pseudoclock has been told to start the run.
    'done': the run is over and the front panel has been saved to the shot file, or
        could not be. The queue manager thread runs the science_over callbacks and
        calls transition_to_manual(); the phase is 'done' until then.
    'manual': the tabs have transitioned to manual mode. The data is the list of
        devices that failed to.
    'error', 'timeout', 'restart': the data is the list of devices that failed,
        timed out or were restarted in the transition to buffered mode. For a restart
        during the run, the data is the restarted devices and the devices in an error
        state.
    'abort': the abort button was clicked.
    """

    def __init__(self, queue_manager, path, device_orders=None):
        self.queue_manager = queue_manager
        self.logger = logging.getLogger('BLACS.queue_manager.shot')
        self.path = path
        # The DeviceOrders of the shot file, if they were read when it was queued:
        self.device_orders = device_orders
        self.events = queue.Queue()
        self.phase = 'preparing'
        self.tabs = {}
        self.start_groups = []
        self.stop_groups = []
        # The tabs that are transitioning and have not reported back:
        self.pending = {}
        self.manual_error_devices = []
        # Set in the main thread when all tabs are in buffered mode:
        self.start_time = None
        self.front_panel_data = None
        self.run_time = None
        # Whether the front panel has been saved to the shot file, None until it has
        # been attempted:
        self.saved = None
        self.run_done = False
        self._buffered_notifier = MainThreadNotifier(self._on_buffered)
        self._run_notifier = MainThreadNotifier(self._on_run_notification)
        self._manual_notifier = MainThreadNotifier(self._on_manual)

    def finish(self, kind, data=None):
        """End the current phase and put an event to the events queue, unless kind is
        None."""
        if self.phase is not None:
            self.phase = None
            if kind is not None:
                self.events.put((kind, data))

    def abort(self):
        if self.phase in ('preparing', 'buffered', 'starting', 'running'):
            self.logger.info('abort signal received from GUI')
            self.finish('abort')

    def tab_restarted(self, name):
        if name not in self.tabs:
            return
        if self.phase in ('buffered', 'starting'):
            self.logger.info('Device %s was restarted, aborting shot.' % name)
            self.finish('restart', [name])
        elif self.phase == 'running':
            error_devices = [n for n, tab in self.tabs.items() if tab.error_message]
            self.finish('restart', ([name], error_devices))
        elif self.phase in ('done', 'manual'):
            in_later_group = any(name in group for group in self.stop_groups)
            if name not in self.pending and not in_later_group:
                return
            self.logger.debug('%s restarted before or during transition to manual' % name)
            self.pending.pop(name, None)
            for group in self.stop_groups:
                group.discard(name)
            self.manual_error_devices.append(name)
            if self.phase == 'manual' and not self.pending:
                self._next_manual_group()

    def check_error_states(self):
        if self.phase == 'buffered':
            error_devices = [name for name, tab in self.pending.items() if tab.error_message]
            if error_devices:
                for name in error_devices:
                    self.logger.error('%s has an error condition, aborting run' % name)
                self.finish('error', error_devices)
        elif self.phase == 'manual':
            for name, tab in list(self.pending.items()):
                if tab.error_message:
                    self.logger.debug('%s is in an error state' % name)
                    del self.pending[name]
                    self.manual_error_devices.append(name)
            if not self.pending:
                self._next_manual_group()

    def time_out(self):
        if self.phase == 'buffered':
            self.finish('timeout', list(self.pending))

    def transition_to_buffered(self, device_orders, start_time):
        if self.phase != 'preparing':
            return
        self.phase = 'buffered'
        self.start_time = start_time
        tablist = self.queue_manager.BLACS.tablist
        self.tabs = {name: tablist[name] for name in device_orders.start_order}
        self.start_groups = self._groups(device_orders.start_order)
        self.stop_groups = self._groups(device_orders.stop_order)
        self._next_buffered_group()

    @staticmethod
    def _groups(order):
        """The sets of device names that have the same order, sorted by order"""
        groups = defaultdict(set)
        for name, value in order.items():
            groups[value].add(name)
        return [groups[value] for value in sorted(groups)]

    def _next_buffered_group(self):
        if not self.start_groups:
            # Get front panel data, but don't save it to the h5 file until the run starts:
            self.front_panel_data = self.queue_manager.BLACS.front_panel_settings.get_save_data()
            program_time = time.time() - self.start_time
            self.queue_manager.set_status("Running (program time: %.3fs)..." % program_time, self.path)
            self.phase = 'starting'
            self.events.put(('buffered', None))
            return
        restart_receiver = self.queue_manager._on_tab_restart
        for name in self.start_groups.pop(0):
            tab = self.tabs[name]
            try:
                if tab.error_message:
                    self.logger.error('%s has an error condition, aborting run' % name)
                    self.finish('error', [name])
                    return
                tab.connect_restart_receiver(restart_receiver)
                tab.transition_to_buffered(self.path, self._buffered_notifier)
            except Exception:
                self.logger.exception('Exception while transitioning %s to buffered mode.' % name)
                self.finish('error', [name])
                return
            self.pending[name] = tab
        self.logger.debug('Waiting for the following devices to finish transitioning to buffered mode: %s' % ', '.join(sorted(self.pending)))

    def _on_buffered(self, item):
        name, result = item
        if self.phase != 'buffered' or name not in self.pending:
            return
        tab = self.pending.pop(name)
        if result == 'fail':
            self.logger.info('abort signal received during transition to buffered of %s' % name)
            self.finish('error', [name])
        elif tab.error_message:
            self.logger.error('%s has an error condition, aborting run' % name)
            self.finish('error', [name])
        else:
            self.logger.debug('%s finished transitioning to buffered mode' % name)
            if not self.pending:
                self._next_buffered_group()

    def start_run(self):
        if self.phase not in ('buffered', 'starting'):
            return
        self.phase = 'running'
        self.logger.debug('About to start the master pseudoclock')
        self.run_time = datetime.datetime.now()
        master_pseudoclock = self.queue_manager.master_pseudoclock
        self.queue_manager.BLACS.tablist[master_pseudoclock].start_run(self._run_notifier)
        self.events.put(('running', None))

    def front_panel_saved(self, success):
        self.saved = success
        self._end_run()

    def _on_run_notification(self, item):
        if self.phase == 'running' and item == 'done':
            self.logger.info('Run complete')
            self.run_done = True
            self._end_run()

    def _end_run(self):
        """Transition the tabs to manual mode once the run is over and the front panel
        has been saved to the shot file"""
        if self.phase != 'running' or not self.run_done or self.saved is None:
            return
        self.phase = 'done'
        self.events.put(('done', None))

    def transition_to_manual(self):
        self.phase = 'manual'
        self.queue_manager._ui.queue_abort_button.setEnabled(False)
        self.queue_manager.set_status("Saving data...", self.path)
        self._next_manual_group()

    def _next_manual_group(self):
        while self.stop_groups and not self.pending:
            for name in self.stop_groups.pop(0):
                tab = self.tabs[name]
                try:
                    tab.transition_to_manual(self._manual_notifier)
                except Exception:
                    self.logger.exception('Exception while transitioning %s to manual mode.' % name)
                    self.manual_error_devices.append(name)
                    continue
                self.pending[name] = tab
            if self.pending:
                self.logger.info('Waiting for the following devices to finish transitioning to manual mode: %s' % ', '.join(sorted(self.pending)))
        if not self.pending:
            self.queue_manager._end_shot(self)
            self.finish('manual', self.manual_error_devices)

    def _on_manual(self, item):
        name, result = item
        if self.phase != 'manual' or name not in self.pending:
            return
        tab = self.pending.pop(name)
        if result == 'fail':
            self.manual_error_devices.append(name)
            self.logger.debug('%s failed to transition to manual' % name)
        elif tab.error_message:
            self.manual_error_devices.append(name)
            self.logger.debug('%s is in an error state' % name)
        else:
            self.logger.debug('%s finished transitioning to manual mode' % name)
        if not self.pending:
            self._next_manual_group()
