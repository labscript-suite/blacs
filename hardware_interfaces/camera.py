import os
import socket
import gtk
import h5py

from tab_base_classes import Tab, Worker, define_state

class camera(Tab):
    def __init__(self,notebook,settings,restart=False):
        self.destroy_complete = False
        self.transitioned_to_buffered = False
        self.static_mode = True
        Tab.__init__(self,CameraWorker,notebook,settings)
        self.settings = settings
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/camera.glade')
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text(self.settings["device_name"])
        self.camera_responding = self.builder.get_object('responding')
        self.camera_notresponding = self.builder.get_object('notresponding')
        self.host = self.builder.get_object('host')
        self.port = self.builder.get_object('port')
        self.viewport.add(self.toplevel)
        self.restore_front_panel_state()
        self.initialise_camera()
        self.builder.connect_signals(self)
    
    def get_front_panel_state(self):
        return {'host':str(self.host.get_text()),  'port': str(self.port.get_text())}
    
    def restore_front_panel_state(self):
        try:
            with h5py.File(os.path.join("connectiontables", socket.gethostname()+"_settings.h5"),'r') as hdf5_file:
                dataset = hdf5_file['front_panel/camera']
                for row in dataset:
                   name,host,port = row
                   if name == self.settings["device_name"]:
                        self.host.set_text(host)
                        self.port.set_text(port)
                        print host, port, 'SDFDSFSDLFHSKFHSDFKHSDKJHLFDLHJ'
                        return
                self.logger.warning('No entry for this device in saved front panel states')
        except:
            raise
            self.logger.warning('Couldn\'t restore front panel state')
            
    @define_state
    def destroy(self):        
        self.destroy_complete = True
        self.close_tab()
    
    @define_state
    def initialise_camera(self,button=None):
        self.queue_work('initialise_camera', self.host.get_text(), self.port.get_text())
        self.do_after('after_initialise_camera')
        
    def after_initialise_camera(self,_results):
        if _results:
            self.camera_responding.show()
            self.camera_notresponding.hide()
        else:
            self.camera_responding.hide()
            self.camera_notresponding.show()
    
    @define_state
    def transition_to_buffered(self,h5file):       
        self.transitioned_to_buffered = False
        self.queue_work('starting_experiment',h5file,self.host.get_text(),self.port.get_text())
        self.do_after('leave_transition_to_buffered')
    
    def leave_transition_to_buffered(self,_results):
        self.transitioned_to_buffered = True
        self.static_mode = False
       
    def abort_buffered(self):
        pass
        
    @define_state    
    def transition_to_static(self):
        # This must be called after all other tabs have done their stuff
        # already, we need to work out hoe to do that.
        self.queue_work('finished_experiment',self.host.get_text(),self.port.get_text())
        self.do_after('leave_transition_to_static')
    
    def leave_transition_to_static(self,_results):
        self.transitioned_to_buffered = False
        self.static_mode = True

class CameraWorker(Worker):

#    def init(self):
#        global socket; import socket
    
    def initialise_camera(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, int(port)))
        s.send('hello\r\n')
        response = s.recv(1024)
        s.close()
        if 'hello' in response:
            return True
        else:
            raise Exception('invalid response from server: ' + response)
            
    def starting_experiment(self,h5file,host,port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((host, int(port)))
        s.send('%s\r\n'%h5file)
        response = s.recv(1024)
        if not 'ok' in response:
            s.close()
            raise Exception(response)
        response = s.recv(1024)
        if not 'done' in response:
            s.close()
            raise Exception(response)
        
    def finished_experiment(self,host,port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((host, int(port)))
        s.send('done\r\n')
        response = s.recv(1024)
        if not 'ok' in response:
            s.close()
            raise Exception(response)
        response = s.recv(1024)
        if not 'done' in response:
            s.close()
            raise Exception(response)
    
        
        
