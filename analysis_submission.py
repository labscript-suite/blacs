#####################################################################
#                                                                   #
# /analysis_submission.py                                           #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import logging
import os
import Queue
import threading
import time
import sys

if 'PySide' in sys.modules.copy():
    from PySide.QtCore import *
    from PySide.QtGui import *
else:
    from PyQt4.QtCore import *
    from PyQt4.QtGui import *
    
from qtutils import *
from zprocess import zmq_get
import labscript_utils.shared_drive

class AnalysisSubmission(object):        
    def __init__(self, BLACS, blacs_ui):
        self.inqueue = Queue.Queue()
        self.BLACS = BLACS
        self.port = int(self.BLACS.exp_config.get('ports', 'lyse'))
        self._send_to_server = False
        self._server = ''
        self._server_online = 'offline'
        
        self._ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'analysis_submission.ui'))
        blacs_ui.analysis.addWidget(self._ui)
        # connect signals
        self._ui.send_to_server.toggled.connect(lambda state:self._set_send_to_server(state))
        self._ui.server.editingFinished.connect(lambda: self._set_server(self._ui.server.text()))
        
        self._waiting_for_submission = []
        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
        self.checking_thread = threading.Thread(target=self.check_connectivity_loop)
        self.checking_thread.daemon = True
        self.checking_thread.start()
    
    def restore_save_data(self,data):
        if "server" in data:
            self.server = data["server"]
        if "send_to_server" in data:
            self.send_to_server = data["send_to_server"]
        if "waiting_for_submission" in data:
            self._waiting_for_submission = list(data["waiting_for_submission"])
            self.inqueue.put(['try again', None])
            
    def get_save_data(self):
        return {"waiting_for_submission":list(self._waiting_for_submission),
                "server":self.server,
                "send_to_server":self.send_to_server
               }
    
    def _set_send_to_server(self,value):
        self.send_to_server = value
        
    def _set_server(self,server):
        self.server = server
    
    @property
    @inmain_decorator(True)
    def send_to_server(self):
        return self._send_to_server
        
    @send_to_server.setter
    @inmain_decorator(True)
    def send_to_server(self,value):
        self._send_to_server = bool(value)
        self._ui.send_to_server.setChecked(self.send_to_server)
        if not self.send_to_server:
            self.inqueue.put(['clear', None])
    
    @property
    @inmain_decorator(True)
    def server(self):
        return str(self._server)
        
    @server.setter    
    @inmain_decorator(True)
    def server(self,value):
        self._server = value
        self._ui.server.setText(self.server)
        
    @property
    @inmain_decorator(True)
    def server_online(self):
        return self._server_online
        
    @server_online.setter
    @inmain_decorator(True)
    def server_online(self,value):
        self._server_online = str(value)
        
        # resend any files not sent
        if self.server_online:
            self.inqueue.put(['try again', None])
        
        # update GUI
        self._ui.server_online.setText(value+(' (Files to send: %d)'%len(self._waiting_for_submission) if self._waiting_for_submission else ''))
    
    def get_queue(self):
        return self.inqueue
                 
    def mainloop(self):
        self._mainloop_logger = logging.getLogger('BLACS.AnalysisSubmission.mainloop') 
        while True:
            signal, data = self.inqueue.get()
            if signal == 'close':
                break
            elif signal == 'file':
                if self.send_to_server:
                    self._waiting_for_submission.append(data)
                self.submit_waiting_files()
            elif signal == 'try again':
                self.submit_waiting_files()
            elif signal == 'clear':
                self._waiting_for_submission = []
            else:
                self._mainloop_logger.error('Invalid signal: %s'%str(signal))
            
                   
    def check_connectivity_loop(self):
        time_to_sleep = 1
        #self._check_connectivity_logger = logging.getLogger('BLACS.AnalysisSubmission.check_connectivity_loop') 
        while True:
            # get the current host:
            host = self.server
            send_to_server = self.send_to_server
            if host and send_to_server:                
                try:
                    self.server_online = 'checking'
                    response = zmq_get(self.port, host, 'hello', timeout = 2)
                    if response == 'hello':
                        success = True
                    else:
                        success = False
                except Exception:
                    success = False
                    
                # update GUI
                self.server_online = 'online' if success else 'offline'
                
                # update how long we should sleep
                if success:
                    time_to_sleep = 10
                else:
                    time_to_sleep = 1
            else:
                self.server_online = ''
            
            # stop sleeping if the host changes
            for i in range(time_to_sleep*5):
                if host == self.server and send_to_server == self.send_to_server:
                    time.sleep(0.2)
                     
    def submit_waiting_files(self):
        if not self._waiting_for_submission:
            return
        while self._waiting_for_submission:
            path = self._waiting_for_submission[0]
            try:
                self._mainloop_logger.info('Submitting run file %s.\n'%os.path.basename(path))
                data = {'filepath': labscript_utils.shared_drive.path_to_agnostic(path)}
                response = zmq_get(self.port, self.server, data, timeout = 2)
                if response != 'added successfully':
                    raise Exception
            except:
                return
            else:
                self._waiting_for_submission.pop(0) 
        