from labscript import *
from calibrations import *

# MAIN DEVICE DEFINITIONS
PulseBlaster(   'pulseblaster_0')
NI_PCIe_6363(   'ni_pcie_6363_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0')
NI_PCI_6733(     'ni_pci_6733_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0')
NovaTechDDS9M( 'novatechdds9m_9',  pulseblaster_0, 'slow clock')

# MAG-NEAT-O CONTROL
AnalogOut(    'Bx',  ni_pci_6733_0,          'ao0')
AnalogOut(    'By',  ni_pci_6733_0,          'ao1')
AnalogOut(    'Bz',  ni_pci_6733_0,          'ao2')
AnalogIn( 'Bx_mon',  ni_pcie_6363_0,         'ai0')
AnalogIn( 'By_mon',  ni_pcie_6363_0,         'ai1')
AnalogIn( 'Bz_mon',  ni_pcie_6363_0,         'ai2')

# QUAD DRIVER
AnalogOut(          'Bq',  ni_pci_6733_0,    'ao3')
DigitalOut( 'cap_charge',  ni_pcie_6363_0,   'port0/line11')
AnalogIn( 'quad_current',  ni_pcie_6363_0,   'ai3')

# ZEEMAN SLOWER
DigitalOut('Zeeman_coil_2',  ni_pcie_6363_0, 'port0/line0')
# TABLE ENABLE
DigitalOut('Table_Enable',  ni_pcie_6363_0, 'port0/line21')

# SHUTTERS
Shutter(           'MOT_shutter',  ni_pcie_6363_0, 'port0/line17', delay=(0,0))
Shutter(    'MOT_repump_shutter',  ni_pcie_6363_0, 'port0/line18', delay=(0,0))
Shutter(        'Zeeman_shutter',  ni_pcie_6363_0, 'port0/line19', delay=(0,0))
Shutter( 'Zeeman_repump_shutter',  ni_pcie_6363_0, 'port0/line20', delay=(0,0))
#Shutter(       'Imaging_shutter',  ni_pcie_6363_0, 'port0/line8', delay=(0,0))

# POWER MONITORING
AnalogIn(    'MOT_power',  ni_pcie_6363_0,   'ai4')
AnalogIn( 'Zeeman_power',  ni_pcie_6363_0,   'ai5')
AnalogIn(     'OP_power',  ni_pcie_6363_0,   'ai6')
AnalogIn('Imaging_power',  ni_pcie_6363_0,   'ai7')
AnalogIn( 'TA_seed_leak',  ni_pcie_6363_0,   'ai8')

# FLUORESCENCE MONITORING
AnalogIn( 'MOT_fluoro',  ni_pcie_6363_0,     'ai9')

# SUPERNOVA
DDS(             'MOPA',  novatechdds9m_9, 'channel 0', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line4'})
DDS(           'Zeeman',  novatechdds9m_9, 'channel 1', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line5'})   # proposed RF channel
StaticDDS(        'MOT',  novatechdds9m_9, 'channel 2', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line6'})
StaticDDS( 'MOT_repump',  novatechdds9m_9, 'channel 3', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line7'})

# IMAGING SYSTEM
Camera( 'camera', ni_pcie_6363_0, 'port0/line1', 0.1, 'side')

# PULSEBLASTER 0 DDS
DDS(         'Imaging',  pulseblaster_0,     'dds 0')
DDS( 'MOT_repump_lock',  pulseblaster_0,     'dds 1')

# Triggering
DigitalOut('cro_trigger', ni_pcie_6363_0, 'port0/line15')

stop(1)
