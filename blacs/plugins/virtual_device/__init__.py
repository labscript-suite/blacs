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

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *
from qtutils import *

import labscript_utils.properties as properties
from labscript_utils.connections import ConnectionTable
from zprocess import TimeoutError
from labscript_utils.ls_zprocess import Event
from blacs.plugins import PLUGINS_DIR, callback
from blacs.device_base_class import DeviceTab
from blacs.output_classes import AO as AO_output_class
from blacs.output_classes import DO as DO_output_class
from blacs.output_classes import DDS as DDS_output_class

from .virtual_device_tab import VirtualDeviceTab

name = "Virtual Devices"
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
        self.save_virtual_devices = self.virtual_devices

        self.tab_dict = {}

        self.setup_complete = False
        self.close_event = threading.Event()
        # If the virtual device starts after a device starts, it needs to connect its widgets.
        # So we start a background thread to periodically check if we have any non-connected widgets and connect them.
        self.reconnect_thread = threading.Thread(target=self.reconnect, args=(self.close_event,))
        self.reconnect_thread.daemon = True

        # If a tab (device) is restarted, it recreates its outputs.
        # If the virtual device still has widgets referencing those outputs, they will fail.
        # So, we need to disconnect them.
        self.tab_restart_receiver = lambda dn, s=self: self.disconnect_widgets(dn)

    @inmain_decorator(True)
    def connect_widgets(self):
        '''
        For each of our tabs, tell connect its widgets to outputs.
        Also connect restart receivers so we can detect if new tabs start to close.
        '''
        if not self.setup_complete:
            return
        for name, vd_tab in self.tab_dict.items():
            vd_tab.connect_widgets()
        for _, tab in self.BLACS['ui'].blacs.tablist.items():
            if hasattr(tab, 'connect_restart_receiver'):
                tab.connect_restart_receiver(self.tab_restart_receiver)

    @inmain_decorator(True)
    def disconnect_widgets(self, closing_device_name):
        '''
        For each of our tabs, disconnect it from closing_device_name
        '''
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

    def get_virtual_devices(self):
        return self.virtual_devices

    def get_save_virtual_devices(self):
        return self.save_virtual_devices

    def set_save_virtual_devices(self, save_virtual_devices):
        self.save_virtual_devices = save_virtual_devices

    def get_save_data(self):
        return {'virtual_devices': self.save_virtual_devices}

    def get_tab_classes(self):
        return {k: VirtualDeviceTab for k in self.virtual_devices.keys()}

    def tabs_created(self, tab_dict):
        self.tab_dict = tab_dict

    def get_callbacks(self):
        return {}

    def get_menu_class(self):
        return Menu

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

