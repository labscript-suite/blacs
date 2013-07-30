import os
import socket
import gtk

from tab_base_classes import Tab, Worker, define_state

class camera(Tab):
    def __init__(self,BLACS, notebook,settings,restart=False):
        self.destroy_complete = False
        self.static_mode = True
        Tab.__init__(self,BLACS,CameraWorker,notebook,settings)
        self.settings = settings
        self.device_name = self.settings["device_name"]
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/camera.glade')
        self.toplevel = self.builder.get_object('toplevel')
        self.builder.get_object('title').set_text(self.settings["device_name"])
        self.camera_responding = self.builder.get_object('responding')
        self.camera_notresponding = self.builder.get_object('notresponding')
        self.camera_working = self.builder.get_object('working')
        self.host = self.builder.get_object('host')
        self.port = self.builder.get_object('port')
        self.viewport.add(self.toplevel)
        self.restore_save_data()
        self.port.set_text(self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection)
        self.builder.connect_signals(self)
        host, port = self.host.get_text(), self.port.get_text()
        if host and port:
            self.initialise_camera()
        
    def get_save_data(self):
        return {'host':str(self.host.get_text())}
    
    def restore_save_data(self):
        save_data = self.settings['saved_data']
        if save_data:
            host = save_data['host']
            self.host.set_text(host)
        else:
            self.logger.warning('No previous front panel state to restore')
    
    @define_state
    def on_change_host(self,widget):
        # Save host into settings
        self.settings['saved_data'] = self.get_save_data()
        self.initialise_camera()        
    
    @define_state
    def destroy(self):        
        self.destroy_complete = True
        self.close_tab()
    
    @define_state
    def initialise_camera(self,button=None):
        self.camera_working.show()
        self.camera_notresponding.hide()
        self.camera_responding.hide()
        host, port = self.host.get_text(), self.port.get_text()
        self.queue_work('initialise_camera', host, port)
        self.do_after('after_initialise_camera')
        
    def after_initialise_camera(self,_results):
        if _results:
            self.camera_working.hide()
            self.camera_responding.show()
        else:
            self.camera_working.hide()
            self.camera_notresponding.show()
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):       
        self.queue_work('starting_experiment',h5file,self.host.get_text(),self.port.get_text())
        self.do_after('leave_transition_to_buffered', notify_queue)
    
    def leave_transition_to_buffered(self,notify_queue,_results):
        self.static_mode = False
        # Notify the queue manager thread that we've finished transitioning to buffered:
        notify_queue.put(self.device_name)
        
    def abort_buffered(self):
        # Nothing to do here:
        pass
        
    @define_state    
    def transition_to_static(self,notify_queue):
        self.queue_work('finished_experiment',self.host.get_text(),self.port.get_text())
        self.do_after('leave_transition_to_static',notify_queue)
    
    def leave_transition_to_static(self,notify_queue,_results):
        self.static_mode = True
        # Tell the queue manager that we're done:
        notify_queue.put(self.device_name)
        
        
class CameraWorker(Worker):

#    def init(self):
#        global socket; import socket
    
    def initialise_camera(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        assert port, 'No port number supplied.'
        assert host, 'No hostname supplied.'
        assert str(int(port)) == port, 'Port must be an integer.'
        s.settimeout(10)
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
        s.settimeout(120)
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
        s.settimeout(120)
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
    
        
        
