#####################################################################
#                                                                   #
# /plugins/connection_table/__init__.py                             #
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
import subprocess
import sys
import ast

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from blacs.compile_and_restart import CompileAndRestart
from labscript_utils.filewatcher import FileWatcher
from qtutils import *
from blacs.plugins import PLUGINS_DIR

FILEPATH_COLUMN = 0
name = "Connection Table"
module = "connection_table" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

class Plugin(object):
    def __init__(self,initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        
    def get_menu_class(self):
        return Menu
        
    def get_notification_classes(self):
        return [RecompileNotification, BrokenDevicesNotification]

    def get_setting_classes(self):
        return [Setting]
        
    def get_callbacks(self):
        return {'settings_changed':self.notifications[RecompileNotification].setup_filewatching}

    def set_menu_instance(self,menu):
        self.menu = menu
        
    def set_notification_instances(self,notifications):
        self.notifications = notifications
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        # The 'clean' modified info. We don't save the 'dirty' modified info. If watched
        # files are 'dirty' then our callback will be immediately called.
        clean_modified_info = self.initial_settings.get('clean_modified_info', None)
        self.notifications[RecompileNotification].setup_filewatching(clean_modified_info)
        self.menu.close_notification_func = self.notifications[RecompileNotification].on_restart
        failed_devices = list(self.BLACS['experiment_queue'].BLACS.failed_device_settings.keys())
        if failed_devices:
            self.notifications[RecompileNotification]._show()
            self.notifications[BrokenDevicesNotification].set_broken_devices(failed_devices)
            self.notifications[BrokenDevicesNotification]._show()

    def get_save_data(self):
        return self.notifications[RecompileNotification].get_save_data()

    def close(self):
        self.notifications[RecompileNotification].close()
        self.notifications[BrokenDevicesNotification].close()

class Menu(object):
    def __init__(self,BLACS):
        self.BLACS = BLACS
        self.close_notification_func = None
        
    def get_menu_items(self):
        return {'name':name,        
                'menu_items':[{'name':'Edit',
                               'action':self.on_edit_connection_table,
                               'icon': ':/qtutils/fugue/document--pencil'
                              },
                              {'name':'Select Globals',
                               'action':self.on_select_globals,
                               'icon': ':/qtutils/fugue/table--pencil'
                              },
                              {'name':'Recompile',
                               'action':self.on_recompile_connection_table,
                               'icon': ':/qtutils/fugue/arrow-circle'
                              }
                             ]                                
               }
    
    def on_select_globals(self,*args,**kwargs):
        self.BLACS['settings'].create_dialog(goto_page=Setting)
      
    def on_edit_connection_table(self,*args,**kwargs):
        # get path to text editor
        editor_path = self.BLACS['exp_config'].get('programs','text_editor')
        editor_args = self.BLACS['exp_config'].get('programs','text_editor_arguments')
        if editor_path:  
            if '{file}' in editor_args:
                editor_args = editor_args.replace('{file}', self.BLACS['exp_config'].get('paths','connection_table_py'))
            else:
                editor_args = self.BLACS['exp_config'].get('paths','connection_table_py') + " " + editor_args            
            try:
                subprocess.Popen([editor_path,editor_args])
            except Exception:
                QMessageBox.information(self.BLACS['ui'],"Error","Unable to launch text editor. Check the path is valid in the experiment config file (%s) (you must restart BLACS if you edit this file)"%self.BLACS['exp_config'].config_path)
        else:
            QMessageBox.information(self.BLACS['ui'],"Error","No text editor path was specified in the experiment config file (%s) (you must restart BLACS if you edit this file)"%self.BLACS['exp_config'].config_path)
    
    def on_recompile_connection_table(self,*args,**kwargs):
        logger.info('recompile connection table called')
        # get list of globals
        globals_files = self.BLACS['settings'].get_value(Setting,'globals_list')
        # Remove unicode encoding so that zprocess.locking doesn't crash
        for i in range(len(globals_files)):
            globals_files[i] = str(globals_files[i])
        CompileAndRestart(self.BLACS, globals_files, self.BLACS['exp_config'].get('paths','connection_table_py'), self.BLACS['exp_config'].get('paths','connection_table_h5'),close_notification_func=self.close_notification_func)


class BrokenDevicesNotification(object):
    name = 'Device initialization failed'
    def __init__(self, BLACS):
        # Create the widget
        self._ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'broken_device_notification.ui'))

    def get_widget(self):
        return self._ui

    def set_broken_devices(self, device_names):
        self._ui.label.setText('''<html><head/><body><span style=" font-weight:600; color:#ff0000;">BLACS failed to initialize some of your devices.
            It is advised that you solve this problem before using BLACS.
            The devices causing problems were: {}</span></body></html>'''.format(', '.join(device_names)))

    def get_properties(self):
        return {'can_hide':False, 'can_close':False}

    def set_functions(self,show_func,hide_func,close_func,get_state):
        self._show = show_func
        self._hide = hide_func
        self._close = close_func
        self._get_state = get_state

    def get_save_data(self):
        return {}

    def close(self):
        pass

