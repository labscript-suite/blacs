from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from labscript_utils.qtwidgets.toolpalette import ToolPaletteGroup

from blacs.tab_base_classes import PluginTab

class VirtualDeviceTab(PluginTab):

    def create_widgets(self, blacs_tablist, AOs, DOs, DDSs):
        self._blacs_tablist = blacs_tablist
        self._AOs = {(AO[0], AO[1]): None for AO in AOs}
        self._DOs = {(DO[0], DO[1], DO[2]): None for DO in DOs}
        self._DDSs = {(DDS[0], DDS[1]): None for DDS in DDSs}

        for AO in self._AOs.keys():
            if self._AOs[AO] is None:
                self._AOs[AO] = self._blacs_tablist[AO[0]].get_channel(AO[1]).create_widget(None, False, None)
                self._AOs[AO].last_AO = None

        for DO in self._DOs.keys():
            if self._DOs[DO] is None:
                self._DOs[DO] = self._blacs_tablist[DO[0]].get_channel(DO[1]).create_widget(inverted=DO[2])
                self._DOs[DO].last_DO = None

        dds_widgets = []

        if len(self._AOs) > 0:
            self.place_widget_group('Analog Outputs', [v for k, v in self._AOs.items()])
        if len(self._DOs) > 0:
            self.place_widget_group('Digital Outputs', [v for k, v in self._DOs.items()])

        return

    def connect_widgets(self):
        for AO in self._AOs.keys():
            if self._AOs[AO] is not None:
                new_AO = self._blacs_tablist[AO[0]].get_channel(AO[1])
                if self._AOs[AO].get_AO() is None and self._AOs[AO].last_AO != new_AO:
                    self._AOs[AO].set_AO(new_AO)
        for DO in self._DOs.keys():
            if self._DOs[DO] is not None:
                new_DO = self._blacs_tablist[DO[0]].get_channel(DO[1])
                if self._DOs[DO].get_DO() is None and self._DOs[DO].last_DO != new_DO:
                    self._DOs[DO].set_DO(new_DO)

    def disconnect_widgets(self, closing_device_name):
        for AO in self._AOs.keys():
            if AO[0] == closing_device_name:
                self._AOs[AO].last_AO = self._AOs[AO].get_AO()
                self._AOs[AO].set_AO(None)
        for DO in self._DOs.keys():
            if DO[0] == closing_device_name:
                self._DOs[DO].last_DO = self._DOs[DO].get_DO()
                self._DOs[DO].set_DO(None)

    def place_widget_group(self, name, widgets):
        widget = QWidget()
        toolpalettegroup = ToolPaletteGroup(widget)

        if toolpalettegroup.has_palette(name):
            toolpalette = toolpalettegroup.get_palette(name)
        else:
            toolpalette = toolpalettegroup.append_new_palette(name)

        for output_widget in widgets:
            toolpalette.addWidget(output_widget, True)

        self.get_tab_layout().addWidget(widget)
        self.get_tab_layout().addItem(QSpacerItem(0,0,QSizePolicy.Minimum,QSizePolicy.MinimumExpanding))
