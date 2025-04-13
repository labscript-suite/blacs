from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

from labscript_utils.qtwidgets.toolpalette import ToolPaletteGroup
from labscript_utils.qtwidgets.ddsoutput import AnalogOutput, DigitalOutput, DDSOutput

from blacs.tab_base_classes import PluginTab
from blacs.tab_base_classes import PluginTab

class VirtualDeviceTab(PluginTab):

    def create_widgets(self, blacs_tablist, AOs, DOs, DDSs):
        '''
        This function sets up the tab, and should be called as soon as the plugin is otherwise ready.
        Here, we create dictionaries of widgets (initially connecting them to outputs).
        '''
        self._blacs_tablist = blacs_tablist
        self._AOs = {(AO[0], AO[1]): None for AO in AOs}
        self._DOs = {(DO[0], DO[1], DO[2]): None for DO in DOs}
        self._DDSs = {(DDS[0], DDS[1]): None for DDS in DDSs}

        for AO in self._AOs.keys():
            if self._AOs[AO] is None:
                chan = self._blacs_tablist[AO[0]].get_channel(AO[1])
                orig_label = chan.name.split('-')
                virtual_label = '%s\n%s' % (AO[0]+'.'+orig_label[0], orig_label[1])
                self._AOs[AO] = chan.create_widget(virtual_label, False, None)
                self._AOs[AO].last_AO = None

        for DO in self._DOs.keys():
            if self._DOs[DO] is None:
                self._DOs[DO] = self._blacs_tablist[DO[0]].get_channel(DO[1]).create_widget(inverted=DO[2])
                orig_label = self._DOs[DO].text().split('\n')
                virtual_label = '%s\n%s' % (DO[0]+'.'+orig_label[0], orig_label[1])
                self._DOs[DO].setText(virtual_label)
                self._DOs[DO].last_DO = None

        for DDS in self._DDSs.keys():
            if self._DDSs[DDS] is None:
                chan = self._blacs_tablist[DDS[0]].get_channel(DDS[1])
                orig_label = chan.name.split(' - ')
                self._DDSs[DDS] = DDSOutput(DDS[0]+'.'+orig_label[0], orig_label[1])
                chan.add_widget(self._DDSs[DDS])
                self._DDSs[DDS].last_DDS = None

        if len(self._AOs) > 0:
            self.place_widget_group('Analog Outputs', [v for k, v in self._AOs.items()])
        if len(self._DOs) > 0:
            self.place_widget_group('Digital Outputs', [v for k, v in self._DOs.items()])
        if len(self._DDSs) > 0:
            self.place_widget_group('DDS Outputs', [v for k, v in self._DDSs.items()])

        return

    def connect_widgets(self):
        '''
        For each of our widgets, check if it is connected to an output.
        If not, connect it.
        '''
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
        for DDS in self._DDSs.keys():
            if self._DDSs[DDS] is not None:
                new_DDS = self._blacs_tablist[DDS[0]].get_channel(DDS[1])
                if self._DDSs[DDS].last_DDS != new_DDS:
                    new_DDS.add_widget(self._DDSs[DDS])

    def disconnect_widgets(self, closing_device_name):
        '''
        For each of our widgets, check if it connects to an output in 'closing_device_name'.
        If it is, disconnect it so that 'closing_device_name' can be safely closed.
        '''
        for AO in self._AOs.keys():
            if AO[0] == closing_device_name:
                self._AOs[AO].last_AO = self._AOs[AO].get_AO()
                self._AOs[AO].set_AO(None)
        for DO in self._DOs.keys():
            if DO[0] == closing_device_name:
                self._DOs[DO].last_DO = self._DOs[DO].get_DO()
                self._DOs[DO].set_DO(None)
        for DDS in self._DDSs.keys():
            if DDS[0] == closing_device_name:
                old_DDS = self._blacs_tablist[DDS[0]].get_channel(DDS[1])
                self._DDSs[DDS].last_DDS = old_DDS

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