class RecompileNotification(object):
    name = name
    def __init__(self, BLACS):
        # set up the file watching
        self.BLACS = BLACS
        self.filewatcher = None
        self.clean_modified_info = None
        # Create the widget
        self._ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'notification.ui'))
        self._ui.button.clicked.connect(self.on_recompile_connection_table)
            
    def get_widget(self):
        return self._ui
        
    def get_properties(self):
        return {'can_hide':True, 'can_close':False}
        
    def set_functions(self, show_func, hide_func, close_func, get_state):
        self._show = show_func
        self._hide = hide_func
        self._close = close_func
        self._get_state = get_state
                
    def on_recompile_connection_table(self,*args,**kwargs):
        self.BLACS['plugins'][module].menu.on_recompile_connection_table()
        
    def callback(self, name, info, event=None):
        if event  == 'deleted':
            logger.info('{} {} ({})'.format(name, event, info))
            inmain(self._show)
        if event  == 'modified':
            logger.info('{} {} ({})'.format(name, event, info))
            inmain(self._show)
        elif event  == 'original':
            logger.info('All watched files restored')
            inmain(self._close)
        elif event == 'restored':
            logger.info('{} {} ({})'.format(name, event, info))
        elif event ==  'debug':
            logger.info(info)

    def setup_filewatching(self, clean_modified_info=None):
        folder_list = []
        file_list = [self.BLACS['connection_table_labscript'], self.BLACS['connection_table_h5file']]
        labconfig = self.BLACS['exp_config']
        try:
            hashable_types = labconfig.get('BLACS/plugins', 'connection_table.hashable_types')
            hashable_types = ast.literal_eval(hashable_types)
        except labconfig.NoOptionError:
            hashable_types = ['.py', '.txt', '.ini', '.json']
        try:
            polling_interval = self.BLACS['exp_config'].getfloat('BLACS/plugins', 'connection_table.polling_interval')
        except labconfig.NoOptionError:
            polling_interval = 1
        logger.info('Using hashable_types: {}; polling_interval: {}'.format(hashable_types, polling_interval))
        
        # append the list of globals
        file_list += self.BLACS['settings'].get_value(Setting,'globals_list')
        # iterate over list, split folders off from files!
        calibration_list = self.BLACS['settings'].get_value(Setting,'calibrations_list')
        for path in calibration_list:
            if os.path.isdir(path):
                folder_list.append(path)
            else:
                file_list.append(path)
        
        # stop watching if we already were
        if self.filewatcher is not None:
            self.filewatcher.stop()
            # Should only be calling this with modified_info not None once at startup:
            assert clean_modified_info is None
            clean_modified_info = self.filewatcher.get_clean_modified_info()
            
        # Start the file watching!
        self.filewatcher = FileWatcher(
            self.callback,
            file_list,
            folder_list,
            clean_modified_info=clean_modified_info,
            hashable_types=hashable_types,
            interval=polling_interval,
        )

    def get_save_data(self):
        if self.clean_modified_info is not None:
            # We are doing a restart after a recompilation - return the modified info
            # that was just saved:
            return {'clean_modified_info': self.clean_modified_info}
        else:
            return {'clean_modified_info': self.filewatcher.get_clean_modified_info()}

    def on_restart(self):
        # Connection table has been sucessfully recompiled, we are restarting. This is
        # the only point, other than when they are first added for watching, that we
        # replace the 'clean' modified info of the files with their current modified
        # info. Since we just recompiled, the current state is the clean state
        self.filewatcher.stop()
        self.clean_modified_info = self.filewatcher.get_modified_info()
        self.filewatcher = None
        # Hide the notification
        self._close()

    def close(self):
        if self.filewatcher is not None:
            self.filewatcher.stop()
    
