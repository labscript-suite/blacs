
import sys
import logging, logging.handlers
import excepthook
import os
import urllib2
#
# Note, Throughout this file we put things we don't want imported in the Worker Processes, inside a "if __name__ == "__main__":"
# Otherwise we import a bunch of stuff we don't need into the child processes! This is due to the way processes are spawned on windows. 
#
if __name__ == "__main__":
    import threading
    import cgi
    import time
    import socket
    import urllib

    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

    import gtk
    import gobject
    import numpy
    import h5py
    
    # Connection Table Code
    from connections import ConnectionTable

def setup_logging():
    logger = logging.getLogger('BLACS')
    handler = logging.handlers.RotatingFileHandler(r'C:\\pythonlib\BLACS.log', maxBytes=1024*1024*50)
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
if __name__ == "__main__":
    logger.info('\n\n===============starting===============\n')
    
# Hardware Interface Imports
from hardware_interfaces import *
for device in device_list:    
    exec("from hardware_interfaces."+device+" import "+device)

if __name__ == "__main__":
    # Virtual Devices Import
    #needs to be dynamic import
    from virtual_devices.shutter import *

    # Temporary imports to demonstrate plotting
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D
    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas


    class BLACS(object):       
        def __init__(self):
            self.exiting = False
            
            self.builder = gtk.Builder()
            self.builder.add_from_file('main_interface.glade')
            self.builder.connect_signals(self)
            self.window = self.builder.get_object("window")
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
            treeselection = self.listwidget.get_selection()
            treeselection.set_mode(gtk.SELECTION_MULTIPLE)
            
            # Set group ID's of notebooks to be the same
            for k,v in self.notebook.items():
                v.set_group_id(1323)
            
            # Need to connect signals!
            self.builder.connect_signals(self)

            # Load Connection Table
            # Get H5 file        
            h5_file = os.path.join("connectiontables", socket.gethostname()+".h5")
            
            # Create Connection Table
            self.connection_table = ConnectionTable(h5_file)
            
            # Instantiate Devices from Connection Table, Place in Array        
            self.attached_devices = self.connection_table.find_devices(device_list)
            
            self.settings_dict = {"ni_pcie_6363_0":{"device_name":"ni_pcie_6363_0"},
                                  "ni_pci_6733_0":{"device_name":"ni_pci_6733_0"},
                                  "pulseblaster_0":{"device_name":"pulseblaster_0","device_num":0,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"},
                                  "pulseblaster_1":{"device_name":"pulseblaster_1","device_num":1,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"},
                                  "novatechdds9m_0":{"device_name":"novatechdds9m_0","COM":"com10"},
                                  "novatechdds9m_1":{"device_name":"novatechdds9m_1","COM":"com13"},
                                  "novatechdds9m_2":{"device_name":"novatechdds9m_2","COM":"com8"},
                                  "novatechdds9m_9":{"device_name":"novatechdds9m_9","COM":"com9"},
                                  "camera":{"device_name":"camera"}
                                 }
            
            # read out position settings
            tab_positions = {}
            try:
                with h5py.File(os.path.join("connectiontables", socket.gethostname()+"_settings.h5"),'r') as hdf5_file:
                    notebook_settings = hdf5_file['/front_panel/_notebook_data']
                    
                    self.window.move(notebook_settings.attrs["window_xpos"],notebook_settings.attrs["window_ypos"])
                    self.window.resize(notebook_settings.attrs["window_width"],notebook_settings.attrs["window_height"])
                    
                    for row in notebook_settings:
                        tab_positions[row[0]] = {"notebook":row[1],"page":row[2],"visible":row[3]}
                    
                    for k,v in self.panes.items():
                        v.set_position(notebook_settings.attrs[k])
                        
            except Exception as e:
                logger.warning("Unable to load window and notebook defaults. Exception:"+str(e))
            
            for k,v in self.settings_dict.items():
                # add common keys to settings:
                v["connection_table"] = self.connection_table
                #v["state_machine"] = self.state_machine
            
            self.tablist = {}
            for k,v in self.attached_devices.items():
                notebook_num = "1"
                if k in tab_positions:
                    notebook_num = tab_positions[k]["notebook"]
                    if notebook_num not in self.notebook:        
                        notebook_num = "1"
                        
                self.tablist[k] = globals()[v](self.notebook[notebook_num],self.settings_dict[k])
            
            # Now that all the pages are created, reorder them!
            for k,v in self.attached_devices.items():
                if k in tab_positions:
                    notebook_num = tab_positions[k]["notebook"]
                    if notebook_num in self.notebook:                                        
                        self.notebook[notebook_num].reorder_child(self.tablist[k]._toplevel,tab_positions[k]["page"])
                    
            # now that they are in the correct order, set the correct one visible
            for k,v in tab_positions.items():
                # if the notebook still exists and we are on the entry that is visible
                if v["visible"] and v["notebook"] in self.notebook:
                    self.notebook[v["notebook"]].set_current_page(v["page"])
            
            #TO DO:            
            # Open BLACS Config File
            # Load Virtual Devices
            
            #self.shutter_tab = globals()["shutter"]([self.tab.get_child("DO",1),self.tab.get_child("DO",5),self.tab.get_child("DO",27),self.tab.get_child("DO",13)])
            #self.notebook.append_page(self.shutter_tab.tab,gtk.Label("shutter_0"))
            #
            # Setup a quick test of plotting data!
            #
            vbox = gtk.VBox()

            fig = Figure(figsize=(5,4), dpi=100)
            ax = fig.add_subplot(111)
            t = numpy.arange(0,10000,1)
            s = numpy.arange(-10,11,21/10000.)
            self.plot_data = s
            ax.plot(t,s)
            self.ax = ax
            self.figure = fig

            canvas = FigureCanvas(fig)  # a gtk.DrawingArea
            self.canvas = canvas
            vbox.pack_start(canvas)
            #self.notebook.append_page(vbox,gtk.Label("graph!"))
            #vbox.show_all()
            #self.tablist["ni_pcie_6363_0"].request_analog_input(0,50000,self.update_plot)
            
            self.window.maximize()
            
            self.window.show()
            
            # Start Queue Manager
            self.manager_running = True
            self.manager_paused = False
            self.manager_repeat = False
            self.manager = threading.Thread(target = self.manage)
            self.manager.daemon=True
            self.manager.start()
               
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
            chooser.set_current_folder(r'Z:\\Experiments')
            response = chooser.run()
            if response == gtk.RESPONSE_OK:
                filename = chooser.get_filename()
                result = process_request(filename)
            else:
                chooser.destroy()
                return
            chooser.destroy()
            if not 'added successfully' in result:
                message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_OK, result) 
                message.run()  
                message.destroy()
            logger.info('Open file:\n%s ' % result)
            
        def get_save_data(self):   
            # So states is a dict with an item for each device
            # *class*. These items have the key being the class name, and
            # the value being another dictionary. This other dictionary
            # has keys being the specific names of each device of that
            # class, and values being each device tab's settings dict.
            states = {}
            tab_positions = {}
            for devicename,tab in self.tablist.items():
                deviceclass_name = self.attached_devices[devicename]
                if deviceclass_name not in states:
                    states[deviceclass_name] = {}
                front_panel_states = tab.get_front_panel_state()
                states[deviceclass_name][devicename] = front_panel_states
            
                # Find the notebook it is in
                current_notebook = tab._toplevel.get_parent()
                # By default we assume it is in notebook1. This way, if a tab gets lost somewhere, and isn't found to be a child of any notebook we know about, 
                # it will revert back to notebook 1 when the file is loaded!
                current_notebook_name = "1" 
                
                for notebook_name,notebook in self.notebook.items():
                    if notebook == current_notebook:
                        current_notebook_name = notebook_name                       
                
                page = current_notebook.page_num(tab._toplevel)
                visible = True if current_notebook.get_current_page() == page else False
                # find the page it is in
                tab_positions[devicename] = {"notebook":current_notebook_name,"page":page, "visible":visible}
            
            # save window data
            window_data = {}
            
            # Size of window
            #self.window.unmaximize()
            win_size = self.window.get_size()
            win_pos = self.window.get_position()
            #self.window.maximize()
            window_data["window"] = {"width":win_size[0],"height":win_size[1],"xpos":win_pos[0],"ypos":win_pos[1]}
            # Main Hpane
            for k,v in self.panes.items():
                window_data[k] = v.get_position()
            
            return states,tab_positions,window_data
            
        def on_save_front_panel(self,widget):
            data = self.get_save_data()
        
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
                    
            self.save_front_panel_to_h5(current_file,data[0],data[1],data[2])    

        def save_front_panel_to_h5(self,current_file,states,tab_positions,window_data,silent = {}):        
            # Save the front panel!

            # Does the file exist?            
            #   Yes: Check connection table inside matches current connection table. Does it match?
            #        Yes: Does the file have a front panel already saved in it?
            #               Yes: Can we overwrite?
            #                  Yes: Delete front_panel group, save new front panel
            #                  No:  Create error dialog!
            #               No: Save front panel in here
            #   
            #        No: Return
            #   No: Create new file, place inside the connection table and front panel
                
            if os.path.isfile(current_file):
                save_conn_table = False
                try:
                    new_conn = ConnectionTable(current_file)
                except:
                    # no connection table is present, so also save the connection table!
                    save_conn_table = True
                
                # if save_conn_table is True, we don't bother checking to see if the connection tables match, because save_conn_table is only true when the connection table doesn't exist in the current file
                # As a result, if save_conn_table is True, we ignore connection table checking, and save the connection table in the h5file.
                if save_conn_table or self.connection_table.compare_to(new_conn):
                    with h5py.File(current_file,'r+') as hdf5_file:
                        if hdf5_file['/'].get('front_panel') != None:
                            # Create a dialog to ask whether we can overwrite!
                            overwrite = False
                            if not silent:                                
                                message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_YES_NO, "Do you wish to replace the existing front panel configuration in this file?")                             
                                resp = message.run()
                                
                                if resp == gtk.RESPONSE_YES:
                                    overwrite = True                              
                                message.destroy()
                            else:
                                overwrite = silent["overwrite"]
                            
                            if overwrite:
                                # Delete Front panel group, save new front panel
                                del hdf5_file['/front_panel']
                                self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table)
                            else:
                                if not silent:
                                    message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_CANCEL, "Front Panel not saved.") 
                                    message.run()  
                                    message.destroy()
                                else:
                                    logger.info("Front Panel not saved as it already existed in the h5 file '"+current_file+"'")
                                return
                        else: 
                            # Save Front Panel in here
                            self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table)
                else:
                    # Create Error dialog (invalid connection table)
                    if not silent:
                        message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_CANCEL, "The Front Panel was not saved as the file selected contains a connection table which is not a subset of the current connection table.") 
                        message.run()  
                        message.destroy()   
                    else:
                        logger.info("Front Panel not saved as the connection table in the h5 file '"+current_file+"' didn't match the current connection table.")
                    return
            else:
                with h5py.File(current_file,'w') as hdf5_file:
                    # save connection table, save front panel                    
                    self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table=True)
            
        def save_conn_table_to_h5_file(self,hdf5_file):
            h5_file = os.path.join("connectiontables", socket.gethostname()+".h5")
            with h5py.File(h5_file,'r') as conn_table:
                conn_data = numpy.array(conn_table['/connection table'][:])
                hdf5_file['/'].create_dataset('connection table',data=conn_data)

           
        def store_front_panel_in_h5(self, hdf5_file,states,tab_positions,window_data,save_conn_table = False):
            if save_conn_table:
                self.save_conn_table_to_h5_file(hdf5_file)
            
            #with h5py.File(current_file,'a') as hdf5_file:
            data_group = hdf5_file['/'].create_group('front_panel')
            
            # Iterate over each device class:
            for deviceclass, deviceclass_states in states.items():
                logger.debug("saving front panel for class:" + deviceclass) 
                device_data = None
                dataset = None
                dtypes = [('name','a256')]
                
                i = 0
                # Iterate over each device within a class
                for devicename, device_state in deviceclass_states.items():
                    logger.debug("saving front panel for device:" + devicename) 
                    if device_data is None:
                        # Add the dtypes for the device's state property
                        # name (eg freq0, DO12, etc) and value of the
                        # property:
                        for property_name, property_value in device_state.items():
                            dtype = type(property_value)
                            if dtype is str:
                                # Have to specify string length:
                                dtype = 'a256'
                            dtypes.append((property_name,dtype))
                        logger.debug("Generated dtypes dtypes:"+str(dtypes))
                        
                        # Create the numpy array
                        device_data = numpy.empty(len(deviceclass_states),dtype=dtypes)
                        logger.debug("Length of dict 'deviceclass_states': "+str(len(deviceclass_states)))
                        logger.debug("Shape of data array: "+str(device_data.shape)) 
                        
                    logger.debug("inserting data to the array")
                    
                    # Get the data into a list for the i'th row.
                    data_list = [devicename]
                    for property_name, property_value in device_state.items():
                        data_list.append(property_value)
                    device_data[i] = tuple(data_list)
                    i += 1
                
                # Create the dataset! 
                logger.debug("attempting to create dataset...")   
                dataset = data_group.create_dataset(deviceclass,data=device_data)
                
            # Save tab positions
            #logger.info(tab_positions)
            i = 0
            tab_data = numpy.empty(len(tab_positions),dtype=[('tab_name','a256'),('notebook','a2'),('page',int),('visible',bool)])
            for k,v in tab_positions.items():
                tab_data[i] = (k,v["notebook"],v["page"],v["visible"])
                i += 1
            dataset = data_group.create_dataset("_notebook_data",data=tab_data)
            dataset.attrs["window_width"] = window_data["window"]["width"]
            dataset.attrs["window_height"] = window_data["window"]["height"]
            dataset.attrs["window_xpos"] = window_data["window"]["xpos"]
            dataset.attrs["window_ypos"] = window_data["window"]["ypos"]
            for k,v in window_data.items():
                if k != "window":
                    dataset.attrs[k] = v
        
        def clean_h5_file(self,h5file,new_h5_file):
            try:
                with h5py.File(h5file,'r') as old_file:
                    with h5py.File(new_h5_file,'w') as new_file:
                        new_file['/'].copy(old_file['/devices'],"devices")
                        new_file['/'].copy(old_file['/calibrations'],"calibrations")
                        new_file['/'].copy(old_file['/script'],"script")
                        new_file['/'].copy(old_file['/globals'],"globals")
                        new_file['/'].copy(old_file['/connection table'],"connection table")
                        new_file['/'].copy(old_file['/analysis'],"analysis")
            except Exception as e:
                raise
                logger.error('Clean H5 File Error: %s' %str(e))
                return False
                
            return True
        
        def on_edit_connection_table(self,widget):
            pass
            
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
                for tab in self.tablist.values():
                    tab.destroy()
                
                # Save front panel
                data = self.get_save_data()
                settingspath = os.path.join("connectiontables", socket.gethostname()+"_settings.h5")
                with h5py.File(settingspath,'r+') as h5file:
                    if 'connection table' in h5file:
                        del h5file['connection table']
                self.save_front_panel_to_h5(settingspath,data[0],data[1],data[2],{"overwrite":True})
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
                start_time = time.time()
                error_condition = False
                with gtk.gdk.lock:
                    self.status_bar.set_text("Transitioning to Buffered")
                    #self.tab.setup_buffered_trigger()
                    for name,tab in self.tablist.items():
                        # do we need to transition this device?
                        with h5py.File(path,'r') as hdf5_file:
                            if name in hdf5_file['devices/']:
                                # leave camera 'til everything else is
                                # done, workaround for the fact that the
                                # camera system does writes to the h5 file:
                                if name != 'camera':
                                    tab.transition_to_buffered(path)
                                transition_list[name] = tab
                
                devices_in_use = transition_list.copy()
                
                while transition_list:
                    for name,tab in transition_list.items():
                        if tab.transitioned_to_buffered:
                            del transition_list[name]
                            logger.debug('%s finished transitioning to buffered mode' % name)
                        if tab.error:
                            logger.error('%s has an error condition, aborting run' % name)
                            error_condition = True
                            break
                    end_time = time.time()
                    if end_time - start_time > timeout_limit:
                        logger.error('Transitioning to buffered mode timed out')
                        break
                    if error_condition:
                        break
                    # Transition the camera to buffered mode only once everything else is done:
                    if transition_list.keys() == ['camera']:
                        with gtk.gdk.lock:
                            transition_list['camera'].transition_to_buffered(path)
                    time.sleep(0.1)
                
                # Handle if we broke out of loop due to timeout
                if end_time - start_time > timeout_limit or error_condition:
                    # It took too long, pause the queue, re add the path to the top of the queue, and set a status message!
                    self.manager_paused = True
                    self.queue.prepend([path])
                    with gtk.gdk.lock:
                        self.queue_pause_button.set_state(True)
                        if end_time - start_time > timeout_limit:
                            self.status_bar.set_text("Device programming timed out. Queue Paused...")
                        else:
                            self.status_bar.set_text("One or more devices is in an error state. Queue Paused...")
                            
                    # Abort the run for other devices
                    for tab in devices_in_use.values():
                        tab.abort_buffered()
                    with gtk.gdk.lock:
                        self.now_running.hide()
                    continue

                with gtk.gdk.lock:
                    self.status_bar.set_text("Preparing to start sequence...(program time: "+str(end_time - start_time)+"s")
                    # Get front panel data, but don't save it to the h5 file until the experiment ends:
                    states,tab_positions,window_data = self.get_save_data()
                
                logger.debug('About to start the PulseBlaster')
                self.tablist["pulseblaster_0"].start()
                #self.tablist["pulseblaster_1"].start()
                logger.info('Experiment run has started!')
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Running...(program time: "+str(end_time - start_time)+"s")
                
                #force status update
                self.tablist["pulseblaster_0"].status_monitor() # Is this actually needed?
                
                # This is a bit of a hack, but will become irrelevant once we have a proper method of determining the experiment execution state
                # Eg, monitoring a digital flag!
                time.sleep(.05) # What's this for? Can it be deleted?
                
                while not self.tablist["pulseblaster_0"].status["waiting"]:
                    if not self.manager_running:
                        break
                    time.sleep(0.05)
                    
                logger.info('Run complete')
                with gtk.gdk.lock:
                    self.status_bar.set_text("Sequence done, saving data...")
                with h5py.File(path,'r+') as hdf5_file:
                    self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table = False)
                        
                with h5py.File(path,'a') as hdf5_file:
                    data_group = hdf5_file['/'].create_group('data')
                    
                # only transition one device to static at a time,
                # since writing data to the h5 file can potentially
                # happen at this stage:
                for devicename, tab in devices_in_use.items():
                    with gtk.gdk.lock:
                        tab.transition_to_static()
                    while not tab.static_mode:
                        logging.debug("%s tab has not transitioned to static"%devicename)
                        time.sleep(0.1)
                            
                logger.info('All devices are back in static mode.')  

                with gtk.gdk.lock:
                    self.status_bar.set_text("Submitting to analysis server")

                port = 42519
                server = 'localhost'
                # Workaround to force python not to use IPv6 for the request:
                address  = socket.gethostbyname(server)
                #print 'Submitting run file %s.\n'%os.path.basename(run_file)
                params = urllib.urlencode({'filepath': os.path.abspath(path)})
                response = urllib2.urlopen('http://%s:%d'%(address,port), params, 2).read()
                #if not 'added successfully' in response:
                    #raise Exception(response)

                with gtk.gdk.lock:
                    self.status_bar.set_text("Idle")
                    if self.manager_repeat:
                        # Resubmit job to the bottom of the queue:
                        process_request(path)
                    self.now_running.hide()
            logger.info('Stopping')
            
    class RequestHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
            length = int(self.headers.getheader('content-length'))
            postvars = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
            h5_filepath =  postvars['filepath'][0]
            with gtk.gdk.lock:
                message = process_request(h5_filepath)
            logger.info('Request handler: %s ' % message.strip())
            self.wfile.write(message)
            self.wfile.close()

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
            return "H5 file not accessible to Control PC\n"
        if app.connection_table.compare_to(new_conn):
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
            message =  ("Connection table of your file is not a subset of the experimental control apparatus.\n"
                       "You may have:\n"
                       "    Submitted your file to the wrong control PC\n"
                       "    Added new channels to your h5 file, without rewiring the experiment and updating the control PC\n"
                       "    Renamed a channel at the top of your script\n"
                       "    Submitted an old file, and the experiment has since been rewired\n"
                       "\n"
                       "Please verify your experiment script matches the current experiment configuration, and try again\n")
            return message


    port = 42517
    gtk.gdk.threads_init()
    app = BLACS()
    # Make it not look so terrible (if icons and themes are installed):
    gtk.settings_get_default().set_string_property('gtk-icon-theme-name','gnome-human','')
    gtk.settings_get_default().set_string_property('gtk-theme-name','Clearlooks','')
    gtk.settings_get_default().set_string_property('gtk-font-name','ubuntu 9','')
    gtk.settings_get_default().props.gtk_button_images = True
    serverthread = threading.Thread(target = HTTPServer(('', port),RequestHandler).serve_forever)
    serverthread.daemon = True
    serverthread.start()
    with gtk.gdk.lock:
        gtk.main()
        
