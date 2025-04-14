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
import threading
import time
import sys
import queue

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from qtutils import *
from zprocess import TimeoutError, raise_exception_in_thread
from zprocess.security import AuthenticationFailure
from labscript_utils.ls_zprocess import zmq_get
from socket import gaierror
import labscript_utils.shared_drive
from labscript_utils.qtwidgets.elide_label import elide_label
from blacs import BLACS_DIR


class AnalysisSubmission(object):        
    
    icon_names = {'checking': ':/qtutils/fugue/hourglass',
                  'online': ':/qtutils/fugue/tick',
                  'offline': ':/qtutils/fugue/exclamation', 
                  '': ':/qtutils/fugue/status-offline'}

    tooltips = {'checking': 'Checking...',
                'online': 'Server is responding',
                'offline': 'Server not responding',
                '': 'Disabled'}  
    
    def __init__(self, BLACS, blacs_ui):
        self.inqueue = queue.Queue()
        self.BLACS = BLACS
        self.port = int(self.BLACS.exp_config.get('ports', 'lyse'))
        
        self._ui = UiLoader().load(os.path.join(BLACS_DIR, 'analysis_submission.ui'))
        blacs_ui.analysis.addWidget(self._ui)
        self._ui.frame.setMinimumWidth(blacs_ui.queue_controls_frame.sizeHint().width())
        elide_label(self._ui.resend_shots_label, self._ui.failed_to_send_frame.layout(), Qt.ElideRight)
        
        self._waiting_for_submission = {}
        self.failure_reason = {}
        self.send_to_server = False
        self.server = ''
        self.time_of_last_connectivity_check = 0
        self.server_online = {}
        
        # connect signals
        self._ui.send_to_server.toggled.connect(lambda state: self._set_send_to_server(state))
        self._ui.server.editingFinished.connect(lambda: self._set_server(self._ui.server.text()))
        self._ui.clear_unsent_shots_button.clicked.connect(lambda _: self.clear_waiting_files())
        self._ui.retry_button.clicked.connect(lambda _: self.check_retry())


        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
    def restore_save_data(self,data):
        if "server" in data:
            self.server = data["server"]
        if "send_to_server" in data:
            self.send_to_server = data["send_to_server"]
        if "waiting_for_submission" in data:
            self._waiting_for_submission = dict(data["waiting_for_submission"])
        self.inqueue.put(['save data restored', None, None])
        self.check_retry()
            
    def get_save_data(self):
        return {"waiting_for_submission": dict(self._waiting_for_submission),
                "server": self.server,
                "send_to_server": self.send_to_server
               }
    
    def _waiting_for_submission_len(self):
        length = 0
        for k, v in enumerate(self._waiting_for_submission):
            length += len(v)
        
        return length
    
    def _set_send_to_server(self,value):
        self.send_to_server = value
        
    def _set_server(self,server):
        self.server = server
        self.check_retry()
    
    @property
    @inmain_decorator(True)
    def send_to_server(self):
        return self._send_to_server
        
    @send_to_server.setter
    @inmain_decorator(True)
    def send_to_server(self, value):
        self._send_to_server = bool(value)
        self._ui.send_to_server.setChecked(self.send_to_server)
        if self.send_to_server:
            self._ui.server.setEnabled(True)
            self._ui.server_online.show()
            self.check_retry()
        else:
            self.clear_waiting_files()
            self._ui.server.setEnabled(False)
            self._ui.server_online.hide()
    
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
    def server_online(self, value):

        self._server_online = value        

        status = 'online'
        tooltip = ''
        for server in self._waiting_for_submission:
            
            if server not in value:
                value[server] = ''

            v = value[server]
            
            if v == 'offline':
                status = 'offline'
            if tooltip != '':
                tooltip += '\n'
                
            tip = self.tooltips.get(status, 'Invalid message {}'.format(status))
            tooltip += 'Server {} status: {}'.format(server, tip)
            
            if server not in self.failure_reason:
                self.failure_reason[server] = None
                tooltip += 'Server not checked yet'
            
            if self.failure_reason[server] is not None:
                tooltip += '[[{}]]'.format(self.failure_reason[server])

        icon = QIcon(self.icon_names.get(status, ':/qtutils/fugue/exclamation-red'))
        pixmap = icon.pixmap(QSize(16, 16))

        # Update GUI:
        self._ui.server_online.setPixmap(pixmap)
        self._ui.server_online.setToolTip(tooltip)
        self.update_waiting_files_message()


    @inmain_decorator(True)
    def update_waiting_files_message(self):

        message = ''
        failed = False
        for server, shots in self._waiting_for_submission.items():
            length = len(shots)
            
            # The server may never have been checked
            if server not in self.server_online:
                self._server_online[server] = ''
                
            # if there is only one shot and we haven't encountered failure yet, do
            # not show the error frame:
            if (self.server_online[server] == 'checking') and (length == 1) and not self._ui.failed_to_send_frame.isVisible():
                pass
            elif length:
                if self.server_online[server] == 'checking':
                    message += 'Server {}: Sending {} shot(s)...'.format(server, length)
                else:
                    message += 'Server {}: {} shot(s) to send...'.format(server, length)

        if failed and self._waiting_for_submission_len():
            self._ui.failed_to_send_frame.show()
        else:
            self._ui.failed_to_send_frame.hide()

        self._ui.resend_shots_label.setText(message)
        
        self._ui.retry_button.show()

    def get_queue(self):
        return self.inqueue

    @inmain_decorator(True)
    def clear_waiting_files(self):
        self._waiting_for_submission = {}
        self.update_waiting_files_message()

    @inmain_decorator(True)
    def check_retry(self):
        self.inqueue.put(['check/retry', None, None])

    def mainloop(self):
        self._mainloop_logger = logging.getLogger('BLACS.AnalysisSubmission.mainloop')
        # Ignore signals until save data is restored:
        while self.inqueue.get()[0] != 'save data restored':
            pass
        timeout = 10
        while True:
            try:
                try:
                    signal, data, lyse_host = self.inqueue.get(timeout=timeout)
                except queue.Empty:
                    continue

                if signal == 'file':
                    if self.send_to_server:
                        
                        lyse_host = lyse_host if lyse_host != '' else self.server                       
                        
                        if lyse_host not in self._waiting_for_submission:
                            self._waiting_for_submission[lyse_host] = []
                        
                        self._waiting_for_submission[lyse_host].append(data)
                        
                        self.submit_waiting_files()
                elif signal == 'close':
                    break
                elif signal == 'save data restored':
                    continue
                elif signal == 'check/retry': 
                    self.submit_waiting_files()
                else:
                    raise ValueError('Invalid signal: %s'%str(signal))

                self._mainloop_logger.info('Processed signal: %s'%str(signal))
            except Exception:
                # Raise in a thread for visibility, but keep going
                raise_exception_in_thread(sys.exc_info())
                self._mainloop_logger.exception("Exception in mainloop, continuing")
            
    def check_connectivity(self):
        
        server_online = {}

        for server in self._waiting_for_submission:
            send_to_server = self.send_to_server
            if send_to_server:       
                server_online[server] = 'checking'
                self.server_online = server_online # update GUI
                
                try:
                    response = zmq_get(self.port, server, 'hello', timeout=1)
                    self.failure_reason[k] = None
                except (TimeoutError, gaierror, AuthenticationFailure) as e:
                    success = False
                    self.failure_reason[k] = str(e)
                else:
                    success = (response == 'hello')
                    if not success:
                        self.failure_reason[k] = "unexpected reponse: %s" % str(response)
                    
                server_online[server] = 'online' if success else 'offline'
            else:
                server_online[server] = ''

        # update GUI
        self.server_online = server_online
    
        self.time_of_last_connectivity_check = time.time()

    def submit_waiting_files(self):
        
        server_online = {}
        for server, shots in self._waiting_for_submission.items():
            success = True

            while shots and success:
                path = shots[0]
                self.server = server
        
                self._mainloop_logger.info('Submitting run file %s.\n'%os.path.basename(path))
                data = {'filepath': labscript_utils.shared_drive.path_to_agnostic(path)}

                server_online[server] = 'checking'
                self.server_online = server_online # update GUI

                try:
                    response = zmq_get(self.port, server, data, timeout=1)
                    self.failure_reason[server] = None
                except (TimeoutError, gaierror, AuthenticationFailure) as e:
                    success = False
                    self.failure_reason[server] = str(e)
                else:
                    success = (response == 'added successfully')
                    if not success:
                        self.failure_reason[server] = "unexpected reponse: %s" % str(response)
                    try:
                        shots.pop(0) 
                    except IndexError:
                        # Queue has been cleared
                        pass
            
            server_online[server] = 'online' if success else 'offline'
            
        # update GUI
        self.server_online = server_online
        
        self.time_of_last_connectivity_check = time.time()
        
