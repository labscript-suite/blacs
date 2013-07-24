import sys
if __name__ == "__main__":
    from splash_screen import SplashWindow
    splash = SplashWindow('BLACS.png',(500,500),(70,450))
    
    splash.update_text('Importing logging...')

import logging, logging.handlers
from setup_logging import setup_logging
import excepthook
import os
from subprocess import Popen

#
# Note, Throughout this file we put things we don't want imported in the Worker Processes, inside a "if __name__ == "__main__":"
# Otherwise we import a bunch of stuff we don't need into the child processes! This is due to the way processes are spawned on windows. 
#
if __name__ == "__main__":
    
    splash.update_text('Importing standard libraries...')
    import threading
    import cgi
    import time
    import socket
    import Queue    
    import ctypes

    splash.update_text('Importing gtk/numpy/h5py...')
    import gtk
    import gobject
    import numpy
    import h5_lock, h5py
    
    splash.update_text('Importing pythonlib modules')
    from subproc_utils import zmq_get, ZMQServer
    from settings import Settings
    import settings_pages
    from filewatcher import FileWatcher
    from compile_and_restart import CompileAndRestart
    # Connection Table Code
    from connections import ConnectionTable
    
    # Save/restore frontpanel code
    from front_panel_settings import FrontPanelSettings
    
    # Notification code
    from notifications import Notifications
    
    # Lab config code
    from LabConfig import LabConfig, config_prefix

if __name__ == "__main__":
    splash.update_text('Setting up logging...')
logger = setup_logging()
excepthook.set_logger(logger)
if __name__ == "__main__":
    logger.info('\n\n===============starting===============\n')
    
    splash.update_text('Importing device classes...')
# Hardware Interface Imports
from hardware_interfaces import *
for device in device_list:    
    exec("from hardware_interfaces."+device+" import "+device)

