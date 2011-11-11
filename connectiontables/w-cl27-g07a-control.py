from labscript import *

PulseBlaster(  'pulseblaster_0')
NI_PCIe_6363(  'ni_pcie_6363_0',  pulseblaster_0, 'fast clock')
NovaTechDDS9M( 'novatechdds9m_9', pulseblaster_0, 'slow clock')

AnalogOut( 'analog0',  ni_pcie_6363_0,         'ao0')
AnalogOut( 'analog1',  ni_pcie_6363_0,         'ao1')
AnalogOut( 'analog2',  ni_pcie_6363_0,         'ao2')
AnalogIn(   'input1',  ni_pcie_6363_0,         'ai0')
Shutter(  'shutter1',  ni_pcie_6363_0, 'port0/line0', delay=(0,0))
Shutter(  'shutter2',  pulseblaster_0,      'flag 2', delay=(0,0))
DDS(       'Imaging',  novatechdds9m_9,   'channel 0')
DDS(           'MOT',  novatechdds9m_9,   'channel 1')
StaticDDS(  'Zeeman',  novatechdds9m_9,   'channel 2')
StaticDDS(    'MOPA',  novatechdds9m_9,   'channel 3')
DDS(          'dds0',  pulseblaster_0,       'dds 0')
DDS(          'dds1',  pulseblaster_0,       'dds 1')

stop(0)