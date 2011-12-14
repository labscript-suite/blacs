from labscript import *

# MAIN DEVICE DEFINITIONS
PulseBlaster(   'pulseblaster_0')
NI_PCIe_6363(   'ni_pcie_6363_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0')
NI_PCI_6733(     'ni_pci_6733_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0')
NovaTechDDS9M( 'novatechdds9m_9',  pulseblaster_0, 'slow clock')

# MAG-NEAT-O CONTROL
AnalogOut(    'Bx',  ni_pcie_6363_0,         'ao0')
AnalogOut(    'By',  ni_pcie_6363_0,         'ao1')
AnalogOut(    'Bz',  ni_pcie_6363_0,         'ao2')
AnalogIn( 'Bx_mon',  ni_pcie_6363_0,         'ai0')
AnalogIn( 'By_mon',  ni_pcie_6363_0,         'ai1')
AnalogIn( 'Bz_mon',  ni_pcie_6363_0,         'ai2')

# QUAD DRIVER
AnalogOut(          'Bq',  ni_pcie_6363_0,         'ao3')
DigitalOut( 'cap_charge',  ni_pcie_6363_0,  'port0/line11')
AnalogIn( 'quad_current',  ni_pcie_6363_0,         'ai3')

# ZEEMAN SLOWER
DigitalOut('Zeeman_coils',  ni_pcie_6363_0,  'port0/line12')
DigitalOut('Zeeman_shutter',ni_pcie_6363_0,  'port0/line13')

# SHUTTERS
Shutter(    'MOT_shutter',  ni_pcie_6363_0, 'port0/line0', delay=(0,0))
Shutter( 'Zeeman_shutter',  ni_pcie_6363_0, 'port0/line1', delay=(0,0))
Shutter('Imaging_shutter',  ni_pcie_6363_0, 'port0/line2', delay=(0,0))
Shutter( 'Repump_shutter',  ni_pcie_6363_0, 'port0/line3', delay=(0,0))
Shutter(     'OP_shutter',  ni_pcie_6363_0, 'port0/line4', delay=(0,0))

# CAMERA
DigitalOut('Camera_trigger',ni_pcie_6363_0,  'port0/line14')

# POWER MONITORING
AnalogIn(    'MOT_power',  ni_pcie_6363_0,         'ai4')
AnalogIn( 'Zeeman_power',  ni_pcie_6363_0,         'ai5')
AnalogIn(     'OP_power',  ni_pcie_6363_0,         'ai6')
AnalogIn('Imaging_power',  ni_pcie_6363_0,         'ai7')
AnalogIn( 'TA_seed_leak',  ni_pcie_6363_0,         'ai8')

# FLUORESCENCE MONITORING
AnalogIn( 'MOT_fluoro',  ni_pcie_6363_0,         'ai9')

# SUPERNOVA
DDS(                 'MOPA',  novatechdds9m_9,   'channel 0')
DDS(              'Imaging',  novatechdds9m_9,   'channel 1')   # proposed RF channel
StaticDDS(            'MOT',  novatechdds9m_9,   'channel 2')
StaticDDS(         'Repump',  novatechdds9m_9,   'channel 3')
DigitalOut(   'MOPA_enable',  ni_pcie_6363_0,  'port0/line5')
DigitalOut('Imaging_enable',  ni_pcie_6363_0,  'port0/line6')   # proposed RF channel
DigitalOut(    'MOT_enable',  ni_pcie_6363_0,  'port0/line7')
DigitalOut( 'Repump_enable',  ni_pcie_6363_0,  'port0/line8')

# IMAGING SYSTEM
Camera('camera',  pulseblaster_0, 'flag 2', 0.1, 'top')
DigitalOut('imaging', pulseblaster_0, 'flag 3')

# PULSEBLASTER 0 DDS
# DDS(               'Zeeman',  pulseblaster_0,       'dds 0')   forseen assignment
# DDS(              'Imaging',  pulseblaster_0,       'dds 1')   forseen assignment
# DigitalOut( 'Zeeman_enable',  ni_pcie_6363_0,  'port0/line9')  forseen assignment
# DigitalOut('Imaging_enable',  ni_pcie_6363_0,  'port0/line10') forseen assignment

stop(1)
