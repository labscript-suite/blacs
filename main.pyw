
import sys
import logging, logging.handlers
import excepthook
import os

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
    handler = logging.handlers.RotatingFileHandler(r'C:\\pythonlib\BLACS.log', maxBytes=1024**2, backupCount=1)
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
            self.notebook = self.builder.get_object("notebook1")
            self.queue = self.builder.get_object("remote_liststore")
            self.listwidget = self.builder.get_object("treeview1")
            self.status_bar = self.builder.get_object("status_label")
            self.queue_pause_button = self.builder.get_object("Queue_Pause")
            
            treeselection = self.listwidget.get_selection()
            treeselection.set_mode(gtk.SELECTION_MULTIPLE)
            
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
                                  "pulseblaster_0":{"device_name":"pulseblaster_0","device_num":0,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"},
                                  "pulseblaster_1":{"device_name":"pulseblaster_1","device_num":1,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"},
                                  "novatechdds9m_0":{"device_name":"novatechdds9m_0","COM":"com1"},
                                  "novatechdds9m_1":{"device_name":"novatechdds9m_1","COM":"com13"},
                                  "novatechdds9m_2":{"device_name":"novatechdds9m_2","COM":"com8"},
                                  "novatechdds9m_9":{"device_name":"novatechdds9m_9","COM":"com9"},
                                  "andor_ixon":{"device_name":"andor_ixon"}
                                 }
                                 
            for k,v in self.settings_dict.items():
                # add common keys to settings:
                v["connection_table"] = self.connection_table
                #v["state_machine"] = self.state_machine
            
            self.tablist = {}
            for k,v in self.attached_devices.items():
                self.tablist[k] = globals()[v](self.notebook,self.settings_dict[k])
            
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
            
            # Setup the sequence manager thread
            # This thread will listen on a specific port, and will add items it recieves to a queue
            # We will add an idle callback function which check the queue for entries, and starts an 
            # experimental run if appropriate
            
            
            self.window.show()
            
            # Start Queue Manager
            self.manager_running = True
            self.manager_paused = False
            self.manager = threading.Thread(target = self.manage)
            self.manager.daemon=True
            self.manager.start()
            
        def update_plot(self,channel,data,rate):
            line = self.ax.get_lines()[0]
            #print line
            #print rate
            #self.plot_data = numpy.append(self.plot_data[len(data[0,:]):],data[0,:])
            t = time.time()
            #print 'a'
            a = numpy.zeros(len(self.plot_data))
            a[0:len(self.plot_data)-len(data[0,:])] = self.plot_data[len(data[0,:]):]
            a[len(self.plot_data)-len(data[0,:]):] = data[0,:]
            #print str(time.time()-t)
            self.plot_data = a
            #print str(time.time()-t)
            line.set_ydata(self.plot_data)
            #print str(time.time()-t)
            #self.ax.draw_artist(line)
            # just redraw the axes rectangle
            #self.canvas.blit(self.ax.bbox)
            #print line.data
            #self.ax.plot(data[1,:],data[0,:])
            self.canvas.draw_idle()
            pass
        
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
            
            
        def on_save_front_panel(self,widget):
            states = {}
            for k,v in self.tablist.items():
                if self.attached_devices[k] not in states:
                    states[self.attached_devices[k]] = {}
                states[self.attached_devices[k]][k] = v.get_front_panel_state()
            
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
                        
            self.save_front_panel_to_h5(current_file,states)    

        def save_front_panel_to_h5(self,current_file,states,silent = {}):        
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
                                self.store_front_panel_in_h5(hdf5_file,states,save_conn_table)
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
                            self.store_front_panel_in_h5(hdf5_file,states,save_conn_table)
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
                    self.store_front_panel_in_h5(hdf5_file,states,save_conn_table=True)
            
        def save_conn_table_to_h5_file(self,hdf5_file):
            h5_file = os.path.join("connectiontables", socket.gethostname()+".h5")
            with h5py.File(h5_file,'r') as conn_table:
                conn_data = numpy.array(conn_table['/connection table'][:])
                hdf5_file['/'].create_dataset('connection table',data=conn_data)

           
        def store_front_panel_in_h5(self, hdf5_file,states,save_conn_table = False):
            if save_conn_table:
                self.save_conn_table_to_h5_file(hdf5_file)
            
            #with h5py.File(current_file,'a') as hdf5_file:
            data_group = hdf5_file['/'].create_group('front_panel')
            
            # Iterate over each device class.
            # Here k is the device class
            #      v is the dictionary containing an entry for each device
            for k,v in states.items():
                logger.debug("saving front panel for class:" +k) 
                device_data = None
                ds = None
                my_dtype = []
                i = 0
                
                #The first entry in each row of the numpy array should be a string! Let's find the biggest string for this device and add it
                max_string_length = 0
                
                # Here j is the device name
                #      w is the dictionary of front panel values
                for j,w in v.items():
                    if len(j) > max_string_length:
                        max_string_length = len(j)
                
                # Here j is the device name
                #      w is the dictionary of front panel values
                for j,w in v.items():
                    logger.debug("saving front panel for device:" +j) 
                    if device_data == None:
                        
                        # add the dtype for the string
                        my_dtype.append(('name','a'+str(max_string_length)))
                        
                        # Add the dtypes for the generic dictionary entries
                        # Here l property name (eg freq0, DO12, etc)
                        #      x value of the property
                        for l,x in w.items():
                            my_dtype.append((l,type(x)))
                        logger.debug("Generated dtypes dtypes:"+str(my_dtype))
                        
                        # Create the numpy array
                        device_data = numpy.empty(len(v),dtype=my_dtype)
                        logger.debug("Length of variable 'v':"+str(len(v)))
                        logger.debug("Shape of data array:"+str(device_data.shape)) 
                        
                    logger.debug("inserting data to the array")
                    
                    # Get the data into a list for the i'th row.
                    data_list = []
                    data_list.append(j)
                    
                    # Here l property name (eg freq0, DO12, etc)
                    #      x value of the property
                    for l,x in w.items():
                        data_list.append(x)
                    device_data[i] = tuple(data_list)
                    i += 1
                
                # Create the dataset! 
                logger.debug("attempting to create dataset...")   
                ds = data_group.create_dataset(k,data=device_data)
            
        def on_edit_connection_table(self,widget):
            pass
            
        def on_about(self,widget):
            pass
            
        def on_menuitem_reset_activate(self,menuitem):
            pass
        
        def on_window_destroy(self,widget):
            self.destroy()
        
        def on_delete_event(self,a,b):
            self.destroy()
        
        def destroy(self):
            logger.info('destroy called')
            if not self.exiting:
                self.exiting = True
                self.manager_running = False
                #self.window.hide()
                
                for k,v in self.tablist.items():
                    v.destroy()
                                      
                gobject.timeout_add(100,self.finalise_quit,time.time())
        
        def finalise_quit(self,initial_time):
            #TODO: Force quit all processes after a certain time
            logger.info('checking finalisation:' + str(len(self.tablist))+' items left to finish')
            for k,v in self.tablist.items():
                if v.destroy_complete:
                    v.close_tab()  
                    self.tablist.pop(k)
            logger.info('checked...:' + str(len(self.tablist))+' items left to finish')        
            
            if time.time()-initial_time > 2:
                for k,v in self.tablist.items():
                    v.close_tab()  
                    self.tablist.pop(k)
            
            if len(self.tablist) == 0:
                logger.info('quitting')
                gtk.main_quit()
                logger.info('gtk.main_quit done')
                return False
            else:
                return True
        
        
        def on_pause_queue(self,widget):
            self.manager_paused = widget.get_active()
        
        def on_delete_queue_element(self,widget):
            #selection = self.listwidget.get_selection()
            #selection.selected_foreach(self.delete_item)
            selection = self.listwidget.get_selection()
            model, selection = selection.get_selected_rows()

            for path in selection:
                iter = model.get_iter(path)
                model.remove(iter)
        
        def delete_item(self,treemodel,path,iter):
            self.queue.remove(iter)
        
        
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
            
            timeout_limit = 60 #seconds
            
            with gtk.gdk.lock:
                self.status_bar.set_text("Idle")
                
            while self.manager_running:                
                # If the pause button is pushed in, sleep
                if self.manager_paused:
                    with gtk.gdk.lock:
                        if self.status_bar.get_text() == "Idle":
                            self.status_bar.set_text("Queue Paused") 
                    time.sleep(1)
                    continue
                
                # Get the top file
                with gtk.gdk.lock:
                    iter = self.queue.get_iter_first()
                # If no files, sleep for 1s,
                if iter is None:
                    with gtk.gdk.lock:
                        self.status_bar.set_text("Idle")
                    time.sleep(1)
                    continue
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Reading file path from the queue:")    
                    path = "".join(self.queue.get(iter,0))
                    self.queue.remove(iter)
                
                print 'Queue Manager: got a path:',path
                
                # Transition devices to buffered mode
                transition_list = {}                
                start_time = time.time()
                error = {}
                with gtk.gdk.lock:
                    self.status_bar.set_text("Transitioning to Buffered")
                    #self.tab.setup_buffered_trigger()
                    for k,v in self.tablist.items():
                        # do we need to transition this device?
                        with h5py.File(path,'r') as hdf5_file:
                            group = hdf5_file['devices/'].get(k)
                            if group != None:
                                v.transition_to_buffered(path)
                                transition_list[k] = v
                
                devices_in_use = transition_list.copy()
                
                while len(transition_list) > 0:
                    for k,v in transition_list.items():
                        if v.transitioned_to_buffered:
                            transition_list.pop(k)
                        
                        if v.error != '':
                            error[k] = v.error
                            transition_list.pop(k)
                            break
                    end_time = time.time()
                    if end_time - start_time > timeout_limit:
                        break
                    if error:
                        break
                    time.sleep(0.1)
                        
                
                # Handle if we broke out of loop due to timeout
                if end_time - start_time > timeout_limit or len(error) > 0:
                    # It took too long, pause the queue, re add the path to the top of the queue, and set a status message!
                    self.manager_paused = True
                    self.queue_pause_button.set_state(True)
                    self.queue.prepend([path])
                    
                    with gtk.gdk.lock:
                        if end_time - start_time > timeout_limit:
                            self.status_bar.set_text("Device programming timed out. Queue Paused...")
                        else:
                            self.status_bar.set_text("One or more devices is in an error state. Queue Paused...")
                            
                    # Abort the run for other devices
                    for k,v in devices_in_use.items():
                        #if k not in transition_list:
                        v.abort_buffered()
                    continue
                
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Preparing to start sequence...(program time: "+str(end_time - start_time)+"s")
                
                #print "Devices programmed"
                self.tablist["pulseblaster_0"].start()
                #self.tablist["pulseblaster_1"].start()
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Running...(program time: "+str(end_time - start_time)+"s")
                
                #force status update
                self.tablist["pulseblaster_0"].status_monitor()
                
                # This is a nit of a hack, but will become irrelevant once we have a proper method of determining the experiment execution state
                # Eg, monitoring a digital flag!
                time.sleep(5)
                
                while self.tablist["pulseblaster_0"].status["waiting"] is not True:
                    if not self.manager_running:
                        break
                    #print 'waiting'
                    time.sleep(0.05)
                
                with gtk.gdk.lock:
                    self.status_bar.set_text("Sequence done, saving data...")
                
                
                with gtk.gdk.lock:
                    with h5py.File(path,'a') as hdf5_file:
                        try:
                            data_group = hdf5_file['/'].create_group('data')
                        except Exception as e:
                            raise
                            print str(e)
                            print 'failed creating data group'
                    
                    for k,v in devices_in_use.items():
                        v.transition_to_static()
                        
                
                while len(devices_in_use) > 0:
                    for k,v in devices_in_use.items():
                        logging.debug("the following tab has not transitioned to static: "+k)
                        if v.static_mode:
                            devices_in_use.pop(k)    
                                                       
                with gtk.gdk.lock:
                    self.status_bar.set_text("Idle")
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
            print 'Request handler: ', message
            self.wfile.write(message)
            self.wfile.close()
            
    def process_request(h5_filepath):
        #print 'Request Handler: got a filepath:', h5_filepath
        # check connection table
        try:
            new_conn = ConnectionTable(h5_filepath)
        except:
            return "H5 file not accessible to Control PC\n"
            
        if app.connection_table.compare_to(new_conn):  
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
#if __name__ == "__main__":
    gtk.gdk.threads_init()
    app = BLACS()
    # Make it not look so terrible (if icons and themes are installed):
    gtk.settings_get_default().set_string_property('gtk-icon-theme-name','gnome-human','')
    #gtk.settings_get_default().set_string_property('gtk-theme-name','Clearlooks','')
    gtk.settings_get_default().set_string_property('gtk-font-name','ubuntu 10','')
    #gtk.settings_get_default().set_long_property('gtk-button-images',False,'')
    gtk.settings_get_default().props.gtk_button_images = True
    serverthread = threading.Thread(target = HTTPServer(('', port),RequestHandler).serve_forever)
    serverthread.daemon = True # process will end if only daemon threads are left
    serverthread.start()
    with gtk.gdk.lock:
        gtk.main()
        