class Menu(object):
    VD_TREE_DUMMY_ROW_TEXT = '<Click to add virtual device>'

    CT_TREE_COL_NAME = 0
    CT_TREE_COL_ADD = 1
    CT_TREE_ROLE_NAME = Qt.UserRole + 1
    CT_TREE_ROLE_DO_INVERTED = Qt.UserRole + 2

    VD_TREE_COL_NAME = 0
    VD_TREE_COL_UP = 1
    VD_TREE_COL_DN = 2
    VD_TREE_COL_DELETE = 3
    VD_TREE_ROLE_IS_DUMMY_ROW = Qt.UserRole + 1
    VD_TREE_ROLE_DO_INVERTED = Qt.UserRole + 2

    def _get_root_parent(item):
        while item.parent() is not None:
            item = item.parent()
        return item

    def _get_child_outputs(self, conn_table, root_devs, dev_name, tab):
        '''
        Get all child outputs of a device.

        This is more complex than simply accessing `child_list` for the device
        as some devices have structures between themselves and their ultimate outputs.
        '''
        AOs = []
        DOs = []
        DDSs = []

        device_conn = conn_table.find_by_name(dev_name)
        for child in device_conn.child_list.keys():
            if child in root_devs:
                # Don't cross between tabs here
                continue

            child_dev = device_conn.find_by_name(child)
            channel = tab.get_channel(child_dev.parent_port)
            if channel is None:
                AOs_, DOs_, DDSs_ = self._get_child_outputs(conn_table, root_devs, child, tab)

                AOs += AOs_
                DOs += DOs_
                DDSs += DDSs_
            elif isinstance(channel, DO_output_class):
                inv = child_dev.properties['inverted'] if 'inverted' in child_dev.properties else False
                DOs.append((child, child_dev.parent_port, inv))
            elif isinstance(channel, AO_output_class):
                AOs.append((child, child_dev.parent_port))
            elif isinstance(channel, DDS_output_class):
                DDSs.append((child, child_dev.parent_port))

        return AOs, DOs, DDSs

    def __init__(self, BLACS):
        self.BLACS = BLACS

        self.connection_table_model = QStandardItemModel()
        self.connection_table_model.setHorizontalHeaderLabels(['Connection Table Devices', 'Add'])
        self.connection_table_view = None

        # Construct tree from tablist and connection table
        connection_table = ConnectionTable(self.BLACS['connection_table_h5file'])
        for tab_name, tab in self.BLACS['ui'].blacs.tablist.items():
            if isinstance(tab, DeviceTab):
                device_item = QStandardItem(tab_name)
                self.connection_table_model.appendRow([device_item])

                analog_outputs = QStandardItem('Analog Outputs')
                digital_outputs = QStandardItem('Digital Outputs')
                dds_outputs = QStandardItem('DDS Outputs')

                device_item.appendRow(analog_outputs)
                device_item.appendRow(digital_outputs)
                device_item.appendRow(dds_outputs)

                root_devs = self.BLACS['ui'].blacs.tablist.keys()
                AOs, DOs, DDSs = self._get_child_outputs(connection_table, root_devs, tab_name, tab)

                for DO in DOs:
                    DO_item = QStandardItem(DO[1] + ' - ' + DO[0])
                    add_to_vd_item = QStandardItem()
                    add_to_vd_item.setIcon(QIcon(':qtutils/fugue/arrow'))
                    add_to_vd_item.setEditable(False)
                    add_to_vd_item.setToolTip('Add this output to selected virtual device')
                    add_to_vd_item.setData(DO[1] + ' - ' + DO[0], self.CT_TREE_ROLE_NAME)
                    add_to_vd_item.setData(DO[2], self.CT_TREE_ROLE_DO_INVERTED)
                    digital_outputs.appendRow([DO_item, add_to_vd_item])
                for AO in AOs:
                    AO_item = QStandardItem(AO[1] + ' - ' + AO[0])
                    add_to_vd_item = QStandardItem()
                    add_to_vd_item.setIcon(QIcon(':qtutils/fugue/arrow'))
                    add_to_vd_item.setEditable(False)
                    add_to_vd_item.setToolTip('Add this output to selected virtual device')
                    add_to_vd_item.setData(AO[1] + ' - ' + AO[0], self.CT_TREE_ROLE_NAME)
                    analog_outputs.appendRow([AO_item, add_to_vd_item])
                for DDS in DDSs:
                    DDS_item = QStandardItem(DDS[1] + ' - ' + DDS[0])
                    add_to_vd_item = QStandardItem()
                    add_to_vd_item.setIcon(QIcon(':qtutils/fugue/arrow'))
                    add_to_vd_item.setEditable(False)
                    add_to_vd_item.setToolTip('Add this output to selected virtual device')
                    add_to_vd_item.setData(DDS[1] + ' - ' + DDS[0], self.CT_TREE_ROLE_NAME)
                    dds_outputs.appendRow([DDS_item, add_to_vd_item])

        self.virtual_device_model = QStandardItemModel()
        self.virtual_device_model.setHorizontalHeaderLabels(['Virtual Devices', 'Up', 'Down', 'Remove'])
        self.virtual_device_model.itemChanged.connect(self.on_virtual_devices_item_changed)
        self.virtual_device_view = None

    def get_menu_items(self):
        return {'name': name,
                'menu_items': [{'name': 'Edit',
                                'action': self.on_edit_virtual_devices,
                               'icon': ':/qtutils/fugue/document--pencil'
                                }
                               ]
                }

    def make_virtual_device_output_row(self, name):
        name_item = QStandardItem(name)
        up_item = QStandardItem()
        up_item.setIcon(QIcon(':qtutils/fugue/arrow-090'))
        up_item.setEditable(False)
        up_item.setToolTip('Move this output up in the virtual device output list')
        dn_item = QStandardItem()
        dn_item.setIcon(QIcon(':qtutils/fugue/arrow-270'))
        dn_item.setEditable(False)
        dn_item.setToolTip('Move this output down in the virtual device output list')
        remove_item = QStandardItem()
        remove_item.setIcon(QIcon(':qtutils/fugue/minus'))
        remove_item.setEditable(False)
        remove_item.setToolTip('Remove this output from the virtual device')

        return [name_item, up_item, dn_item, remove_item]

    def on_treeView_connection_table_clicked(self, index):
        item = self.connection_table_model.itemFromIndex(index)
        if item.column() == self.CT_TREE_COL_ADD:
            # Add this output to the currently selected virtual devices
            new_vd_output = QStandardItem('{}.{}'.format(item.parent().parent().text(),
                                                         item.data(self.CT_TREE_ROLE_NAME)))
            if item.data(self.CT_TREE_ROLE_DO_INVERTED) is not None:
                new_vd_output.setData(item.data(self.CT_TREE_ROLE_DO_INVERTED), self.VD_TREE_ROLE_DO_INVERTED)

            complete_vds = []
            for i in self.virtual_device_view.selectedIndexes():
                vd = Menu._get_root_parent(self.virtual_device_model.itemFromIndex(i))
                if vd.text() in complete_vds:
                    continue
                complete_vds.append(vd.text())

                for r in range(0, vd.rowCount()):
                    output_group = vd.child(r, self.VD_TREE_COL_NAME)
                    if output_group.text() != item.parent().text():
                        continue

                    # Avoid duplicating outputs in a virtual device
                    already_present = False
                    for j in range(0, output_group.rowCount()):
                        if output_group.child(j).text() == new_vd_output.text():
                            already_present = True
                            break
                    if already_present:
                        continue

                    output_group.appendRow(self.make_virtual_device_output_row(new_vd_output))

    def on_virtual_devices_item_changed(self, item):
        if item.column() != self.VD_TREE_COL_NAME or not item.data(self.VD_TREE_ROLE_IS_DUMMY_ROW):
            # Item rearrangement, nothing we need to do.
            return

        if item.text() != self.VD_TREE_DUMMY_ROW_TEXT:
            # If dummy row text has changed, use this as name of new virtual device and add it
            new_vd_name = item.text()
            if len(self.virtual_device_model.findItems(new_vd_name)) > 1:
                QMessageBox.warning(self.BLACS['ui'], 'Unable to add virtual device',
                                    'Unable to add virtual device, name {} already in use'.format(new_vd_name))
                item.setText(self.VD_TREE_DUMMY_ROW_TEXT)
                return

            new_device_item = QStandardItem(new_vd_name)
            remove_item = QStandardItem()
            remove_item.setIcon(QIcon(':qtutils/fugue/minus'))
            remove_item.setEditable(False)
            remove_item.setToolTip('Remove this virtual device')
            self.virtual_device_model.insertRow(self.virtual_device_model.rowCount() - 1,
                                                [new_device_item, None, None, remove_item])
            new_device_item.appendRow(QStandardItem('Analog Outputs'))
            new_device_item.appendRow(QStandardItem('Digital Outputs'))
            new_device_item.appendRow(QStandardItem('DDS Outputs'))

            item.setText(self.VD_TREE_DUMMY_ROW_TEXT)

    def on_treeView_virtual_devices_clicked(self, index):
        item = self.virtual_device_model.itemFromIndex(index)
        if item.data(self.VD_TREE_ROLE_IS_DUMMY_ROW):
            name_index = index.sibling(index.row(), self.VD_TREE_COL_NAME)
            name_item = self.virtual_device_model.itemFromIndex(name_index)
            self.virtual_device_view.setCurrentIndex(name_index)
            self.virtual_device_view.edit(name_index)
            return
        elif item.column() == self.VD_TREE_COL_UP:
            if index.row() > 0:
                item.parent().insertRow(index.row()-1, item.parent().takeRow(index.row()))
        elif item.column() == self.VD_TREE_COL_DN:
            if index.row() < item.parent().rowCount()-1:
                item.parent().insertRow(index.row()+1, item.parent().takeRow(index.row()))
        elif item.column() == self.VD_TREE_COL_DELETE:
            item.parent().removeRow(index.row())

    def on_edit_virtual_devices(self, *args, **kwargs):
        # Construct tree of virtual devices
        # This happens here so that the tree is up to date
        for vd_name, vd in self.BLACS['plugins'][module].get_save_virtual_devices().items():
            device_item = QStandardItem(vd_name)
            self.virtual_device_model.appendRow([device_item])

            analog_outputs = QStandardItem('Analog Outputs')
            device_item.appendRow(analog_outputs)
            for AO in vd['AO']:
                chan = self.BLACS['ui'].blacs.tablist[AO[0]].get_channel(AO[1])
                analog_outputs.appendRow(self.make_virtual_device_output_row(AO[0] + '.' + chan.name))

            digital_outputs = QStandardItem('Digital Outputs')
            device_item.appendRow(digital_outputs)
            for DO in vd['DO']:
                chan = self.BLACS['ui'].blacs.tablist[DO[0]].get_channel(DO[1])
                digital_outputs.appendRow(self.make_virtual_device_output_row(DO[0] + '.' + chan.name))

            dds_outputs = QStandardItem('DDS Outputs')
            device_item.appendRow(dds_outputs)
            for DDS in vd['DDS']:
                chan = self.BLACS['ui'].blacs.tablist[DDS[0]].get_channel(DDS[1])
                dds_outputs.appendRow(self.make_virtual_device_output_row(DDS[0] + '.' + chan.name))

        add_vd_item = QStandardItem(self.VD_TREE_DUMMY_ROW_TEXT)
        add_vd_item.setData(True, self.VD_TREE_ROLE_IS_DUMMY_ROW)
        add_vd_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable)
        self.virtual_device_model.appendRow([add_vd_item])

        edit_dialog = QDialog(self.BLACS['ui'])
        edit_dialog.setModal(True)
        edit_dialog.accepted.connect(self.on_save)
        edit_dialog.rejected.connect(self.on_cancel)
        edit_dialog.setWindowTitle('Virtual Device Builder')
        # Remove the help flag next to the [X] close button
        edit_dialog.setWindowFlags(edit_dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(edit_dialog)
        ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'virtual_device_menu.ui'))
        layout.addWidget(ui)

        ui.treeView_connection_table.setModel(self.connection_table_model)
        ui.treeView_connection_table.setAnimated(True)
        ui.treeView_connection_table.setSelectionMode(QTreeView.ExtendedSelection)
        ui.treeView_connection_table.setSortingEnabled(False)
        ui.treeView_connection_table.setColumnWidth(self.CT_TREE_COL_NAME, 200)
        ui.treeView_connection_table.clicked.connect(self.on_treeView_connection_table_clicked)
        for column in range(1, self.connection_table_model.columnCount()):
            ui.treeView_connection_table.resizeColumnToContents(column)
        self.connection_table_view = ui.treeView_connection_table

        ui.treeView_virtual_devices.setModel(self.virtual_device_model)
        ui.treeView_virtual_devices.setAnimated(True)
        ui.treeView_virtual_devices.setSelectionMode(QTreeView.ExtendedSelection)
        ui.treeView_virtual_devices.setSortingEnabled(False)
        ui.treeView_virtual_devices.setColumnWidth(self.VD_TREE_COL_NAME, 200)
        ui.treeView_virtual_devices.clicked.connect(self.on_treeView_virtual_devices_clicked)
        for column in range(1, self.virtual_device_model.columnCount()):
            ui.treeView_virtual_devices.resizeColumnToContents(column)
        self.virtual_device_view = ui.treeView_virtual_devices

        # Add OK/cancel buttons
        widget = QWidget()
        hlayout = QHBoxLayout(widget)
        button_box = QDialogButtonBox()
        button_box.setStandardButtons(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(edit_dialog.accept)
        button_box.rejected.connect(edit_dialog.reject)
        hlayout.addItem(QSpacerItem(0,0,QSizePolicy.MinimumExpanding,QSizePolicy.Minimum))
        hlayout.addWidget(button_box)
        layout.addWidget(widget)

        edit_dialog.show()

        return

    def _encode_virtual_devices(self):
        '''
        Convert data in model to a simple dictionary that can be saved.
        '''
        virtual_device_data = {}
        root = self.virtual_device_model.invisibleRootItem()
        for i in range(root.rowCount()):
            vd = root.child(i)
            if vd.text() == self.VD_TREE_DUMMY_ROW_TEXT:
                continue

            virtual_device_data[vd.text()] = {'AO': [], 'DO': [], 'DDS': []}
            for j in range(vd.rowCount()):
                output_group = vd.child(j)
                if output_group.text() == 'Analog Outputs':
                    for k in range(output_group.rowCount()):
                        AO_name = output_group.child(k).text().split(' - ')[0].split('.')
                        virtual_device_data[vd.text()]['AO'].append((AO_name[0], AO_name[1]))
                elif output_group.text() == 'Digital Outputs':
                    for k in range(output_group.rowCount()):
                        DO_name = output_group.child(k).text().split(' - ')[0].split('.')
                        inverted = output_group.child(k).data(self.VD_TREE_ROLE_DO_INVERTED)
                        virtual_device_data[vd.text()]['DO'].append((DO_name[0], DO_name[1], inverted))
                elif output_group.text() == 'DDS Outputs':
                    for k in range(output_group.rowCount()):
                        DDS_name = output_group.child(k).text().split(' - ')[0].split('.')
                        virtual_device_data[vd.text()]['DDS'].append((DDS_name[0], DDS_name[1]))

        return virtual_device_data

    def on_save(self):
        self.BLACS['plugins'][module].set_save_virtual_devices(self._encode_virtual_devices())
        QMessageBox.information(self.BLACS['ui'], 'Virtual Devices Saved',
                                'New virtual devices saved. Please restart BLACS to load new devices.')

    def on_cancel(self):
        QMessageBox.information(self.BLACS['ui'], 'Virtual Devices Not Saved',
                                'Editing of virtual devices canceled.')

    def close(self):
        pass
