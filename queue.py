import logging

import h5py
from PySide.QtCore import *
from PySide.QtGui import *

FILEPATH_COLUMN = 0

class QueueManager(object):
    
    def __init__(self, ui):
        self._ui = ui
        self._manager_running = True
        self._manager_paused = False
        self._manager_repeat = False
        
        self._logger = logging.getLogger('BLACS.QueueManager')   
        
        # Create listview model
        self._model = QStandardItemModel()
        self._create_headers()
        self._ui.treeview.setModel(self._model)
        
        # set up buttons
        self._ui.queue_pause_button.toggled.connect(self._toggle_pause)
        self._ui.queue_repeat_button.toggled.connect(self._toggle_repeat)
        self._ui.queue_delete_button.clicked.connect(self._delete_selected_items)
        self._ui.queue_push_up.clicked.connect(self._move_up)
        self._ui.queue_push_down.clicked.connect(self._move_down)
        self._ui.queue_push_to_top.clicked.connect(self._move_top)
        self._ui.queue_push_to_bottom.clicked.connect(self._move_bottom)
        
        
        
    def _create_headers(self):
        self._model.setHorizontalHeaderItem(FILEPATH_COLUMN, QStandardItem('Filepath'))
        
    @property
    def manager_running(self):
        return self._manager_running
        
    def _toggle_pause(self,checked):    
        self.manager_paused = checked
    
    @property
    def manager_paused(self):
        return self._manager_paused
    
    @manager_paused.setter
    def manager_paused(self,value):
        value = bool(value)
        self._manager_paused = value
        if value != self._ui.queue_pause_button.isChecked():
            self._ui.queue_pause_button.setChecked(value)
    
    def _toggle_repeat(self,checked):    
        self.manager_repeat = checked
        
    @property
    def manager_repeat(self):
        return self._manager_repeat
    
    @manager_repeat.setter
    def manager_repeat(self,value):
        value = bool(value)
        self._manager_repeat = value
        if value != self._ui.queue_repeat_button.isChecked():
            self._ui.queue_repeat_button.setChecked(value)
        
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
    
    def append(self, h5files):
        for file in h5files:
            self._model.appendRow(QStandardItem(file))
             
    def clean_h5_file(self,h5file,new_h5_file):
        try:
            with h5py.File(h5file,'r') as old_file:
                with h5py.File(new_h5_file,'w') as new_file:
                    new_file['/'].copy(old_file['/devices'],"devices")
                    new_file['/'].copy(old_file['/calibrations'],"calibrations")
                    new_file['/'].copy(old_file['/script'],"script")
                    new_file['/'].copy(old_file['/globals'],"globals")
                    new_file['/'].copy(old_file['/connection table'],"connection table")
                    new_file['/'].copy(old_file['/labscriptlib'],"labscriptlib")
                    for name in old_file.attrs:
                        new_file.attrs[name] = old_file.attrs[name]
        except Exception as e:
            raise
            self._logger.error('Clean H5 File Error: %s' %str(e))
            return False
            
        return True
        
    def is_in_queue(self,path):
        # item = self.queue.get_iter_first()
        # while item:
            # if path ==  self.queue.get(item,0)[0]:
                # return True
            # else:
                # item = self.queue.iter_next(item)
                
        item = self._model.findItems(path,column=FILEPATH_COLUMN)
        if item:
            return True
        else:
            return False



