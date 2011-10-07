import pygtk
import gtk
import urllib, threading, cgi
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import spinapi


imp_test="ni_pcie_6363"
exec("from hardware_interfaces."+imp_test+" import *")
from hardware_interfaces.novatech_dds9m import novatech_dds9m
from hardware_interfaces.pulseblaster import pulseblaster

import numpy
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
#from matplotlib.backends.backend_gtk import FigureCanvasGTK as FigureCanvas
from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas



#needs to be dynamic import
from virtual_devices.shutter import *

class BLACS(object):       
    def __init__(self):
        self.exiting = False
        
        self.builder = gtk.Builder()
        self.builder.add_from_file('main_interface.glade')
        self.builder.connect_signals(self)
        self.window = self.builder.get_object("window")
        self.notebook = self.builder.get_object("notebook1")
        self.queue = self.builder.get_object("remote_liststore")
        
		# Need to connect signals!
        self.builder.connect_signals(self)
        
        
        # Here we pretend we loaded a H5 file, and found a ni_pcie_6363 device!
        
        
        self.tab = globals()[imp_test]({"device_name":"ni_pcie_6363_0"})
        self.notebook.append_page(self.tab.tab,gtk.Label(imp_test+"_0"))
        
        self.do_test = self.tab.get_child("DO",2)
        self.do_test1 = self.tab.get_child("DO",16)
        self.do_widget = self.builder.get_object("test_toggle")
        self.do_test.add_callback(self.update_test)
        self.do_test1.add_callback(self.update_test)
        
        self.shutter_tab = globals()["shutter"]([self.tab.get_child("DO",1),self.tab.get_child("DO",5),self.tab.get_child("DO",27),self.tab.get_child("DO",13)])
        self.notebook.append_page(self.shutter_tab.tab,gtk.Label("shutter_0"))
        
        #self.novatech_0_tab = globals()["novatech_dds9m"](self.notebook,{"device_name":"novatechdds9m_0","COM":"com10"})
        
        
        self.novatech_1_tab = globals()["novatech_dds9m"](self.notebook,{"device_name":"novatechdds9m_0","COM":"com1"})
        
                
        self.pulseblaster_0_tab = globals()["pulseblaster"]({"device_name":"pulseblaster_0","device_num":0,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"})
        self.notebook.append_page(self.pulseblaster_0_tab.tab,gtk.Label("pulseblaster_0"))        
        self.pulseblaster_0_tab.set_defaults()
        
        #self.pulseblaster_1_tab = globals()["pulseblaster"]({"device_name":"pulseblaster_1","device_num":1,"f0":"20.0","a0":"0.15","p0":"0","f1":"20.0","a1":"0.35","p1":"0"})
        #self.notebook.append_page(self.pulseblaster_1_tab.tab,gtk.Label("pulseblaster_1"))        
        #self.pulseblaster_1_tab.set_defaults()
        
        
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
        
        self.tab.request_analog_input(0,10000,self.update_plot)
        
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

    def update_test(self,a):
        if self.do_widget.get_active() != a.state:
            self.do_widget.set_active(a.state)
			
    def toggle_test(self,widget):
        self.do_test.update_value(widget.get_active())
        self.do_test1.update_value(widget.get_active())
    
    def on_window_destroy(self,widget):
        self.destroy()
    
    def on_delete_event(self,a,b):
        self.destroy()
    
    def destroy(self):
        if not self.exiting:
            self.exiting = True
            self.manager_running = False
            self.window.hide()
            self.tab.destroy()
            self.pulseblaster_0_tab.destroy()
            #self.pulseblaster_1_tab.destroy()
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
            
            # Transition devices to buffered mode!
            #gtk.gdk.threads_leave()
            # Create Event
            #pb0_event = threading.Event()
            #threading.Thread(target = self.pulseblaster_0_tab.transition_to_buffered, args=(path, pb0_event)).start()
            #ni0_event = threading.Event()
            #threading.Thread(target = self.tab.transition_to_buffered,args=(path,ni0_event)).start()
            #nt1_event = threading.Event()
            #gtk.gdk.threads_enter()
            gtk.gdk.threads_enter()
            #self.tab.setup_buffered_trigger()
            self.pulseblaster_0_tab.transition_to_buffered(path)
            print 'pb_event done'
            self.tab.transition_to_buffered(path)
            print 'ni_event done'
            self.novatech_1_tab.transition_to_buffered(path)
            print 'nt_event done'
            
            # Wait for programming to complete!
            #pb0_event.wait()
            
            #ni0_event.wait()
            
            #print 'done programming!'
            self.pulseblaster_0_tab.start()
            #self.tab.start_buffered()
            
            #time.sleep(0.2)
            #force status update
            self.pulseblaster_0_tab.status_monitor()
            gtk.gdk.threads_leave()
            
            while self.pulseblaster_0_tab.status["waiting"] is not True:
                if not self.manager_running:
                    break
                #print 'waiting'
                time.sleep(0.05)
            
            gtk.gdk.threads_enter()
            self.pulseblaster_0_tab.transition_to_static()
            self.tab.transition_to_static()
            self.novatech_1_tab.transition_to_static()
            #print 'transitioning back'
            self.pulseblaster_0_tab.start()
            gtk.gdk.threads_leave()
            #print 'started'
            

def do_stuff(h5_filepath):
    #print 'got a filepath:', h5_filepath
    gtk.gdk.threads_enter()
    app.queue.append([h5_filepath])
    gtk.gdk.threads_leave()
        
class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        length = int(self.headers.getheader('content-length'))
        postvars = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
        h5_filepath =  postvars['filepath'][0]
        do_stuff(h5_filepath)
        self.wfile.write('response_data!')


port = 42517
if __name__ == "__main__":
    app = BLACS()
    
    gtk.threads_init()
    
    serverthread = threading.Thread(target = HTTPServer(('', port),RequestHandler).serve_forever)
    serverthread.daemon = True # process will end if only daemon threads are left
    serverthread.start()
    gtk.gdk.threads_enter()
    gtk.main()
    gtk.gdk.threads_leave()
        