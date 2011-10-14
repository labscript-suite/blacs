import pygtk
import gtk
import urllib
import threading
import cgi
import time
import numpy
import socket
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

# Connection Table Code
from connections import *

# Hardware Interface Imports
from hardware_interfaces import *
for device in device_list:    
    exec("from hardware_interfaces."+device+" import "+device)
    


# Virtual Devices Import
#needs to be dynamic import
from virtual_devices.shutter import *


# Temporary imports to demonstrate plotting
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
#from matplotlib.backends.backend_gtk import FigureCanvasGTK as FigureCanvas
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
        treeselection = self.listwidget.get_selection()
        treeselection.set_mode(gtk.SELECTION_MULTIPLE)
        
		# Need to connect signals!
        self.builder.connect_signals(self)
        
        ######################################
        # TODO: Load From Connection Table   #
        ######################################
        
        # Get H5 file        
        h5_file = "connectiontables\\"+socket.gethostname()+".h5"
        
        # Create Connection Table
        self.connection_table = ConnectionTable(h5_file)
        
        # Instantiate Devices from Connection Table, Place in Array        
        attached_devices = self.connection_table.find_devices(device_list)
        
        self.settings_dict = {"ni_pcie_6363_0":{"device_name":"ni_pcie_6363_0","connection_table":self.connection_table},
                              "pulseblaster_0":{"device_name":"pulseblaster_0","device_num":0,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0","connection_table":self.connection_table},
                              "pulseblaster_1":{"device_name":"pulseblaster_1","device_num":1,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0","connection_table":self.connection_table},
                              "novatechdds9m_0":{"device_name":"novatechdds9m_0","COM":"com10","connection_table":self.connection_table},
                              "novatechdds9m_1":{"device_name":"novatechdds9m_1","COM":"com13","connection_table":self.connection_table},
                              "andor_ixon":{"device_name":"andor_ixon","connection_table":self.connection_table}
                             }
        self.tablist = {}
        for k,v in attached_devices.items():
            self.tablist[k] = globals()[v](self.notebook,self.settings_dict[k])
                
        # Open BLACS Config File
        # Load Virtual Devices
        
        ############
        # END TODO #
        ############
        
        #self.shutter_tab = globals()["shutter"]([self.tab.get_child("DO",1),self.tab.get_child("DO",5),self.tab.get_child("DO",27),self.tab.get_child("DO",13)])
        #self.notebook.append_page(self.shutter_tab.tab,gtk.Label("shutter_0"))
        #
        # Setup a quick test of plotting data!
        #
        vbox = gtk.VBox()

        fig = Figure(figsize=(5,4), dpi=100)
        ax = fig.add_subplot(111)
        t = numpy.arange(0,1000,1)
        s = numpy.arange(-10,11,21/1000.)

        ax.plot(t,s)
        self.ax = ax
        self.figure = fig

        canvas = FigureCanvas(fig)  # a gtk.DrawingArea
        self.canvas = canvas
        vbox.pack_start(canvas)
        self.notebook.append_page(vbox,gtk.Label("graph!"))
        
        #self.tab.request_analog_input(0,10000,self.update_plot)
        
        # Setup the sequence manager thread
        # This thread will listen on a specific port, and will add items it recieves to a queue
        # We will add an idle callback function which check the queue for entries, and starts an 
        # experimental run if appropriate
        
        
        self.window.show_all()
        
        # Start Queue Manager
        self.manager_running = True
        self.manager_paused = False
        gtk.gdk.threads_leave()
        self.manager = threading.Thread(target = self.manage).start()
        gtk.gdk.threads_enter()
        
    def update_plot(self,channel,data,rate):
        line = self.ax.get_lines()[0]
        #print line
        line.set_ydata(data[0,:])
        #self.ax.draw_artist(line)
        # just redraw the axes rectangle
        #self.canvas.blit(self.ax.bbox)
        #print line.data
        #self.ax.plot(data[1,:],data[0,:])
        self.canvas.draw_idle()
        pass
    
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
    
    def on_window_destroy(self,widget):
        self.destroy()
    
    def on_delete_event(self,a,b):
        self.destroy()
    
    def destroy(self):
        if not self.exiting:
            self.exiting = True
            self.manager_running = False
            self.window.hide()
            
            for k,v in self.tablist.items():
                v.destroy()
            
            gtk.main_quit()

        
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
        # While the program is running!
        while self.manager_running:
            # If the pause button is pushed in, sleep
            if self.manager_paused:
                time.sleep(1)
                continue
            
            # Get the top file
            iter = self.queue.get_iter_first()
            # If no files, sleep for 1s,
            if iter is None:
                #print 'sleeping'
                time.sleep(1)
                continue
            path = "".join(self.queue.get(iter,0))
            self.queue.remove(iter)
            
            print path
            
            # Transition devices to buffered mode
            gtk.gdk.threads_enter()
            #self.tab.setup_buffered_trigger()
            for k,v in self.tablist.items():
                v.transition_to_buffered(path)
            
            self.tablist["pulseblaster_0"].start()
           
            #force status update
            self.tablist["pulseblaster_0"].status_monitor()
            gtk.gdk.threads_leave()
            
            while self.tablist["pulseblaster_0"].status["waiting"] is not True:
                if not self.manager_running:
                    break
                #print 'waiting'
                time.sleep(0.05)
            
            gtk.gdk.threads_enter()
            for k,v in self.tablist.items():
                v.transition_to_static()
                
            self.tablist["pulseblaster_0"].start()
            gtk.gdk.threads_leave()
            #print 'started'
            

def do_stuff(h5_filepath):
    #print 'got a filepath:', h5_filepath
    
    # check connection table
    try:
        new_conn = ConnectionTable(h5_filepath)
    except:
        return "H5 file not accessible to Control PC"
        
    if app.connection_table.compare_to(new_conn):    
        app.queue.append([h5_filepath])
        message = "Experiment added successfully"
        if app.manager_paused:
            message += "\nWarning: Queue is currently paused"
            
        if not app.manager_running:
            message += "\nError: Queue is not running"
        return message
    else:
        message =  "Connection table of your file is not a subset of the experimental control apparatus.\n"
        message += "You may have:\n"
        message += "    Submitted your file to the wrong control PC\n"
        message += "    Added new channels to your h5 file, without rewiring the experiment and updating the control PC\n"
        message += "    Renamed a channel at the top of your script\n"
        message += "    Submitted an old file, and the experiment has since been rewired\n"
        message += "\n"
        message += "Please verify your experiment script matches the current experiment configuration, and try again"
        return message
    
        
class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        length = int(self.headers.getheader('content-length'))
        postvars = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
        h5_filepath =  postvars['filepath'][0]
        gtk.gdk.threads_enter()
        message = do_stuff(h5_filepath)
        gtk.gdk.threads_leave()
        self.wfile.write(message)


port = 42517
if __name__ == "__main__":
    app = BLACS()
    settings = gtk.settings_get_default()
    settings.props.gtk_button_images = True
    gtk.threads_init()
    
    serverthread = threading.Thread(target = HTTPServer(('', port),RequestHandler).serve_forever)
    serverthread.daemon = True # process will end if only daemon threads are left
    serverthread.start()
    gtk.gdk.threads_enter()
    gtk.main()
    gtk.gdk.threads_leave()
        