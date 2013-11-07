import logging
import os
import platform
import Queue
import threading
import time

import zlock, h5_lock, h5py
zlock.set_client_process_name('BLACS.queuemanager')
from PySide.QtCore import *
from PySide.QtGui import *
from qtutils import *

# Connection Table Code
from connections import ConnectionTable

FILEPATH_COLUMN = 0

class QueueTreeview(QTreeView):
    def __init__(self,*args,**kwargs):
        QTreeView.__init__(self,*args,**kwargs)
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
        if event.mimeData().hasUrls:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            
            for url in event.mimeData().urls():
                path = url.toLocalFile()
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
    
    def __init__(self, BLACS, ui):
        self._ui = ui
        self.BLACS = BLACS
        self._manager_running = True
        self._manager_paused = False
        self._manager_repeat = False
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
        self._ui.queue_push_up.clicked.connect(self._move_up)
        self._ui.queue_push_down.clicked.connect(self._move_down)
        self._ui.queue_push_to_top.clicked.connect(self._move_top)
        self._ui.queue_push_to_bottom.clicked.connect(self._move_bottom)
        
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
                'files_queued':file_list,
               }
    
    def restore_save_data(self,data):
        if 'manager_paused' in data:
            self.manager_paused = data['manager_paused']
        if 'manager_repeat' in data:
            self.manager_repeat = data['manager_repeat']
        if 'files_queued' in data:
            file_list = list(data['files_queued'])
            self._model.clear()
            self._create_headers()
            for file in file_list:
                self.process_request(str(file))
        
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
    
    @inmain_decorator(False)
    def append(self, h5files):
        for file in h5files:
            self._model.appendRow(QStandardItem(file))
    
    @inmain_decorator(False)
    def prepend(self,h5file):
        self._model.insertRow(0,QStandardItem(h5file))
    
    def process_request(self,h5_filepath):
        # check connection table
        try:
            new_conn = ConnectionTable(h5_filepath)
        except:
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
                new_h5_filepath = self.new_rep_name(h5_filepath)
                # Keep counting up until we get a filename that isn't in the filesystem:
                while os.path.exists(new_h5_filepath):
                    new_h5_filepath = self.new_rep_name(new_h5_filepath)
                success = self.clean_h5_file(h5_filepath, new_h5_filepath)
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
            # TODO: Parse and display the contents of "error" for a more detailed analysis of what is wrong!
            message =  ("Connection table of your file is not a subset of the experimental control apparatus.\n"
                       "You may have:\n"
                       "    Submitted your file to the wrong control PC\n"
                       "    Added new channels to your h5 file, without rewiring the experiment and updating the control PC\n"
                       "    Renamed a channel at the top of your script\n"
                       "    Submitted an old file, and the experiment has since been rewired\n"
                       "\n"
                       "Please verify your experiment script matches the current experiment configuration, and try again\n")
            return message
    
    def new_rep_name(self,h5_filepath):
        basename = os.path.basename(h5_filepath).split('.h5')[0]
        if '_rep' in basename:
            reps = int(basename.split('_rep')[1])
            return h5_filepath.split('_rep')[-2] + '_rep%05d.h5'% (int(reps) + 1)
        return h5_filepath.split('.h5')[0] + '_rep%05d.h5'%1
        

    
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
                    new_file['/'].copy(old_file['/waits'],"waits")
                    for name in old_file.attrs:
                        new_file.attrs[name] = old_file.attrs[name]
        except Exception as e:
            #raise
            self._logger.error('Clean H5 File Error: %s' %str(e))
            return False
            
        return True
        
    def is_in_queue(self,path):                
        item = self._model.findItems(path,column=FILEPATH_COLUMN)
        if item:
            return True
        else:
            return False

    @inmain_decorator(wait_for_return=False)
    def set_status(self,text):
        # TODO: make this fancier!
        self._ui.queue_status.setText(str(text))
        
    @inmain_decorator(wait_for_return=True)
    def get_status(self):
        return self._ui.queue_status.text()
            
    @inmain_decorator(wait_for_return=True)
    def get_next_file(self):
        return str(self._model.takeRow(0)[0].text())
    
    @inmain_decorator(wait_for_return=True)    
    def transition_device_to_buffered(self, name, transition_list, h5file):
        tab = self.BLACS.tablist[name]
        if self.get_device_error_state(name,self.BLACS.tablist):
            return False
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
        timeout_limit = 130 #seconds
        self.set_status("Idle") 
        
        while self.manager_running:
            # If the pause button is pushed in, sleep
            if self.manager_paused:
                if self.get_status() == "Idle":
                    logger.info('Paused')
                self.set_status("Queue Paused") 
                time.sleep(1)
                continue
            
            # Get the top file
            try:
                path = self.get_next_file()
                now_running_text = 'Now running: <b>%s</b>'%os.path.basename(path)
                self.set_status(now_running_text)
                logger.info('Got a file: %s'%path)
            except:
                # If no files, sleep for 1s,
                self.set_status("Idle")
                time.sleep(1)
                continue
            
            try:
                # Transition devices to buffered mode
                transition_list = {}     
                # A Queue for event-based notification when the tabs have
                # completed transitioning to buffered:
                self.current_queue = Queue.Queue()           
                start_time = time.time()
                timed_out = False
                error_condition = False
                self.set_status(now_running_text+"<br>Transitioning to Buffered")
                
                with h5py.File(path,'r') as hdf5_file:
                    h5_file_devices = hdf5_file['devices/'].keys()
                
                for name in h5_file_devices: 
                    try:
                        success = self.transition_device_to_buffered(name,transition_list,path)
                        if not success:
                            logger.error('%s has an error condition, aborting run' % name)
                            error_condition = True
                            break
                    except Exception as e:
                        logger.error('Exception while transitioning %s to buffered mode. Exception was: %s'%(name,str(e)))
                        error_condition = True
                        break
                        
                devices_in_use = transition_list.copy()

                while transition_list and not error_condition:
                    try:
                        # Wait for a device to transtition_to_buffered:
                        logger.debug('Waiting for the following devices to finish transitioning to buffered mode: %s'%str(transition_list))
                        device_name, result = self.current_queue.get(timeout=2)
                        if result == 'fail':
                            logger.info('abort signal received during transition to buffered of ' % device_name)
                            error_condition = True
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
                if timed_out or error_condition:
                    # Pause the queue, re add the path to the top of the queue, and set a status message!
                    self.manager_paused = True
                    self.prepend(path)                
                    if timed_out:
                        self.set_status("Device programming timed out. Queue Paused...")
                    else:
                        self.set_status("One or more devices is in an error state. Queue Paused...")
                            
                    # Abort the run for all devices in use:
                    self.current_queue = Queue.Queue()
                    for tab in devices_in_use.values():
                        # TODO: check if all devices have aborted successfully?
                        # TODO: should we be calling abort_buffered or abort_transition_to_buffered?
                        tab.abort_buffered(self.current_queue)
                    continue
                    
                    
                # Get front panel data, but don't save it to the h5 file until the experiment ends:
                states,tab_positions,window_data,plugin_data = self.BLACS.front_panel_settings.get_save_data()
                self.set_status(now_running_text+"<br>Running...(program time: %.3fs)"%(time.time() - start_time))
                    
                # A Queue for event-based notification of when the experiment has finished.
                self.current_queue = Queue.Queue()               
                logger.debug('About to start the master pseudoclock')
                run_time = time.localtime()
                #TODO: fix potential race condition if BLACS is closing when this line executes?
                self.BLACS.tablist[self.master_pseudoclock].start_run(self.current_queue)
           
                ############
                # Science! #
                ############
                
                # TODO: what if the start_run function of the master pseudoclock throws an exception?
                # What if another device crashes mid-run?
                # We need to catch these cases!
                
                # Wait for notification of the end of run:
                result = self.current_queue.get()
                if result == 'abort':
                   pass # TODO implement this
                logger.info('Run complete')
                self.set_status(now_running_text+"<br>Sequence done, saving data...")

                with h5py.File(path,'r+') as hdf5_file:
                    self.BLACS.front_panel_settings.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,plugin_data,save_conn_table = False)
                with h5py.File(path,'r+') as hdf5_file:
                    data_group = hdf5_file['/'].create_group('data')
                    # stamp with the run time of the experiment
                    hdf5_file.attrs['run time'] = time.strftime('%Y%m%dT%H%M%S',run_time)
        
                # A Queue for event-based notification of when the devices have transitioned to static mode:
                self.current_queue = Queue.Queue()    
                    
                # only transition one device to static at a time,
                # since writing data to the h5 file can potentially
                # happen at this stage:
                error_condition = False
                for devicename, tab in devices_in_use.items():
                    tab.transition_to_manual(self.current_queue)
                    _, result = self.current_queue.get()
                    if result == 'fail':
                        error_condition = True
                    if self.get_device_error_state(devicename,devices_in_use):
                        error_condition = True
                        
                if error_condition:                
                    self.set_status("Error during transtion to static. Queue Paused.")
                    raise Exception('A device failed during transition to static')
                                       
            except Exception as e:
                logger.exception("Error in queue manager execution. Queue paused.")
                # clean up the h5 file
                self.manager_paused = True
                # clean the h5 file:
                self.clean_h5_file(path, 'temp.h5')
                try:
                    os.remove(path)
                    os.rename('temp.h5', path)
                except WindowsError if platform.system() == 'Windows' else None:
                    logger.warning('Couldn\'t delete failed run file %s, another process may be using it. Using alternate filename for second attempt.'%path)
                    os.rename('temp.h5', path.replace('.h5','_retry.h5'))
                # Put it back at the start of the queue:
                self.prepend(path)
                continue
                
            logger.info('All devices are back in static mode.')  
            # Submit to the analysis server
            self.BLACS.analysis_submission.get_queue().put(['file', path])
                
            self.set_status("Idle")
            if self.manager_repeat:
                # Resubmit job to the bottom of the queue:
                try:
                    message = self.process_request(path)
                except:
                    # TODO: make this error popup for the user
                    self.logger.error('Failed to copy h5_file (%s) for repeat run'%s)
                logger.info(message)      

        logger.info('Stopping')

