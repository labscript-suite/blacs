import os
from PySide.QtCore import *
from PySide.QtGui import *
from PySide.QtUiTools import QUiLoader
FILEPATH_COLUMN = 0

class Plugin(object):
    def __init__(self):
        pass
        
    def get_menus(self):
        return [Menu]
        
    def get_notifications(self):
        return [Notification]
        
    def get_settings(self):
        return [Setting]
        
    def register_callbacks(self):
        pass

class Menu(object):
    def __init__(self,BLACS):
        pass
        
    def get_menu_items(Self):
        return {'Connection Table':{'Edit':self.on_edit_connection_table}}
    
    def on_select_globals(self,*args,**kwargs):
        self.settings.create_dialog(goto_page=plugins.connection_table.Setting)
      
    def on_edit_connection_table(self,*args,**kwargs):
        # get path to text editor
        editor_path = self.exp_config.get('programs','text_editor')
        editor_args = self.exp_config.get('programs','text_editor_arguments')
        if editor_path:  
            if '{file}' in editor_args:
                editor_args = editor_args.replace('{file}', self.exp_config.get('paths','connection_table_py'))
            else:
                editor_args = self.exp_config.get('paths','connection_table_py') + " " + editor_args            
            try:
                subprocess.Popen([editor_path,editor_args])
            except Exception:
                QMessageBox.information(self.ui,"Error","Unable to launch text editor. Check the path is valid in the experiment config file (%s) (you must restart BLACS if you edit this file)"%self.exp_config.config_path)
        else:
            QMessageBox.information(self.ui,"Error","No text editor path was specified in the experiment config file (%s) (you must restart BLACS if you edit this file)"%self.exp_config.config_path)
    
    
# class Notification(object):
    # pass
    
class Setting(object):
    name = "Connection Table"

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        self.stores_list = ['globals','calibrations']
        
        for store in self.stores_list:
            if '%s_list'%store not in self.data:
                self.data['%s_list'%store] = []
                
            #set the default sort order if it wasn't previousl saved
            if '%s_sort_order'%store not in self.data:
                self.data['%s_sort_order'%store] = Qt.AscendingOrder
        
    # Create the page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        ui = QUiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'connection_table.ui'))
        
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
        
            self.views[store].sortByColumn(FILEPATH_COLUMN,self.data['%s_sort_order'%store])
        
        return ui,None
    
    def global_sort_indicator_changed(self):
        self.data['globals_sort_order'] = self.views['globals'].header().sortIndicatorOrder()
        
    def calibrations_sort_indicator_changed(self):
        self.data['calibrations_sort_order'] = self.views['calibrations'].header().sortIndicatorOrder()
    
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
                self.data['%s_list'%store].append(self.models[store].item(row_index).text())        
        
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
                # Qt has this weird behaviour where if you type in the name of a file that exists
                # but does not have the extension you have limited the dialog to, the OK button is greyed out
                # but you can hit enter and the file will be selected. 
                # So we must check the extension of each file here!
                if filepath.endswith('.h5') or filepath.endswith('.hdf5'):
                    # make sure the path isn't already in the list
                    if not self.is_filepath_in_store(filepath,'globals'):
                        self.models['globals'].appendRow(QStandardItem(filepath))
         
            self.views['globals'].sortByColumn(FILEPATH_COLUMN,self.data['globals_sort_order'])
            
    def is_filepath_in_store(self,filepath,store):
        for row_index in range(self.models[store].rowCount()):
            if filepath == self.models[store].item(row_index).text():
                return True
        return False
    
    def delete_selected_globals_file(self):
        index_list = self.views['globals'].selectedIndexes()
        while index_list:
            self.models['globals'].takeRow(index_list[0].row())
            index_list = self.views['globals'].selectedIndexes()
        
        self.views['globals'].sortByColumn(FILEPATH_COLUMN,self.data['globals_sort_order'])
            
    def add_calibration_file(self):
        # create file chooser dialog
        dialog = QFileDialog(None,"Select unit conversion scripts", "C:\\", "Python files (*.py *.pyw)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            for filepath in selected_files:
                # Qt has this weird behaviour where if you type in the name of a file that exists
                # but does not have the extension you have limited the dialog to, the OK button is greyed out
                # but you can hit enter and the file will be selected. 
                # So we must check the extension of each file here!
                if filepath.endswith('.py') or filepath.endswith('.pyw'):
                    # make sure the path isn't already in the list
                    if not self.is_filepath_in_store(filepath,'calibrations'):
                        self.models['calibrations'].appendRow(QStandardItem(filepath))
         
            self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.data['calibrations_sort_order'])
        
    def add_calibration_folder(self):
        # create file chooser dialog
        dialog = QFileDialog(None,"Select unit conversion folder", "C:\\", "")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.Directory)
        
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            for filepath in selected_files:
                # make sure the path isn't already in the list
                if not self.is_filepath_in_store(filepath,'calibrations'):
                    self.models['calibrations'].appendRow(QStandardItem(filepath))
         
            self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.data['calibrations_sort_order'])
        
    
    def delete_selected_conversion_file(self):
        index_list = self.views['calibrations'].selectedIndexes()
        while index_list:
            self.models['calibrations'].takeRow(index_list[0].row())
            index_list = self.views['calibrations'].selectedIndexes()
        
        self.views['calibrations'].sortByColumn(FILEPATH_COLUMN,self.data['calibrations_sort_order'])