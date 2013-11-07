import os
from BLACS.tab_base_classes import Worker, define_state
from BLACS.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  

from BLACS.device_base_class import DeviceTab

from PySide.QtUiTools import QUiLoader

class camera(DeviceTab):
    def initialise_GUI(self):
        layout = self.get_tab_layout()
        ui_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'camera.ui')
        self.ui = QUiLoader().load(ui_filepath)
        layout.addWidget(self.ui)
        
        port = int(self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection)
        self.ui.port_label.setText(str(port)) 
        
        self.ui.is_responding.setVisible(False)
        self.ui.is_not_responding.setVisible(False)
        
    def get_save_data(self):
        return {'host': str(self.ui.host_lineEdit.text()), 'use_zmq': self.ui.use_zmq_checkBox.isChecked()}
    
    def restore_save_data(self, save_data):
        print 'restore save data running'
        if save_data:
            host = save_data['host']
            self.ui.host_lineEdit.setText(host)
            if 'use_zmq' in save_data:
                use_zmq = save_data['use_zmq']
                self.ui.use_zmq_checkBox.setChecked(use_zmq)
        else:
            self.logger.warning('No previous front panel state to restore')
            
    def initialise_workers(self):
        worker_initialisation_kwargs = {'port': self.ui.port_label.text(),
                                        'host': str(self.ui.host_lineEdit.text()),
                                        'use_zmq': self.ui.use_zmq_checkBox.isChecked()}
        self.create_worker("main_worker", CameraWorker, worker_initialisation_kwargs)
        self.primary_worker = "main_worker"
    
    @define_state(MODE_MANUAL,True)
    def initialise_device(self):
        # Run worker
        responding = yield(self.queue_work(self._primary_worker,'initialise'))
        self.update_responding_indicator(responding)
        # Connect signals; user input should only so anything after the device has been initialised:
        self.ui.host_lineEdit.returnPressed.connect(self.update_settings_and_check_connectivity)
        self.ui.use_zmq_checkBox.toggled.connect(self.update_settings_and_check_connectivity)
        self.ui.check_connectivity_pushButton.clicked.connect(self.update_settings_and_check_connectivity)
        
    @define_state(MODE_MANUAL, queue_state_indefinitely=True, delete_stale_states=True)
    def update_settings_and_check_connectivity(self, *args):
        self.ui.saying_hello.setVisible(True)
        self.ui.is_responding.setVisible(False)
        self.ui.is_not_responding.setVisible(False)
        kwargs = self.get_save_data()
        responding = yield(self.queue_work(self.primary_worker, 'update_settings_and_check_connectivity', **kwargs))
        self.update_responding_indicator(responding)
        
    def update_responding_indicator(self, responding):
        self.ui.saying_hello.setVisible(False)
        if responding:
            self.ui.is_responding.setVisible(True)
            self.ui.is_not_responding.setVisible(False)
        else:
            self.ui.is_responding.setVisible(False)
            self.ui.is_not_responding.setVisible(True)
            
class CameraWorker(Worker):
    def init(self):#, port, host, use_zmq):
#        self.port = port
#        self.host = host
#        self.use_zmq = use_zmq
        global socket; import socket
        global zmq; import zmq
        global subproc_utils; import subproc_utils
        global shared_drive; import shared_drive
        
    def initialise(self):
        if not self.host:
            return False
        if not self.use_zmq:
            return self.initialise_sockets(self.host, self.port)
        else:
            response = subproc_utils.zmq_get_raw(self.port, self.host, data='hello')
            if response == 'hello':
                return True
            else:
                raise Exception('invalid response from server: ' + str(response))
        self.connected = True
        
    def update_settings_and_check_connectivity(self, host, use_zmq):
        self.host = host
        self.use_zmq = use_zmq
        return self.initialise()
        
    def initialise_sockets(self, host, port):
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
    
    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        h5file = shared_drive.path_to_agnostic(h5file)
        if not self.use_zmq:
            return self.transition_to_buffered_sockets(h5file,self.host, self.port)
        response = subproc_utils.zmq_get_raw(self.port, self.host, data=h5file)
        if response != 'ok':
            raise Exception('invalid response from server: ' + str(response))
        response = subproc_utils.zmq_get_raw(self.port, self.host, timeout = 10)
        if response != 'done':
            raise Exception('invalid response from server: ' + str(response))
        return {} # indicates final values of buffered run, we have none
        
    def transition_to_buffered_sockets(self, h5file, host, port):
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
        return {} # indicates final values of buffered run, we have none
        
    def transition_to_manual(self):
        if not self.use_zmq:
            return self.transition_to_manual_sockets(self.host, self.port)
        response = subproc_utils.zmq_get_raw(self.port, self.host, 'done')
        if response != 'ok':
            raise Exception('invalid response from server: ' + str(response))
        response = subproc_utils.zmq_get_raw(self.port, self.host, timeout = 10)
        if response != 'done':
            raise Exception('invalid response from server: ' + str(response))
        return True # indicates success
        
    def transition_to_manual_sockets(self, host, port):
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
        return True # indicates success
        
    def abort_buffered(self):
        return self.abort()
        
    def abort_transition_to_buffered(self):
        return self.abort()
    
    def abort(self):
        if not self.use_zmq:
            return self.abort_sockets(self.host, self.port)
        response = subproc_utils.zmq_get_raw(self.port, self.host, 'abort')
        if response != 'done':
            raise Exception('invalid response from server: ' + str(response))
        return True # indicates success 
        
    def abort_sockets(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(120)
        s.connect((host, int(port)))
        s.send('abort\r\n')
        response = s.recv(1024)
        if not 'done' in response:
            s.close()
            raise Exception(response)
        return True # indicates success 
        
    def shutdown(self):
        return
        
