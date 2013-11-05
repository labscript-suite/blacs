from time import time

from BLACS.tab_base_classes import Worker, define_state
from BLACS.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  
from BLACS.device_base_class import DeviceTab

class rfblaster(DeviceTab):
    def initialise_GUI(self):
        # Capabilities 
        self.base_units =     {'freq':'Hz',        'amp':'%',         'phase':'Degrees'}
        self.base_min =       {'freq':500000,      'amp':0.0,         'phase':0}
        self.base_max =       {'freq':350000000.0, 'amp':99.99389648, 'phase':360}
        self.base_step =      {'freq':1000000,     'amp':1.0,         'phase':1}
        #TODO: Find out what the amp and phase precision is
        self.base_decimals =  {'freq':1,           'amp':3,           'phase':3}
        self.num_DDS = 2  

        # Create DDS Output objects
        dds_prop = {}
        for i in range(self.num_DDS): # 2 is the number of DDS outputs on this device
            dds_prop['dds %d'%i] = {}
            for subchnl in ['freq', 'amp', 'phase']:
                dds_prop['dds %d'%i][subchnl] = {'base_unit':self.base_units[subchnl],
                                                 'min':self.base_min[subchnl],
                                                 'max':self.base_max[subchnl],
                                                 'step':self.base_step[subchnl],
                                                 'decimals':self.base_decimals[subchnl]
                                                }
            dds_prop['dds %d'%i]['gate'] = {}
                
        # Create the output objects    
        self.create_dds_outputs(dds_prop)        
        # Create widgets for output objects
        dds_widgets,ao_widgets,do_widgets = self.auto_create_widgets()
        # and auto place the widgets in the UI
        self.auto_place_widgets(("DDS Outputs",dds_widgets))
        
        # Store the COM port to be used
        self.address = "http://" + str(self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection) + ":8080"
        
        # Create and set the primary worker
        self.create_worker("main_worker",RFBlasterWorker,{'address':self.address, 'num_DDS':self.num_DDS})
        self.primary_worker = "main_worker"

        # Set the capabilities of this device
        self.supports_remote_value_check(True)
        self.supports_smart_programming(False) 
        