if __name__ == "__main__":
    # Virtual Devices Import
    #needs to be dynamic import
    splash.update_text('Importing virtual device classes...')
    from virtual_devices.shutter import *

    splash.update_text('Importing matplotlib...')
    # Temporary imports to demonstrate plotting
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D
    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas


    class BLACS(object):       
        def __init__(self,exp_config,settings_path,splash):
            self.exiting = False
            
            self.exp_config = exp_config
            self.settings_path = settings_path
            self.front_panel_settings = FrontPanelSettings()
            #self.settings_path = os.path.join("connectiontables", socket.gethostname()+"_settings.h5")
            
            splash.update_text('creating settings h5 file...')
            # Create the settings h5 file if it doesn't exist!
            with h5py.File(self.settings_path,'a') as h5file:
                pass
            
            splash.update_text('Creating BLACS interface...')
            self.builder = gtk.Builder()
            self.builder.add_from_file('main_interface.glade')
            self.builder.connect_signals(self)
            self.window = self.builder.get_object("window")
            self.mainbox = self.builder.get_object("main_box")
            self.notifications = Notifications(self)
            
            self.notebook = {}
            self.notebook["1"] = self.builder.get_object("notebook1")
            self.notebook["2"] = self.builder.get_object("notebook2")
            self.notebook["3"] = self.builder.get_object("notebook3")
            self.notebook["4"] = self.builder.get_object("notebook4")
            
            self.panes = {}
            self.panes["hpaned1"] = self.builder.get_object("hpaned1")
            self.panes["hpaned2"] = self.builder.get_object("hpaned2")
            self.panes["hpaned3"] = self.builder.get_object("hpaned3")
            self.panes["vpaned1"] = self.builder.get_object("vpaned1")
            
            self.queue = self.builder.get_object("remote_liststore")
            self.listwidget = self.builder.get_object("treeview1")
            self.status_bar = self.builder.get_object("status_label")
            self.queue_pause_button = self.builder.get_object("Queue_Pause")
            self.now_running = self.builder.get_object('label_now_running')
            self.analysis_container = self.builder.get_object('analysis_submission_container')
 
            treeselection = self.listwidget.get_selection()
            treeselection.set_mode(gtk.SELECTION_MULTIPLE)
            
            # Set group ID's of notebooks to be the same
            for notebook_number, notebook in self.notebook.items():
                notebook.set_group_id(1323)
            
            # Need to connect signals!
            self.builder.connect_signals(self)
            
            # Set the icon!
            self.window.set_icon_from_file(os.path.join('BLACS.svg'))
            
            #
            # Load Connection Table
            #
            splash.update_text('Loading connection table...')
            # Get file paths (used for file watching later)           
            self.connection_table_h5file = self.exp_config.get('paths','connection_table_h5')
            self.connection_table_labscript = self.exp_config.get('paths','connection_table_py')
            
            # Create Connection Table object
            try:
                self.connection_table = ConnectionTable(self.connection_table_h5file)
            except:
                dialog = gtk.MessageDialog(None,gtk.DIALOG_MODAL,gtk.MESSAGE_ERROR,gtk.BUTTONS_NONE,"The connection table in '%s' is not valid. Please check the compilation of the connection table for errors\n\n"%self.connection_table_h5file)
                     
                dialog.run()
                dialog.destroy()
                sys.exit("Invalid Connection Table")
                return
            
            # Get settings to restore
            splash.update_text('Loading device save data...')
            settings,question,error,tab_data = self.front_panel_settings.restore(self.settings_path,self.connection_table)
            
            # TODO: handle question/error cases
            
            # Instantiate Devices from Connection Table, Place in Array        
            self.attached_devices = self.connection_table.find_devices(device_list)
            self.master_pseudoclock = self.connection_table.master_pseudoclock
            
            self.settings_dict = {
                                  #"zaber_stages":{"device_name":"zaber_stages","COM":"com1"},
                                 }
            
            # read out position settings:
            try:
                self.window.move(tab_data['BLACS settings']["window_xpos"],tab_data['BLACS settings']["window_ypos"])
                self.window.resize(tab_data['BLACS settings']["window_width"],tab_data['BLACS settings']["window_height"])
                
                for pane_name,pane in self.panes.items():
                    pane.set_position(tab_data['BLACS settings'][pane_name])
                        
            except Exception as e:
                logger.warning("Unable to load window and notebook defaults. Exception:"+str(e))
            
            splash.update_text('Creating the device tabs...')
            self.tablist = {}
            for device_name,device_class in self.attached_devices.items():
                self.settings_dict.setdefault(device_name,{"device_name":device_name})
                # add common keys to settings:
                self.settings_dict[device_name]["connection_table"] = self.connection_table
                self.settings_dict[device_name]["front_panel_settings"] = settings[device_name] if device_name in settings else {}
                self.settings_dict[device_name]["saved_data"] = tab_data[device_name]['data'] if device_name in tab_data else {}
                
                # Select the notebook to add the device to
                notebook_num = "1"
                if device_name in tab_data:
                    notebook_num = tab_data[device_name]["notebook"]
                    if notebook_num not in self.notebook:        
                        notebook_num = "1"
                splash.update_text('Creating the device tabs...'+device_name+'...')
                # Instantiate the device        
                self.tablist[device_name] = globals()[device_class](self,self.notebook[notebook_num],self.settings_dict[device_name])
            
            splash.update_text('restoring tab positions...')
            # Now that all the pages are created, reorder them!
            for device_name,device_class in self.attached_devices.items():
                if device_name in tab_data:
                    notebook_num = tab_data[device_name]["notebook"]
                    if notebook_num in self.notebook:                                        
                        self.notebook[notebook_num].reorder_child(self.tablist[device_name]._toplevel,tab_data[device_name]["page"])
                    
            # Now that they are in the correct order, set the correct one visible
            for device_name,device_data in tab_data.items():
                if device_name == 'BLACS settings':
                    continue
                # if the notebook still exists and we are on the entry that is visible
                if device_data["visible"] and device_data["notebook"] in self.notebook:
                    self.notebook[device_data["notebook"]].set_current_page(device_data["page"])
            
            self.front_panel_settings.setup_settings(self)
            
            #TO DO:            
            # Open BLACS Config File
            # Load Virtual Devices
            

            #self.window.maximize()            
            #self.window.show()
            
            # Start Queue Manager
            splash.update_text('Starting the queue manager thread...')
            self.manager_running = True
            self.manager_paused = False
            self.manager_repeat = False
            self.manager = threading.Thread(target = self.manage)
            self.manager.daemon=True
            self.manager.start()
            
            # Start the analysis submission thread:
            splash.update_text('Starting the analysis submission thread...')
            self.analysis_queue = Queue.Queue()
            self.analysis_submission = AnalysisSubmission(self.analysis_container, self.analysis_queue,self.settings_path)
            
            
            # setup the BLACS preferences system
            splash.update_text('Setting up the BLACS settings...')
            self.settings = Settings(file=self.settings_path,
                                     parent = self.window,
                                     page_classes=[settings_pages.connection_table.ConnectionTable,
                                                   settings_pages.general.General])
            self.settings.register_callback(self.on_settings_changed)
            
            splash.update_text('Setting up connection table file watching...')
            self.filewatcher = None
            self.setup_folder_watching()
            
            
        def setup_folder_watching(self):                
            folder_list = []
            file_list = [self.connection_table_labscript, self.connection_table_h5file]
            
            # append the list of globals
            file_list += self.settings.get_value(settings_pages.connection_table.ConnectionTable,'globals_list')
            # iterate over list, split folders off from files!
            calibration_list = self.settings.get_value(settings_pages.connection_table.ConnectionTable,'calibrations_list')
            for path in calibration_list:
                if os.path.isdir(path):
                    folder_list.append(path)
                else:
                    file_list.append(path)
            
            # stop watching if we already were
            if self.filewatcher:
                self.filewatcher.stop()
            # Start the file watching!
            self.filewatcher = FileWatcher(self.on_file_change,file_list,folder_list)
            
        def on_file_change(self,filename,modified_time):
            self.notifications.show('recompile')
            
        def on_settings_changed(self):
            # update the filewatching code!
            self.setup_folder_watching()
                
        def on_open_preferences(self,widget):
            self.settings.create_dialog()
            
        def recompile_connection_table(self,widget):
            logger.info('recompile connection table called')
            # get list of globals
            globals_files = self.settings.get_value(settings_pages.connection_table.ConnectionTable,'globals_list')
            CompileAndRestart(self,globals_files,self.connection_table_labscript, self.connection_table_h5file)
            
        def update_plot(self,channel,data,rate):
            line = self.ax.get_lines()[0]
            #self.plot_data = numpy.append(self.plot_data[len(data[0,:]):],data[0,:])
            t = time.time()
            a = numpy.zeros(len(self.plot_data))
            a[0:len(self.plot_data)-len(data[0,:])] = self.plot_data[len(data[0,:]):]
            a[len(self.plot_data)-len(data[0,:]):] = data[0,:]
            self.plot_data = a
            line.set_ydata(self.plot_data)
            #self.ax.draw_artist(line)
            # just redraw the axes rectangle
            #self.canvas.blit(self.ax.bbox)
            #self.ax.plot(data[1,:],data[0,:])
            self.canvas.draw_idle()
        
        def on_open(self,widget):
            chooser = gtk.FileChooserDialog(title='Open',action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                           gtk.STOCK_OPEN,gtk.RESPONSE_OK))
            chooser.set_default_response(gtk.RESPONSE_OK)
            # TODO, change over to labconfig path
            chooser.set_current_folder(r'Z:\\Experiments')
            chooser.set_select_multiple(True)
            response = chooser.run()
            if response == gtk.RESPONSE_OK:
                filename = chooser.get_filenames()
                for f in filename:                
                    result = process_request(f)
            else:
                chooser.destroy()
                return
            chooser.destroy()
            # TODO: update this so that it handles multiple file selections properly
            if not 'added successfully' in result:
                message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_OK, result) 
                message.run()  
                message.destroy()
            logger.info('Open file:\n%s ' % result)
            
        def on_save_front_panel(self,widget):
            data = self.front_panel_settings.get_save_data()
        
            # Open save As dialog
            chooser = gtk.FileChooserDialog(title='Save Front Panel',action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                            buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                            gtk.STOCK_SAVE,gtk.RESPONSE_OK))
            chooser.set_default_response(gtk.RESPONSE_OK)

            #chooser.set_do_overwrite_confirmation(True)
            chooser.set_current_folder_uri(r'Z:\Experiments\Front Panels')
            chooser.set_current_name('a_meaningful_name.h5')
            response = chooser.run()
            if response == gtk.RESPONSE_OK:
                current_file = chooser.get_filename()
                chooser.destroy()
            else:
                chooser.destroy()
                return
                    
            self.front_panel_settings.save_front_panel_to_h5(current_file,data[0],data[1],data[2])    
            
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
                raise
                logger.error('Clean H5 File Error: %s' %str(e))
                return False
                
            return True
        
        def on_edit_connection_table(self,widget):
            # get path to text editor
            editor_path = self.exp_config.get('programs','text_editor')
            editor_args = self.exp_config.get('programs','text_editor_arguments')
            if editor_path:  
                if '{file}' in editor_args:
                    editor_args = editor_args.replace('{file}', self.exp_config.get('paths','connection_table_py'))
                else:
                    editor_args = self.exp_config.get('paths','connection_table_py') + " " + editor_args
                
                try:
                    Popen([editor_path,editor_args])
                except Exception:
                    raise Exception("Unable to launch text editor. Check the path is valid in the experiment config file (%s)"%self.exp_config.config_path)
            else:
                raise Exception("No editor path was specified in the lab config file")
                
            
        def on_select_globals(self,widget):
            self.settings.create_dialog(goto_page=settings_pages.connection_table.ConnectionTable)
              
        def on_about(self,widget):
            pass
            
        def on_reset_menuitem_activate(self,menuitem):
            pass
        
        def on_window_destroy(self,widget):
            self.destroy()
        
        def on_delete_event(self,a,b):
            self.destroy()
            return True
        
        def destroy(self):
            logger.info('destroy called')
            if not self.exiting:
                self.exiting = True
                self.manager_running = False
                self.filewatcher.stop()
                self.settings.close()
                self.notifications.close_all()
                experiment_server.shutdown()
                
                gobject.idle_add(self.on_save_exit)
                
        def on_save_exit(self):
            # Save front panel
            data = self.front_panel_settings.get_save_data()
           
            with h5py.File(self.settings_path,'r+') as h5file:
                if 'connection table' in h5file:
                    del h5file['connection table']
            
            self.front_panel_settings.save_front_panel_to_h5(self.settings_path,data[0],data[1],data[2],{"overwrite":True})
                             
            for tab in self.tablist.values():
                tab.destroy()            
                
            gobject.timeout_add(100,self.finalise_quit,time.time())
        
        def finalise_quit(self,initial_time):
            # Kill any tabs which didn't close themselves:
            for name, tab in self.tablist.items():
                if tab.destroy_complete:
                    del self.tablist[name]
            if self.tablist:
                if time.time() - initial_time > 2:
                    for name, tab in self.tablist.items():
                        try:
                            tab.close_tab() 
                        except Exception as e:
                            logger.error('Couldn\'t close tab:\n%s'%str(e))
                        del self.tablist[name]
            if self.tablist:
                return True
            else:
                logger.info('quitting')
                self.window.hide()
                gtk.main_quit()
                logger.info('gtk.main_quit done')
                return False
        
        def on_repeat_toggled(self,widget):
            self.manager_repeat = widget.get_active()
            
        def on_pause_queue(self,widget):
            self.manager_paused = widget.get_active()
            if widget.get_active():
                self.builder.get_object('hbox_running').hide()
                self.builder.get_object('hbox_paused').show()
            else:
                self.builder.get_object('hbox_running').show()
                self.builder.get_object('hbox_paused').hide()
                
        def on_delete_queue_element(self,widget):
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()
            while selection:
                path = selection[0]
                iter = model.get_iter(path)
                model.remove(iter)
                selection = self.listwidget.get_selection()
                model, selection = selection.get_selected_rows()
        
        def move_up(self,button):
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()
            selection = [path[0] for path in selection]
            n = self.queue.iter_n_children(None)
            order = range(n)
            for index in sorted(selection):
                if 0 < index < n  and (order[index - 1] not in selection):
                    order[index], order[index - 1] =  order[index - 1], order[index]
            self.queue.reorder(order)
               
        def move_down(self,button):
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()
            selection = [path[0] for path in selection]
            n = self.queue.iter_n_children(None)
            order = range(n)
            for index in reversed(sorted(selection)):
                if 0 <= index < n - 1 and (order[index + 1] not in selection):
                    order[index], order[index + 1] =  order[index + 1], order[index]
            self.queue.reorder(order)
            
        def move_top(self,button):
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()
            selection = [path[0] for path in selection]
            n = self.queue.iter_n_children(None)
            order = range(n)
            for index in sorted(selection):
                while 0 < index < n and (order[index - 1] not in selection):
                    # swap!
                    order[index], order[index - 1] =  order[index - 1], order[index]
                    index -= 1
            self.queue.reorder(order)
            
        def move_bottom(self,button):
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()
            selection = [path[0] for path in selection]
            n = self.queue.iter_n_children(None)
            order = range(n)
            for index in reversed(sorted(selection)):
                while 0 <= index < n - 1 and (order[index + 1] not in selection):
                    # swap!
                    order[index], order[index + 1] =  order[index + 1], order[index]
                    index += 1
            self.queue.reorder(order)
        
        def is_in_queue(self,path):
            item = self.queue.get_iter_first()
            while item:
                if path ==  self.queue.get(item,0)[0]:
                    return True
                else:
                    item = self.queue.iter_next(item)
            
        #################
        # Queue Manager #
        #################        

        # 
        #
        # START:
        # Does nothing if pause button is pushed: Sleep(1s)
        # Gets file path. If no file: Sleep(1s), return to start
        # If file path:
        # Final (second check) on connection table
        # Transition to buffered: Sends file path off to hardware devices, waits for programmed response
        # Sends start trigger to hardware
        # Waits for digital line signaling end of experiment to go High
        # Transition to static
        # Return to start
        
        def manage(self):


            logger = logging.getLogger('BLACS.queue_manager')   
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
            
            timeout_limit = 130 #seconds
            
            with gtk.gdk.lock:
                self.status_bar.set_text("Idle")
            while self.manager_running:
                # If the pause button is pushed in, sleep
                if self.manager_paused:
                    with gtk.gdk.lock:
                        if self.status_bar.get_text() == "Idle":
                            logger.info('Paused')
                        self.status_bar.set_text("Queue Paused") 
                    time.sleep(1)
                    continue
                
                # Get the top file
                with gtk.gdk.lock:
                    iter = self.queue.get_iter_first()
                # If no files, sleep for 1s,
                if iter is None:
                    with gtk.gdk.lock:
                        if self.status_bar.get_text() != "Idle":
                            self.status_bar.set_text("Idle")
                    time.sleep(1)
                    continue

                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Reading file path from the queue:")    
                    path = "".join(self.queue.get(iter,0))
                    self.queue.remove(iter)
                    self.now_running.set_markup('Now running: <b>%s</b>'%os.path.basename(path))
                    self.now_running.show()
                logger.info('Got a file: %s' % path)
                # Transition devices to buffered mode
                transition_list = {}     
                # A Queue for event-based notification when the tabs have
                # completed transitioning to buffered:
                self.current_queue = Queue.Queue()           
                start_time = time.time()
                timed_out = False
                error_condition = False
                with gtk.gdk.lock:
                    self.status_bar.set_text("Transitioning to Buffered")
                    for name,tab in self.tablist.items():
                        # do we need to transition this device?
                        with h5py.File(path,'r') as hdf5_file:
                            if name in hdf5_file['devices/']:
                                if tab.error:
                                    logger.error('%s has an error condition, aborting run' % name)
                                    error_condition = True
                                    break
                                tab.transition_to_buffered(path,self.current_queue)
                                transition_list[name] = tab
                
                devices_in_use = transition_list.copy()

                while transition_list and not error_condition:
                    try:
                        # Wait for a device to transtition_to_buffered:
                        name = self.current_queue.get(timeout=2)
                        if name == 'abort':
                            logger.info('abort signal received during transition to buffered' % name)
                            error_condition = True
                            break
                        logger.debug('%s finished transitioning to buffered mode' % name)
                        # The tab says it's done, but does it have an error condition?
                        if transition_list[name].error:
                            logger.error('%s has an error condition, aborting run' % name)
                            error_condition = True
                            break
                        del transition_list[name]                   
                    except:
                        # It's been 2 seconds without a device finishing
                        # transitioning to buffered. Is there an error?
                        for name,tab in transition_list.items():
                            if tab.error:
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
                    self.queue.prepend([path])
                    with gtk.gdk.lock:
                        self.queue_pause_button.set_state(True)
                        if timed_out:
                            self.status_bar.set_text("Device programming timed out. Queue Paused...")
                        else:
                            self.status_bar.set_text("One or more devices is in an error state. Queue Paused...")
                            
                    # Abort the run for all devices in use:
                    for tab in devices_in_use.values():
                        tab.abort_buffered()
                    with gtk.gdk.lock:
                        self.now_running.hide()
                    continue
                with gtk.gdk.lock:
                    self.status_bar.set_text("Preparing to start sequence...(program time: %.3fs)"%(time.time()- start_time))
                    # Get front panel data, but don't save it to the h5 file until the experiment ends:
                    states,tab_positions,window_data = self.front_panel_settings.get_save_data()
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Running...(program time: %.3fs)"%(time.time()- start_time))
                    
                # A Queue for event-based notification of when the experiment has finished.
                self.current_queue = Queue.Queue()   
                
                # Tell the Pulseblaster to start the run and to let us know when the it's finished:
                
                logger.debug('About to start the master pseudoclock')
                self.tablist[self.master_pseudoclock].start_run(self.current_queue)

                # Science!

                # Wait for notification of the end of run:
                result = self.current_queue.get()
                if result == 'abort':
                   pass # not implemented
                logger.info('Run complete')
                
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Sequence done, saving data...")
                with h5py.File(path,'r+') as hdf5_file:
                    self.front_panel_settings.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table = False)
                with h5py.File(path,'a') as hdf5_file:
                    data_group = hdf5_file['/'].create_group('data')
                    # stamp with the run time of the experiment
                    hdf5_file.attrs['run time'] = time.strftime('%Y%m%dT%H%M%S',time.localtime())
        
                # A Queue for event-based notification of when the devices have transitioned to static mode:
                self.current_queue = Queue.Queue()    
                    
                # only transition one device to static at a time,
                # since writing data to the h5 file can potentially
                # happen at this stage:
                error_condition = False
                for devicename, tab in devices_in_use.items():
                    with gtk.gdk.lock:
                        tab.transition_to_static(self.current_queue)
                    result = self.current_queue.get()
                    if result == 'abort':
                        error_condition = True
                    if tab.error:
                        error_condition = True
                if not error_condition:            
                    logger.info('All devices are back in static mode.')  
                    # Submit to the analysis server, if submission is enabled:
                    self.analysis_queue.put(['file', path])
                        
                    with gtk.gdk.lock:
                        self.status_bar.set_text("Idle")
                        if self.manager_repeat:
                            # Resubmit job to the bottom of the queue:
                            process_request(path)
                        self.now_running.hide()
                else:
                    self.manager_paused = True
                    # clean the h5 file:
                    self.clean_h5_file(path, 'temp.h5')
                    try:
                        os.remove(path)
                        os.rename('temp.h5', path)
                    except WindowsError if os.name == 'nt' else None:
                        logger.warning('Couldn\'t delete failed run file %s, another process may be using it. Using alternate filename for second attempt.'%path)
                        os.rename('temp.h5', path.replace('.h5','_retry.h5'))
                    # Put it back at the start of the queue:
                    self.queue.prepend([path])
                    with gtk.gdk.lock:
                        self.queue_pause_button.set_state(True)
                        self.status_bar.set_text("Error during transtion to static. Queue Paused.")
                        self.now_running.hide()
                        
                #import memprof
                #import gc
                #gc.collect()
                #memprof.count_diffs()
            logger.info('Stopping')

    class AnalysisSubmission(object):
        port = 42519
        
        def __init__(self, container, inqueue,blacs_settings_path):
            self.inqueue = inqueue
            
            builder = gtk.Builder()
            builder.add_from_file('analysis_submission.glade')
            builder.connect_signals(self)
            
            self.analysis_host = builder.get_object('analysis_server_host')
            self.server_is_responding = builder.get_object('server_is_responding')
            self.server_is_not_responding = builder.get_object('server_is_not_responding')
            self.toggle_analysis = builder.get_object('analysis_toggle')
            self.analysis_error = builder.get_object('analysis_error')
            self.analysis_error_message = builder.get_object('analysis_error_message')
            self.spinner = builder.get_object('spinner')
            toplevel = builder.get_object('toplevel')
            
            container.add(toplevel)
            toplevel.show()
            
            # load settings:
            try:
                with h5py.File(blacs_settings_path,'r') as hdf5_file:
                    dataset = hdf5_file["/front_panel/analysis_server"]
                    self.toggle_analysis.set_active(dataset.attrs['send_for_analysis'])
                    self.analysis_host.set_text(dataset.attrs['server']) 
            except:
                pass 
            self.waiting_for_submission = []
            self.mainloop_thread = threading.Thread(target=self.mainloop)
            self.mainloop_thread.daemon = True
            self.mainloop_thread.start()
            if self.toggle_analysis.get_active():
                self.inqueue.put(['check connectivity', None])
        
        def on_check_connectivity_clicked(self,widget):
            self.inqueue.put(['check connectivity',None])       
            
        def on_try_again_clicked(self,widget):
            self.inqueue.put(['try again', None])
        
        def on_clear_clicked(self,widget):
            self.inqueue.put(['clear',None])
                     
        def mainloop(self):
            while True:
                signal, data = self.inqueue.get()
                with gtk.gdk.lock:
                    self.spinner.show()
                if signal == 'close':
                    break
                elif signal == 'file':
                    with gtk.gdk.lock:
                        if self.toggle_analysis.get_active():
                            self.waiting_for_submission.append(data)
                    self.submit_waiting_files()
                elif signal == 'try again':
                    self.submit_waiting_files()
                elif signal == 'check connectivity':
                    self.check_connectivity()
                elif signal == 'clear':
                    self.waiting_for_submission = []
                    with gtk.gdk.lock:
                        self.analysis_error.hide()
                else:
                    raise ValueError('Invalid signal: %s'%str(signal))
                with gtk.gdk.lock:
                    self.spinner.hide()   
                       
        def check_connectivity(self):
            with gtk.gdk.lock:
                host = self.analysis_host.get_text()
            try:
                #print 'Submitting run file %s.\n'%os.path.basename(run_file)
                response = zmq_get(self.port, host, 'hello', timeout = 2)
                if response == 'hello':
                    success = True
                else:
                    success = False
            except Exception:
                success = False
            with gtk.gdk.lock:
                if success:
                    self.server_is_responding.show()
                    self.server_is_not_responding.hide()
                else:
                    self.server_is_responding.hide()
                    self.server_is_not_responding.show()
                         
        def submit_waiting_files(self):
            if not self.waiting_for_submission:
                return
            while self.waiting_for_submission:
                path = self.waiting_for_submission.pop(0)
                with gtk.gdk.lock:
                    host = self.analysis_host.get_text()
                try:
                    logger.info('Submitting run file %s.\n'%os.path.basename(path))
                    data = {'filepath': path}
                    response = zmq_get(self.port, host, data, timeout = 2)
                    if response != 'added successfully':
                        raise Exception
                except:
                    # Put the file back at the beginning of the waiting list:
                    self.waiting_for_submission.insert(0,path)
                    # Change the gui to show the error state:
                    with gtk.gdk.lock:
                        self.server_is_responding.hide()
                        self.server_is_not_responding.show()
                        self.analysis_error.show()
                        self.analysis_error_message.set_markup('<span foreground="red">Couldn\'t submit %d files</span>'%len(self.waiting_for_submission))
                    return
            # If the loop completed, then the submissions were successful:
            with gtk.gdk.lock:
                self.server_is_responding.show()
                self.server_is_not_responding.hide()
                self.analysis_error.hide()
                
    class ExperimentServer(ZMQServer):
        def handler(self, h5_filepath):
            with gtk.gdk.lock:
                # Convert path to local slashes and shared drive prefix:
                shared_drive_prefix = app.exp_config.get('paths','shared_drive')     
                h5_filepath = h5_filepath.replace('\\', os.path.sep).replace('Z:', shared_drive_prefix)
                logger.info('local filepath: %s'%h5_filepath)
                message = process_request(h5_filepath)
            logger.info('Request handler: %s ' % message.strip())
            return message

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
            if rerun or app.is_in_queue(h5_filepath):
                logger.debug('Run file has already been run! Creating a fresh copy to rerun')
                new_h5_filepath = new_rep_name(h5_filepath)
                # Keep counting up until we get a filename that isn't in the filesystem:
                while os.path.exists(new_h5_filepath):
                    new_h5_filepath = new_rep_name(new_h5_filepath)
                success = app.clean_h5_file(h5_filepath, new_h5_filepath)
                if not success:
                   return 'Cannot create a re run of this experiment. Is it a valid run file?'
                app.queue.append([new_h5_filepath])
                message = "Experiment added successfully: experiment to be re-run\n"
            else:
                app.queue.append([h5_filepath])
                message = "Experiment added successfully\n"
            if app.manager_paused:
                message += "Warning: Queue is currently paused\n"
            if not app.manager_running:
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

    #####################
    ### BEGIN PROGRAM ###
    #####################    
    splash.update_text('Loading configuration file...')
    # Load the experiment config file, and verify that the necessary parameters are there"
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
    gtk.gdk.threads_init()
    
    
    app = BLACS(exp_config,settings_path,splash)
    # Make it not look so terrible (if icons and themes are installed):
    
    splash.update_text('configuring theme...')
    gtk.settings_get_default().set_string_property('gtk-icon-theme-name','gnome-human','')
    gtk.settings_get_default().set_string_property('gtk-theme-name','Clearlooks','')
    gtk.settings_get_default().set_string_property('gtk-font-name','ubuntu 9','')
    gtk.settings_get_default().props.gtk_button_images = True
    gtk.rc_parse('blacs.gtkrc')
    
    splash.update_text('Starting web server for the queue...')
    experiment_server = ExperimentServer(port)
    splash.update_text('Done!')
    
    app.window.maximize()            
    app.window.show()
    # Try putting a time.sleep(10) here!!
    #time.sleep(10)
    splash.destroy()
    with gtk.gdk.lock:
        gtk.main()
        
