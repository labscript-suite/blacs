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

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from qtutils import *
from zprocess import zmq_get, TimeoutError, raise_exception_in_thread
from socket import gaierror
import labscript_utils.shared_drive
from labscript_utils.qtwidgets.elide_label import elide_label

class AnalysisSubmission(object):        
    def __init__(self, BLACS, blacs_ui):
        self.inqueue = Queue.Queue()
        self.BLACS = BLACS
        self.port = int(self.BLACS.exp_config.get('ports', 'lyse'))
        
        self._ui = UiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'analysis_submission.ui'))
        blacs_ui.analysis.addWidget(self._ui)
        self._ui.frame.setMinimumWidth(blacs_ui.queue_controls_frame.sizeHint().width())
        elide_label(self._ui.resend_shots_label, self._ui.failed_to_send_frame.layout(), Qt.ElideRight)
        # connect signals
        self._ui.send_to_server.toggled.connect(lambda state: self._set_send_to_server(state))
        self._ui.server.editingFinished.connect(lambda: self._set_server(self._ui.server.text()))
        self._ui.clear_unsent_shots_button.clicked.connect(lambda _: self.clear_waiting_files())
        self._ui.retry_button.clicked.connect(lambda _: self.check_retry())

        self._waiting_for_submission = []
        self.server_online = 'offline'
        self.send_to_server = False
        self.server = ''
        self.time_of_last_connectivity_check = 0

        self.mainloop_thread = threading.Thread(target=self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
        # self.checking_thread = threading.Thread(target=self.check_connectivity_loop)
        # self.checking_thread.daemon = True
        # self.checking_thread.start()
    
    def restore_save_data(self,data):
        if "server" in data:
            self.server = data["server"]
        if "send_to_server" in data:
            self.send_to_server = data["send_to_server"]
        if "waiting_for_submission" in data:
            self._waiting_for_submission = list(data["waiting_for_submission"])
        self.inqueue.put(['save data restored', None])
        self.check_retry()
            
    def get_save_data(self):
        return {"waiting_for_submission":list(self._waiting_for_submission),
                "server":self.server,
                "send_to_server":self.send_to_server
               }
    
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
    def server_online(self,value):
        self._server_online = str(value)
        
        icon_names = {'checking': ':/qtutils/fugue/hourglass',
                      'online': ':/qtutils/fugue/tick',
                      'offline': ':/qtutils/fugue/exclamation', 
                      '': ':/qtutils/fugue/status-offline'}

        tooltips = {'checking': 'Checking...',
                    'online': 'Server is responding',
                    'offline': 'Server not responding',
                    '': 'Disabled'}

        icon = QIcon(icon_names.get(self._server_online, ':/qtutils/fugue/exclamation-red'))
        pixmap = icon.pixmap(QSize(16, 16))
        tooltip = tooltips.get(self._server_online, "Invalid server status: %s" % self._server_online)

        # Update GUI:
        self._ui.server_online.setPixmap(pixmap)
        self._ui.server_online.setToolTip(tooltip)
        self.update_waiting_files_message()


    @inmain_decorator(True)
    def update_waiting_files_message(self):
        # if there is only one shot and we haven't encountered failure yet, do
        # not show the error frame:
        if (self.server_online == 'checking') and (len(self._waiting_for_submission) == 1) and not self._ui.failed_to_send_frame.isVisible():
            return
        if self._waiting_for_submission:
            self._ui.failed_to_send_frame.show()
            if self.server_online == 'checking':
                self._ui.retry_button.hide()
                text = 'Sending %s shot(s)...' % len(self._waiting_for_submission)
            else:
                self._ui.retry_button.show()
                text = '%s shot(s) to send' % len(self._waiting_for_submission)
            self._ui.resend_shots_label.setText(text)
        else:
            self._ui.failed_to_send_frame.hide()

    def get_queue(self):
        return self.inqueue

    @inmain_decorator(True)
    def clear_waiting_files(self):
        self._waiting_for_submission = []
        self.update_waiting_files_message()

    @inmain_decorator(True)
    def check_retry(self):
        self.inqueue.put(['check/retry', None])

    def mainloop(self):
        self._mainloop_logger = logging.getLogger('BLACS.AnalysisSubmission.mainloop')
        # Ignore signals until save data is restored:
        while self.inqueue.get()[0] != 'save data restored':
            pass
        timeout = 10
        while True:
            try:
                try:
                    signal, data = self.inqueue.get(timeout=timeout)
                except Queue.Empty:
                    timeout = 10
                    # Periodic checking of connectivity and resending of files.
                    # Don't trigger a re-check if we already failed a connectivity
                    # check within the last second:
                    if (time.time() - self.time_of_last_connectivity_check) > 1:
                        signal = 'check/retry'
                    else:
                        continue
                if signal == 'check/retry':
                    self.check_connectivity()
                    if self.server_online == 'online':
                        self.submit_waiting_files()
                elif signal == 'file':
                    if self.send_to_server:
                        self._waiting_for_submission.append(data)
                        if self.server_online != 'online':
                            # Don't stack connectivity checks if many files are
                            # arriving. If we failed a connectivity check less
                            # than a second ago then don't check again.
                            if (time.time() - self.time_of_last_connectivity_check) > 1:
                                self.check_connectivity()
                            else:
                                # But do queue up a check for when we have
                                # been idle for one second:
                                timeout = 1
                        if self.server_online == 'online':
                            self.submit_waiting_files()
                elif signal == 'close':
                    break
                elif signal == 'save data restored':
                    continue
                else:
                    raise ValueError('Invalid signal: %s'%str(signal))

                self._mainloop_logger.info('Processed signal: %s'%str(signal))
            except Exception:
                # Raise in a thread for visibility, but keep going
                raise_exception_in_thread(sys.exc_info())
                self._mainloop_logger.exception("Exception in mainloop, continuing")
            
    def check_connectivity(self):
        host = self.server
        send_to_server = self.send_to_server
        if host and send_to_server:       
            self.server_online = 'checking'         
            try:
                response = zmq_get(self.port, host, 'hello', timeout=1)
            except (TimeoutError, gaierror):
                success = False
            else:
                success = (response == 'hello')
                
            # update GUI
            self.server_online = 'online' if success else 'offline'
        else:
            self.server_online = ''

        self.time_of_last_connectivity_check = time.time()

    def submit_waiting_files(self):
        success = True
        while self._waiting_for_submission and success:
            path = self._waiting_for_submission[0]
            self._mainloop_logger.info('Submitting run file %s.\n'%os.path.basename(path))
            data = {'filepath': labscript_utils.shared_drive.path_to_agnostic(path)}
            self.server_online = 'checking'
            try:
                response = zmq_get(self.port, self.server, data, timeout=1)
            except (TimeoutError, gaierror):
                success = False
            else:
                success = (response == 'added successfully')
                try:
                    self._waiting_for_submission.pop(0) 
                except IndexError:
                    # Queue has been cleared
                    pass
            if not success:
                break
        # update GUI
        self.server_online = 'online' if success else 'offline'
        self.time_of_last_connectivity_check = time.time()
        
