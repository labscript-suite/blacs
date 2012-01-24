from labscript import *

PulseBlaster(  'pulseblaster_0')
NI_PCIe_6363(  'ni_pcie_6363_0',  pulseblaster_0, 'fast clock','/ni_pcie_6363_0/PFI0')
NI_PCI_6733(  'ni_pci_6733_0',  pulseblaster_0, 'fast clock','/ni_pcie_6363_0/PFI0')
NovaTechDDS9M( 'novatechdds9m_0', pulseblaster_0, 'slow clock')

AnalogOut( 'analog0',  ni_pcie_6363_0,         'ao0')
AnalogOut( 'analog1',  ni_pci_6733_0,         'ao0')
AnalogOut( 'analog2',  ni_pci_6733_0,         'ao1')

#AnalogIn(   'input1',  ni_pcie_6363_0,         'ai0')

#DigitalOut(  'digital0',  ni_pcie_6363_0, 'port0/line0')
#DigitalOut(  'table_enable',  pulseblaster_0,      'flag 2')

DDS(          'dds0', novatechdds9m_0,   'channel 0')
DDS(          'dds2',  pulseblaster_0,       'dds 0')

stop(1)
