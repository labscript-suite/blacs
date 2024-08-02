#####################################################################
#                                                                   #
# /plugins/virtual_device/__init__.py                               #
#                                                                   #
# Copyright 2024, Carter Turnbaugh                                  #
#                                                                   #
#####################################################################
import logging
import os
import subprocess
import threading
import sys
import time

from qtutils import inmain, inmain_decorator

import labscript_utils.h5_lock
import h5py

import labscript_utils.properties as properties
from labscript_utils.connections import ConnectionTable
from zprocess import TimeoutError
from labscript_utils.ls_zprocess import Event
from blacs.plugins import PLUGINS_DIR, callback

from .virtual_device_tab import VirtualDeviceTab

name = "Virtual Device"
module = "virtual_device" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)

# Try to reconnect often in case a tab restarts
CONNECT_CHECK_INTERVAL = 0.1

class Plugin(object):
    def __init__(self, initial_settings):
        self.menu = None
        self.notifications = {}
        self.initial_settings = initial_settings
        self.BLACS = None
        self.disconnected_last = False

        self.virtual_devices = initial_settings.get('virtual_devices', {})

        self.tab_dict = {}

        self.setup_complete = False
        self.close_event = threading.Event()
        self.reconnect_thread = threading.Thread(target=self.reconnect, args=(self.close_event,))
        self.reconnect_thread.daemon = True

        self.tab_restart_receiver = lambda dn, s=self: self.disconnect_widgets(dn)

    @inmain_decorator(True)
    def connect_widgets(self):
        if not self.setup_complete:
            return
        for name, vd_tab in self.tab_dict.items():
            vd_tab.connect_widgets()
        for _, tab in self.BLACS['ui'].blacs.tablist.items():
            if hasattr(tab, 'connect_restart_receiver'):
                tab.connect_restart_receiver(self.tab_restart_receiver)

    @inmain_decorator(True)
    def disconnect_widgets(self, closing_device_name):
        if not self.setup_complete:
            return
        self.BLACS['ui'].blacs.tablist[closing_device_name].disconnect_restart_receiver(self.tab_restart_receiver)
        for name, vd_tab in self.tab_dict.items():
            vd_tab.disconnect_widgets(closing_device_name)

    def reconnect(self, stop_event):
        while not stop_event.wait(CONNECT_CHECK_INTERVAL):
            self.connect_widgets()

    def on_tab_layout_change(self):
        return

    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS

        for name, vd_tab in self.tab_dict.items():
            vd_tab.create_widgets(self.BLACS['ui'].blacs.tablist,
                                  self.virtual_devices[name]['AO'],
                                  self.virtual_devices[name]['DO'],
                                  self.virtual_devices[name]['DDS'])

        self.setup_complete = True
        self.reconnect_thread.start()

    def get_save_data(self):
        return {'virtual_devices': {
            'v0': {'AO': [], 'DO': [('christopher', 'GPIO 09', False), ('pdo_0', '1', False)], 'DDS': []},
            'v1': {'AO': [], 'DO': [('pdo_0', '0', False), ('pdo_0', '2', True)], 'DDS': []},
        }}

    def get_tab_classes(self):
        return {k: VirtualDeviceTab for k in self.virtual_devices.keys()}

    def tabs_created(self, tab_dict):
        self.tab_dict = tab_dict

    def get_callbacks(self):
        return {}

    def get_menu_class(self):
        return None

    def get_notification_classes(self):
        return []

    def get_setting_classes(self):
        return []

    def set_menu_instance(self, menu):
        self.menu = menu

    def set_notification_instances(self, notifications):
        self.notifications = notifications

    def close(self):
        self.close_event.set()
        try:
            self.reconnect_thread.join()
        except RuntimeError:
            # reconnect_thread did not start, fail gracefully
            pass
