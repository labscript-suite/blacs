
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import cgi
import ctypes
import logging, logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time

# Must be in this order
import h5_lock
import h5py

from PySide.QtCore import *
from PySide.QtGui import *
from PySide.QtUiTools import QUiLoader

# Connection Table Code
from connections import ConnectionTable
#Draggable Tab Widget Code
from qtutils.widgets.dragdroptab import DragDropTabWidget
# Custom Excepthook
import excepthook
# Lab config code
from LabConfig import LabConfig, config_prefix
# Qt utils for running functions in the main thread
from qtutils import *
# Queue Manager Code
from queue import QueueManager
# Hardware Interface Imports
from hardware_interfaces import *
for device in device_list:    
    exec("from hardware_interfaces."+device+" import "+device)
# Save/restore frontpanel code
from front_panel_settings import FrontPanelSettings
# Preferences system
from settings import Settings
#import settings_pages
import plugins
#compile and restart
from compile_and_restart import CompileAndRestart

def setup_logging():
    logger = logging.getLogger('BLACS')
    handler = logging.handlers.RotatingFileHandler(r'BLACS.log', maxBytes=1024*1024*50)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if sys.stdout.isatty():
        terminalhandler = logging.StreamHandler(sys.stdout)
        terminalhandler.setFormatter(formatter)
        terminalhandler.setLevel(logging.INFO) # only display info or higher in the terminal
        logger.addHandler(terminalhandler)
    else:
        # Prevent bug on windows where writing to stdout without a command
        # window causes a crash:
        sys.stdout = sys.stderr = open(os.devnull,'w')
    logger.setLevel(logging.DEBUG)
    return logger
    
logger = setup_logging()
excepthook.set_logger(logger)

class BLACSWindow(QMainWindow):
    def __init__(self, blacs, parent=None):
        QMainWindow.__init__(self, parent)
        self.ui = loadUi('main.ui', self)
        self.blacs = blacs
        
    def closeEvent(self, event):
        #print 'aaaaa'
        if self.blacs.exit_complete:
            event.accept()
            if self.blacs.relaunch:
                logger.info('relaunching BLACS after quit')
                subprocess.Popen([sys.executable] + sys.argv)
        else:
            event.ignore()
            logger.info('destroy called')
            if not self.blacs.exiting:
                self.blacs.exiting = True
                #self.manager_running = False
                #self.filewatcher.stop()
                #self.settings.close()
                #self.notifications.close_all()
                
                inmain_later(self.blacs.on_save_exit)
                
            QTimer.singleShot(100,self.close)
        