class RFBlasterWorker(Worker):
    def init(self):
        exec 'from multipart_form import *' in globals()
        exec 'from numpy import *' in globals()
        global h5py; import h5_lock, h5py
        global urllib2; import urllib2
        global re; import re
        self.timeout = 30 #How long do we wait until we assume that the RFBlaster is dead? (in seconds)
    
    def initialise(self):
        # See if the RFBlaster answers
        urllib2.urlopen(self.address,timeout=self.timeout)
        
    def program_manual(self,values):
        form = MultiPartForm()
        for i in range(self.num_DDS):
            # Program the frequency, amplitude and phase
            form.add_field("a_ch%d_in"%i,str(values['dds %d'%i]['amp']*values['dds %d'%i]['gate']))
            form.add_field("f_ch%d_in"%i,str(values['dds %d'%i]['freq']*1e-6)) # method expects MHz
            form.add_field("p_ch%d_in"%i,str(values['dds %d'%i]['phase']))
            
        form.add_field("set_dds","Set device")
        # Build the request
        req = urllib2.Request(self.address)
        #raise Exception(form_values)
        body = str(form)
        req.add_header('Content-type', form.get_content_type())
        req.add_header('Content-length', len(body))
        req.add_data(body)
        response = str(urllib2.urlopen(req,timeout=self.timeout).readlines())
        return self.get_web_values(response)
        
    def transition_to_buffered(self,device_name,h5file,initial_values,fresh):
        with h5py.File(h5file,'r') as hdf5_file:
            group = hdf5_file['devices'][device_name]
            #Strip out the binary files and submit to the webserver
            form = MultiPartForm()
            self.final_values = {}
            finalfreq = zeros(self.num_DDS)
            finalamp = zeros(self.num_DDS)
            finalphase = zeros(self.num_DDS)
            for i in range(self.num_DDS):
                #Find the final value from the human-readable part of the h5 file to use for
                #the front panel values at the end
                self.final_values['dds %d'%i] = {'freq':group['TABLE_DATA']["freq%d"%i][-1],
                                                 'amp':group['TABLE_DATA']["amp%d"%i][-1]*100,
                                                 'phase':group['TABLE_DATA']["phase%d"%i][-1],
                                                 'gate':True
                                                }
                data = group['BINARY_CODE/DDS%d'%i].value
                form.add_file_content("pulse_ch%d"%i,"output_ch%d.bin"%i,data)
                
            form.add_field("upload_and_run","Upload and start")
            req = urllib2.Request(self.address)

            body = str(form)
            req.add_header('Content-type', form.get_content_type())
            req.add_header('Content-length', len(body))
            req.add_data(body)
            post_buffered_web_vals = self.get_web_values(str(urllib2.urlopen(req,timeout = self.timeout).readlines()))

            return self.final_values
                 
    def abort_transition_to_buffered(self):
        # TODO: untested (this is probably wrong...)
        form = MultiPartForm()
        #tell the rfblaster to stop
        form.add_field("halt","Halt execution")
        req = urllib2.Request(self.address)
        body = str(form)
        req.add_header('Content-type', form.get_content_type())
        req.add_header('Content-length', len(body))
        req.add_data(body)
        urllib2.urlopen(req,timeout=self.timeout)
    
    def abort_buffered(self):
        form = MultiPartForm()
        #tell the rfblaster to stop
        form.add_field("halt","Halt execution")
        req = urllib2.Request(self.address)
        body = str(form)
        req.add_header('Content-type', form.get_content_type())
        req.add_header('Content-length', len(body))
        req.add_data(body)
        urllib2.urlopen(req,timeout=self.timeout)
     
    def transition_to_manual(self):
        return True
     
    def get_web_values(self,page): 
        #prepare regular expressions for finding the values:
        search = re.compile(r'name="([fap])_ch(\d+?)_in"\s*?value="([0-9.]+?)"')
        webvalues = re.findall(search,page)
        
        register_name_map = {'f':'freq','a':'amp','p':'phase'}
        newvals = {}
        for i in range(self.num_DDS):
            newvals['dds %d'%i] = {}
        for register,channel,value in webvalues:
            newvals['dds %d'%int(channel)][register_name_map[register]] = float(value)
        for i in range(self.num_DDS):
            newvals['dds %d'%i]['gate'] = True
            newvals['dds %d'%i]['freq'] *= 1e6 # BLACS expects it in the base unit (Hz)
            
        return newvals
    
    def check_remote_values(self):
        #read the webserver page to see what values it puts in the form
        page = str(urllib2.urlopen(self.address,timeout=self.timeout).readlines())
        return self.get_web_values(page)       
        
    def shutdown(self):
        pass

if __name__ == '__main__':
    from PySide.QtCore import *
    from PySide.QtGui import *
    import sys,os
    from qtutils.widgets.dragdroptab import DragDropTabWidget
    from BLACS.connections import ConnectionTable
    
    
    class MyWindow(QWidget):
        
        def __init__(self,*args,**kwargs):
            QWidget.__init__(self,*args,**kwargs)
            self.are_we_closed = False
        
        def closeEvent(self,event):
            if not self.are_we_closed:        
                event.ignore()
                self.my_tab.destroy()
                self.are_we_closed = True
                QTimer.singleShot(1000,self.close)
            else:
                if not self.my_tab.destroy_complete: 
                    QTimer.singleShot(1000,self.close)                    
                else:
                    event.accept()
    
        def add_my_tab(self,tab):
            self.my_tab = tab
    
    app = QApplication(sys.argv)
    window = MyWindow()
    layout = QVBoxLayout(window)
    notebook = DragDropTabWidget()
    layout.addWidget(notebook)
    connection_table = ConnectionTable(os.path.join(os.path.dirname(os.path.realpath(__file__)),r'../example_connection_table.h5'))
    tab1 = rfblaster(notebook,settings = {'device_name': 'rfblaster_0', 'connection_table':connection_table})
    window.add_my_tab(tab1)
    window.show()
    def run():
        app.exec_()
        
    sys.exit(run())