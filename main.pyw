
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import cgi
import ctypes
import logging, logging.handlers
import os
import socket
import sys
import threading

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

class BLACS(object):

    tab_widget_ids = 7
    
    def __init__(self):
        self.ui = QUiLoader().load('main.ui')
        self.tab_widgets = {}
        self.exp_config = exp_config # Global variable
        self.settings_path = settings_path # Global variable
        self.connection_table = connection_table # Global variable
        self.connection_table_h5file = self.exp_config.get('paths','connection_table_h5')
        self.connection_table_labscript = self.exp_config.get('paths','connection_table_py')
        
     
        
        # Instantiate Devices from Connection Table, Place in Array        
        self.attached_devices = self.connection_table.find_devices(device_list)
        self.settings_dict = {}
        
        # Get settings to restore 
        self.front_panel_settings = FrontPanelSettings(self.settings_path, self.connection_table)
        settings,question,error,tab_data = self.front_panel_settings.restore()
            
        # TODO: handle question/error cases
        
        # read out position settings:
        # try:
            # self.window.move(tab_data['BLACS settings']["window_xpos"],tab_data['BLACS settings']["window_ypos"])
            # self.window.resize(tab_data['BLACS settings']["window_width"],tab_data['BLACS settings']["window_height"])
            
            # for pane_name,pane in self.panes.items():
                # pane.set_position(tab_data['BLACS settings'][pane_name])
                    
        # except Exception as e:
            # logger.warning("Unable to load window and notebook defaults. Exception:"+str(e))
        
        #splash.update_text('Creating the device tabs...')
        self.tablist = {}
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
                        
            # Select the notebook to add the device to
            notebook_num = 0
            if device_name in tab_data:
                notebook_num = int(tab_data[device_name]["notebook"])
                if notebook_num not in self.tab_widgets: 
                    notebook_num = 0
            #splash.update_text('Creating the device tabs...'+device_name+'...')
            # Instantiate the device            
            self.tablist[device_name] = globals()[device_class](self.tab_widgets[notebook_num],self.settings_dict[device_name])
        
        # splash.update_text('restoring tab positions...')
        # # Now that all the pages are created, reorder them!
        # for device_name,device_class in self.attached_devices.items():
            # if device_name in tab_data:
                # notebook_num = tab_data[device_name]["notebook"]
                # if notebook_num in self.notebook:                                        
                    # self.notebook[notebook_num].reorder_child(self.tablist[device_name]._toplevel,tab_data[device_name]["page"])
                
        # # Now that they are in the correct order, set the correct one visible
        # for device_name,device_data in tab_data.items():
            # if device_name == 'BLACS settings':
                # continue
            # # if the notebook still exists and we are on the entry that is visible
            # if device_data["visible"] and device_data["notebook"] in self.notebook:
                # self.notebook[device_data["notebook"]].set_current_page(device_data["page"])
            
        
        # for i in range(4):
            # self.tab_widgets.append(DragDropTabWidget(self.tab_widget_ids))
            # self.tab_widgets[i].addTab(QLabel("tab %d"%i),"tab %d"%i)
            # getattr(self.ui,'tab_container_%d'%i).addWidget(self.tab_widgets[i])
        
        # Setup the QueueManager
        self.queue = QueueManager(self.ui)
            
        self.ui.show()
        
        

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
    app = BLACS()
    
    def execute_program():
        qapplication.exec_()
        
        http_server.shutdown()
        http_server.server_close()
        http_server.socket.close()
    
    sys.exit(execute_program())