class Setting(object):
    name = name

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        self.stores_list = ['globals','calibrations']
        
        for store in self.stores_list:
            if '%s_list'%store not in self.data:
                self.data['%s_list'%store] = []
                
            #set the default sort order if it wasn't previousl saved
            if '%s_sort_order'%store not in self.data:
                self.data['%s_sort_order'%store] = 'ASC'
        
    # Create the page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'connection_table.ui'))
        
        # Create the models, get the views, and link them!!
        self.models = {}
        self.views = {}
        self.models['globals'] = QStandardItemModel()
        self.models['globals'].setHorizontalHeaderItem(FILEPATH_COLUMN, QStandardItem('Filepath'))
        self.views['globals'] = ui.h5_treeview
        self.views['globals'].setModel(self.models['globals'])
        
        self.models['calibrations'] = QStandardItemModel()
        self.models['calibrations'].setHorizontalHeaderItem(FILEPATH_COLUMN, QStandardItem('Filepath'))
        self.views['calibrations'] = ui.unit_conversion_treeview
        self.views['calibrations'].setModel(self.models['calibrations'])
        
        # Setup the buttons
        ui.add_h5_file.clicked.connect(self.add_global_file)
        ui.delete_h5_file.clicked.connect(self.delete_selected_globals_file)
        ui.add_unitconversion_file.clicked.connect(self.add_calibration_file)
        ui.add_unitconversion_folder.clicked.connect(self.add_calibration_folder)
        ui.delete_unitconversion.clicked.connect(self.delete_selected_conversion_file)
        
        # setup sort indicator changed signals
        self.views['globals'].header().sortIndicatorChanged.connect(self.global_sort_indicator_changed)
        self.views['calibrations'].header().sortIndicatorChanged.connect(self.calibrations_sort_indicator_changed)
        
        #iterate over the two listores
        for store in self.stores_list:
            # If we have saved data in the data store, then load it into the list store
            if '%s_list'%store in self.data:
                for path in self.data['%s_list'%store]:
                    self.models[store].appendRow(QStandardItem(path))
            # otherwise add an empty list to our data store, and leave the liststore empty
            else:
                self.data['%s_list'%store] = []
            
            self.views[store].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['%s_sort_order'%store]))
        
        return ui,None
    
    def global_sort_indicator_changed(self):
        if 'PySide' in sys.modules.copy():
            if self.views['globals'].header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
                order = 'ASC'
            else:
                order = 'DESC'
        else:
            if self.views['globals'].header().sortIndicatorOrder() == Qt.AscendingOrder:
                order = 'ASC'
            else:
                order = 'DESC'
        self.data['globals_sort_order'] = self.enum_to_order(self.views['globals'].header().sortIndicatorOrder())
        
    def calibrations_sort_indicator_changed(self):
        self.data['calibrations_sort_order'] = self.enum_to_order(self.views['calibrations'].header().sortIndicatorOrder())
    
    def order_to_enum(self, order):
        # if we are accidnetally passed an enum, just return it
        if order not in ['ASC', 'DESC']:
            return order
    
        if 'PySide' in sys.modules.copy():
            if order == 'ASC':
                enum = Qt.SortOrder.AscendingOrder
            else:
                enum = Qt.SortOrder.DescendingOrder
        else:
            if order == 'ASC':
                enum = Qt.AscendingOrder
            else:
                enum = Qt.DescendingOrder
        
        return enum
        
    def enum_to_order(self, enum):
        if 'PySide' in sys.modules.copy():
            if enum == Qt.SortOrder.AscendingOrder:
                order = 'ASC'
            else:
                order = 'DESC'
        else:
            if enum == Qt.AscendingOrder:
                order = 'ASC'
            else:
                order = 'DESC'
        
        return order
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        # transfer the contents of the list store into the data store, and then return the data store
        for store in self.stores_list:
            # clear the existing list
            self.data['%s_list'%store] = []
            for row_index in range(self.models[store].rowCount()):
                self.data['%s_list'%store].append(str(self.models[store].item(row_index).text()))
        
        return self.data
        
    def close(self):
        pass
        
    def add_global_file(self,*args,**kwargs):
        # create file chooser dialog
        dialog = QFileDialog(None,"select globals files", "C:\\", "HDF5 files (*.h5 *.hdf5)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            for filepath in selected_files:
                filepath = os.path.normpath(filepath)
                # Qt has this weird behaviour where if you type in the name of a file that exists
                # but does not have the extension you have limited the dialog to, the OK button is greyed out
                # but you can hit enter and the file will be selected. 
                # So we must check the extension of each file here!
                if filepath.endswith('.h5') or filepath.endswith('.hdf5'):
                    # make sure the path isn't already in the list
                    if not self.is_filepath_in_store(filepath, 'globals'):
                        self.models['globals'].appendRow(QStandardItem(filepath))
         
            self.views['globals'].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['globals_sort_order']))
            
        dialog.deleteLater()
            
    def is_filepath_in_store(self,filepath,store):
        for row_index in range(self.models[store].rowCount()):
            if str(filepath) == str(self.models[store].item(row_index).text()):
                return True
        return False
    
    def delete_selected_globals_file(self):
        index_list = self.views['globals'].selectedIndexes()
        while index_list:
            self.models['globals'].takeRow(index_list[0].row())
            index_list = self.views['globals'].selectedIndexes()
        
        self.views['globals'].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['globals_sort_order']))
            
    def add_calibration_file(self):
        # create file chooser dialog
        dialog = QFileDialog(None,"Select unit conversion scripts", "C:\\", "Python files (*.py *.pyw)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            for filepath in selected_files:
                filepath = os.path.normpath(filepath)
                # Qt has this weird behaviour where if you type in the name of a file that exists
                # but does not have the extension you have limited the dialog to, the OK button is greyed out
                # but you can hit enter and the file will be selected. 
                # So we must check the extension of each file here!
                if filepath.endswith('.py') or filepath.endswith('.pyw'):
                    # make sure the path isn't already in the list
                    if not self.is_filepath_in_store(filepath,'calibrations'):
                        self.models['calibrations'].appendRow(QStandardItem(filepath))
         
            self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['calibrations_sort_order']))
        
        dialog.deleteLater()
        
    def add_calibration_folder(self):
        # create file chooser dialog
        dialog = QFileDialog(None,"Select unit conversion folder", "C:\\", "")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.Directory)
        
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            for filepath in selected_files:
                filepath = os.path.normpath(filepath)
                # make sure the path isn't already in the list
                if not self.is_filepath_in_store(filepath,'calibrations'):
                    self.models['calibrations'].appendRow(QStandardItem(filepath))
         
            self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['calibrations_sort_order']))
        
        dialog.deleteLater()
    
    def delete_selected_conversion_file(self):
        index_list = self.views['calibrations'].selectedIndexes()
        while index_list:
            self.models['calibrations'].takeRow(index_list[0].row())
            index_list = self.views['calibrations'].selectedIndexes()
        
        self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.order_to_enum(self.data['calibrations_sort_order']))
