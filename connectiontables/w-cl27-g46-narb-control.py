from labscript import *

PulseBlaster(  'pulseblaster_0')
#NI_PCIe_6363(  'ni_pcie_6363_0',  pulseblaster_0, 'fast clock')
NovaTechDDS9M( 'novatechdds9m_0', pulseblaster_0, 'slow clock')
#DigitalOut(     'digital1',              ni_pcie_6363_0,         'port0/line0')
#AnalogOut( 'analog0',  ni_pcie_6363_0,         'ao0')
#AnalogOut( 'analog1',  ni_pcie_6363_0,         'ao1')
#AnalogOut( 'analog2',  ni_pcie_6363_0,         'ao2')
#AnalogIn(   'input1',  ni_pcie_6363_0,         'ai0')
#Shutter(  'shutter1',  ni_pcie_6363_0, 'port0/line0', delay=(0,0))
#Shutter(  'shutter2',  pulseblaster_0,      'flag 2', delay=(0,0))
DDS(          'dds1', novatechdds9m_0,   'channel 0')
DDS(          'dds2', novatechdds9m_0,   'channel 1')
DDS(          'dds3',  pulseblaster_0,       'dds 0')
DDS(          'dds4',  pulseblaster_0,       'dds 1')

stop(1)