class BLACS(object):

    tab_widget_ids = 7
    
    def __init__(self,application):
        self.qt_application = application
        #self.qt_application.aboutToQuit.connect(self.destroy)
        self.relaunch = False
        self.exiting = False
        self.exit_complete = False
        
        self.ui = BLACSWindow(self).ui
        self.tab_widgets = {}
        self.exp_config = exp_config # Global variable
        self.settings_path = settings_path # Global variable
        self.connection_table = connection_table # Global variable
        self.connection_table_h5file = self.exp_config.get('paths','connection_table_h5')
        self.connection_table_labscript = self.exp_config.get('paths','connection_table_py')
                
        # Setup the UI
        self.ui.main_splitter.setStretchFactor(0,0)
        self.ui.main_splitter.setStretchFactor(1,1)
        
        self.tablist = {}
        self.panes = {}
        self.settings_dict = {}
        # Instantiate Devices from Connection Table, Place in Array        
        self.attached_devices = self.connection_table.find_devices(device_list)
        
        # Store the panes in a dictionary for easy access
        self.panes['tab_top_vertical_splitter'] = self.ui.tab_top_vertical_splitter
        self.panes['tab_bottom_vertical_splitter'] = self.ui.tab_bottom_vertical_splitter
        self.panes['tab_horizontal_splitter'] = self.ui.tab_horizontal_splitter
        self.panes['main_splitter'] = self.ui.main_splitter
                
        # Get settings to restore 
        self.front_panel_settings = FrontPanelSettings(self.settings_path, self.connection_table)
        self.front_panel_settings.setup(self)
        settings,question,error,tab_data = self.front_panel_settings.restore()
            
        # TODO: handle question/error cases
        
        self.restore_window(tab_data)
        
        #splash.update_text('Creating the device tabs...')
        # Create the notebooks
        for i in range(4):
            self.tab_widgets[i] = DragDropTabWidget(self.tab_widget_ids)
            getattr(self.ui,'tab_container_%d'%i).addWidget(self.tab_widgets[i])
        
        for device_name,device_class in self.attached_devices.items():
            self.settings_dict.setdefault(device_name,{"device_name":device_name})
            # add common keys to settings:
            self.settings_dict[device_name]["connection_table"] = self.connection_table
            self.settings_dict[device_name]["front_panel_settings"] = settings[device_name] if device_name in settings else {}
            self.settings_dict[device_name]["saved_data"] = tab_data[device_name]['data'] if device_name in tab_data else {}            
            # Instantiate the device            
            self.tablist[device_name] = globals()[device_class](self.tab_widgets[0],self.settings_dict[device_name])
        
        self.order_tabs(tab_data)
        
                    
        # Setup the QueueManager
        self.queue = QueueManager(self.ui)
        
        # setup the plugin system
        settings_pages = []
        self.plugins = {}
        for module_name in plugins.__plugins__:
            try:
                # instantiate the plugin
                self.plugins[module_name] = plugins.__getattribute__(module_name).Plugin()                
                settings_pages.extend(self.plugins[module_name].get_settings())
            except Exception as e:
                logger.error('Plugin %s only partially instantiated. Error was: %s'%(module_name,str(e)))
        
        # setup the BLACS preferences system
        self.settings = Settings(file=self.settings_path,
                                     parent = self.ui,
                                     page_classes=settings_pages)
                                     #[plugins.connection_table.Setting,
                                     #              plugins.general.Setting])
        #self.settings.register_callback(self.on_settings_changed)
            
        
        
        # Connect menu actions
        self.ui.actionOpenPreferences.triggered.connect(self.on_open_preferences)
        self.ui.actionSelect_Globals.triggered.connect(self.on_select_globals)
        self.ui.actionEdit_Connection_Table.triggered.connect(self.on_edit_connection_table)
        self.ui.actionRecompile.triggered.connect(self.on_recompile_connection_table)
        self.ui.actionSave.triggered.connect(self.on_save_front_panel)
        self.ui.actionOpen.triggered.connect(self.on_load_front_panel)
        
        
        self.ui.show()
    
    def restore_window(self,tab_data):
        # read out position settings:
        try:
            # There are some dodgy hacks going on here to try and restore the window position correctly
            # Unfortunately Qt has two ways of measuring teh window position, one with the frame/titlebar
            # and one without. If you use the one that measures including the titlebar, you don't
            # know what the window size was when the window was UNmaximized.
            #
            # Anyway, no idea if this works cross platform (tested on windows 8)
            # Feel free to rewrite this, along with the code in front_panel_settings.py
            # which stores the values
            #
            # Actually this is a waste of time because if you close when maximized, reoopen and then 
            # de-maximize, the window moves to a random position (not the position it was at before maximizing)
            # so bleh!
            self.ui.move(tab_data['BLACS settings']["window_xpos"]-tab_data['BLACS settings']['window_frame_width']/2,tab_data['BLACS settings']["window_ypos"]-tab_data['BLACS settings']['window_frame_height']+tab_data['BLACS settings']['window_frame_width']/2)
            self.ui.resize(tab_data['BLACS settings']["window_width"],tab_data['BLACS settings']["window_height"])
            
            if 'window_maximized' in tab_data['BLACS settings'] and tab_data['BLACS settings']['window_maximized']:
                self.ui.showMaximized()
            
            for pane_name,pane in self.panes.items():
                pane.setSizes(tab_data['BLACS settings'][pane_name])
                    
        except Exception as e:
            logger.warning("Unable to load window and notebook defaults. Exception:"+str(e))
    
    def order_tabs(self,tab_data):
        # Move the tabs to the correct notebook
        for device_name,device_class in self.attached_devices.items():
            notebook_num = 0
            if device_name in tab_data:
                notebook_num = int(tab_data[device_name]["notebook"])
                if notebook_num not in self.tab_widgets: 
                    notebook_num = 0
                    
            #Find the notebook the tab is in, and remove it:
            for notebook in self.tab_widgets.values():
                tab_index = notebook.indexOf(self.tablist[device_name]._ui)
                if tab_index != -1:
                    notebook.removeTab(tab_index)
                    self.tab_widgets[notebook_num].addTab(self.tablist[device_name]._ui,device_name)
                    break
        
        # splash.update_text('restoring tab positions...')
        # # Now that all the pages are created, reorder them!
        for device_name,device_class in self.attached_devices.items():
            if device_name in tab_data:
                notebook_num = int(tab_data[device_name]["notebook"])
                if notebook_num in self.tab_widgets:  
                    self.tab_widgets[notebook_num].tab_bar.moveTab(self.tab_widgets[notebook_num].indexOf(self.tablist[device_name]._ui),int(tab_data[device_name]["page"]))
        
        # # Now that they are in the correct order, set the correct one visible
        for device_name,device_data in tab_data.items():
            if device_name == 'BLACS settings':
                continue
            # if the notebook still exists and we are on the entry that is visible
            if bool(device_data["visible"]) and int(device_data["notebook"]) in self.tab_widgets:
                self.tab_widgets[int(device_data["notebook"])].tab_bar.setCurrentIndex(int(device_data["page"]))
    
    def update_all_tab_settings(self,settings,tab_data):
        for device_name,tab in self.tablist.items():
            self.settings_dict[device_name]["front_panel_settings"] = settings[device_name] if device_name in settings else {}
            self.settings_dict[device_name]["saved_data"] = tab_data[device_name]['data'] if device_name in tab_data else {}            
            tab.update_from_settings(self.settings_dict[device_name])
                    
        
    def on_load_front_panel(self,*args,**kwargs):
        # get the file:
        # create file chooser dialog
        dialog = QFileDialog(None,"Select file to load", self.exp_config.get('paths','experiment_shot_storage'), "HDF5 files (*.h5 *.hdf5)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.ExistingFile)
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            filepath = str(selected_files[0])
            # Qt has this weird behaviour where if you type in the name of a file that exists
            # but does not have the extension you have limited the dialog to, the OK button is greyed out
            # but you can hit enter and the file will be selected. 
            # So we must check the extension of each file here!
            if filepath.endswith('.h5') or filepath.endswith('.hdf5'):
                try:
                    # TODO: Warn that this will restore values, but not channels that are locked
                    message = QMessageBox()
                    message.setText("Warning: This will modify front panel values and cause device output values to update.\nNote: Channels that are locked will not be updated.\n\nDo you wish to continue?")
                    message.setIcon(QMessageBox.Warning)
                    message.setWindowTitle("BLACS")
                    message.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
                   
                    if message.exec_() == QMessageBox.Yes:                
                        front_panel_settings = FrontPanelSettings(filepath, self.connection_table)
                        settings,question,error,tab_data = front_panel_settings.restore()
                        #TODO: handle question/error
                        
                        # Restore window data
                        self.restore_window(tab_data)
                        self.order_tabs(tab_data)                   
                        self.update_all_tab_settings(settings,tab_data)
                except Exception as e:
                    logger.warning("Unable to load the front panel in %s. Exception:%s"%(filepath,str(e)))
                    message = QMessageBox()
                    message.setText("Unable to load the front panel. The error encountered is printed below.\n\n%s"%str(e))
                    message.setIcon(QMessageBox.Information)
                    message.setWindowTitle("BLACS")
                    message.exec_() 
            else:
                message = QMessageBox()
                message.setText("You did not select a file ending with .h5 or .hdf5. Please try again")
                message.setIcon(QMessageBox.Information)
                message.setWindowTitle("BLACS")
                message.exec_()
                QTimer.singleShot(10,self.on_load_front_panel)
    
    def on_save_exit(self):
        # Save front panel
        data = self.front_panel_settings.get_save_data()
       
        with h5py.File(self.settings_path,'r+') as h5file:
           if 'connection table' in h5file:
               del h5file['connection table']
        
        self.front_panel_settings.save_front_panel_to_h5(self.settings_path,data[0],data[1],data[2],{"overwrite":True})
        logger.info('Destroying tabs')
        for tab in self.tablist.values():
            tab.destroy()            
            
        #gobject.timeout_add(100,self.finalise_quit,time.time())
        QTimer.singleShot(100,lambda: self.finalise_quit(time.time()))
    
    def finalise_quit(self,initial_time):
        logger.info('finalise_quit called')
        tab_close_timeout = 2
        # Kill any tabs which didn't close themselves:
        for name, tab in self.tablist.items():
            if tab.destroy_complete:
                del self.tablist[name]
        if self.tablist:
            for name, tab in self.tablist.items():
                # If a tab has a fatal error or is taking too long to close, force close it:
                if (time.time() - initial_time > tab_close_timeout) or tab.state == 'fatal error':
                    try:
                        tab.close_tab() 
                    except Exception as e:
                        logger.error('Couldn\'t close tab:\n%s'%str(e))
                    del self.tablist[name]
        if self.tablist:
            QTimer.singleShot(100,lambda: self.finalise_quit(initial_time))
        else:
            self.exit_complete = True
            logger.info('quitting')
            #self.window.hide()
            #gtk.main_quit()
            #return False
    
    
    def on_recompile_connection_table(self,*args,**kwargs):
        logger.info('recompile connection table called')
        # get list of globals
        globals_files = self.settings.get_value(plugins.connection_table.Setting,'globals_list')
        # Remove unicode encoding so that zlock doesn't crash
        for i in range(len(globals_files)):
            globals_files[i] = str(globals_files[i])
        CompileAndRestart(self,globals_files,self.connection_table_labscript, self.connection_table_h5file)
     
    def on_save_front_panel(self,*args,**kwargs):
        data = self.front_panel_settings.get_save_data()
    
        # Open save As dialog
        dialog = QFileDialog(None,"Save BLACS state", self.exp_config.get('paths','experiment_shot_storage'), "HDF5 files (*.h5)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        
        if dialog.exec_():
            current_file = str(dialog.selectedFiles()[0])
            if not current_file.endswith('.h5'):
                current_file += '.h5'
            self.front_panel_settings.save_front_panel_to_h5(current_file,data[0],data[1],data[2])
        
                
            
        
    
    #########################
    # Preferences functions #
    #########################
    def on_open_preferences(self,*args,**kwargs):
        self.settings.create_dialog()
        
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
            
                

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        length = int(self.headers.getheader('content-length'))
        postvars = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
        h5_filepath =  postvars['filepath'][0]
        
        # This function runs in the Qt Main thread (see decorator above function definition)
        message = self.process(h5_filepath)
        
        logger.info('Request handler: %s ' % message.strip())
        self.wfile.write(message)
        self.wfile.close() 
    
    @inmain_decorator(wait_for_return=True)
    def process(self,h5_filepath):
        # Convert path to local slashes and shared drive prefix:
        shared_drive_prefix = app.exp_config.get('paths','shared_drive')     
        h5_filepath = h5_filepath.replace('\\', os.path.sep).replace('Z:', shared_drive_prefix)
        logger.info('local filepath: %s'%h5_filepath)
        return process_request(h5_filepath)
        
def new_rep_name(h5_filepath):
    basename = os.path.basename(h5_filepath).split('.h5')[0]
    if '_rep' in basename:
        reps = int(basename.split('_rep')[1])
        return h5_filepath.split('_rep')[-2] + '_rep%05d.h5'% (int(reps) + 1)
    return h5_filepath.split('.h5')[0] + '_rep%05d.h5'%1
        
def process_request(h5_filepath):
    # check connection table
    try:
        new_conn = ConnectionTable(h5_filepath)
    except:
        raise
        return "H5 file not accessible to Control PC\n"
    result,error = app.connection_table.compare_to(new_conn)
    if result:
        # Has this run file been run already?
        with h5py.File(h5_filepath) as h5_file:
            if 'data' in h5_file['/']:
                rerun = True
            else:
                rerun = False
        if rerun or app.queue.is_in_queue(h5_filepath):
            logger.debug('Run file has already been run! Creating a fresh copy to rerun')
            new_h5_filepath = new_rep_name(h5_filepath)
            # Keep counting up until we get a filename that isn't in the filesystem:
            while os.path.exists(new_h5_filepath):
                new_h5_filepath = new_rep_name(new_h5_filepath)
            success = app.queue.clean_h5_file(h5_filepath, new_h5_filepath)
            if not success:
               return 'Cannot create a re run of this experiment. Is it a valid run file?'
            app.queue.append([new_h5_filepath])
            message = "Experiment added successfully: experiment to be re-run\n"
        else:
            app.queue.append([h5_filepath])
            message = "Experiment added successfully\n"
        if app.queue.manager_paused:
            message += "Warning: Queue is currently paused\n"
        if not app.queue.manager_running:
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

 
if __name__ == '__main__':
    config_path = os.path.join(config_prefix,'%s.ini'%socket.gethostname())
    settings_path = os.path.join(config_prefix,'%s_BLACS.h5'%socket.gethostname())
    required_config_params = {"DEFAULT":["experiment_name"],
                              "programs":["text_editor",
                                          "text_editor_arguments",
                                         ],
                              "paths":["shared_drive",
                                       "connection_table_h5",
                                       "connection_table_py",                                       
                                      ],
                              "ports":["BLACS"],
                             }
    exp_config = LabConfig(config_path,required_config_params)        
    
    port = int(exp_config.get('ports','BLACS'))
    myappid = 'monashbec.BLACS' # arbitrary string
    if os.name == 'nt': # please leave this in so I can test in linux!
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    http_server = HTTPServer(('', port),RequestHandler)
    serverthread = threading.Thread(target = http_server.serve_forever)
    serverthread.daemon = True
    serverthread.start()

    # Create Connection Table object
    try:
        connection_table = ConnectionTable(exp_config.get('paths','connection_table_h5'))
    except:
        # dialog = gtk.MessageDialog(None,gtk.DIALOG_MODAL,gtk.MESSAGE_ERROR,gtk.BUTTONS_NONE,"The connection table in '%s' is not valid. Please check the compilation of the connection table for errors\n\n"%self.connection_table_h5file)
             
        # dialog.run()
        # dialog.destroy()
        sys.exit("Invalid Connection Table")
        
    
    qapplication = QApplication(sys.argv)
    app = BLACS(qapplication)
    
    def execute_program():
        qapplication.exec_()
        
        http_server.shutdown()
        http_server.server_close()
        http_server.socket.close()
    
    sys.exit(execute_program())