from labscript import *
from unitconversions import *

# MAIN DEVICE DEFINITIONS
PulseBlaster(   'pulseblaster_0')
PulseBlaster(   'pulseblaster_1')
NI_PCIe_6363(   'ni_pcie_6363_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0', acquisition_rate=1e4)
NI_PCI_6733(     'ni_pci_6733_0',  pulseblaster_0, 'fast clock', '/ni_pcie_6363_0/PFI0')
NovaTechDDS9M( 'novatechdds9m_9',  pulseblaster_0, 'slow clock')

# MAG-NEAT-O CONTROL
AnalogOut(   'Bx0',  ni_pci_6733_0, 'ao0')
AnalogOut(   'Bx1',  ni_pci_6733_0, 'ao1')
AnalogOut(   'By0',  ni_pci_6733_0, 'ao2')
AnalogOut(   'By1',  ni_pci_6733_0, 'ao3')
AnalogOut(   'Bz0',  ni_pci_6733_0, 'ao4')
AnalogOut(   'Bz1',  ni_pci_6733_0, 'ao5')
AnalogIn( 'Bx_mon', ni_pcie_6363_0, 'ai0')
AnalogIn( 'By_mon', ni_pcie_6363_0, 'ai1')
AnalogIn( 'Bz_mon', ni_pcie_6363_0, 'ai2')

# QUAD DRIVER
AnalogOut(          'Bq',  ni_pci_6733_0, 'ao6', unit_conversion_class=quad_driver, unit_conversion_parameters={'A_per_V':Bq_A_per_V, 'A_offset':Bq_A_offset, 'A_min':Bq_A_min, 'Gcm_per_A':Bq_Gcm_per_A})
#DigitalOut( 'cap_charge', ni_pcie_6363_0, 'port0/line11')
AnalogIn( 'quad_current', ni_pcie_6363_0, 'ai3')

# ZEEMAN SLOWER
DigitalOut( 'Zeeman_coil_2', ni_pcie_6363_0, 'port0/line0')

# SHUTTERS
Shutter(           'MOT_shutter', ni_pcie_6363_0, 'port0/line17', delay=(0,0))
Shutter(    'MOT_repump_shutter', ni_pcie_6363_0, 'port0/line18', delay=(0,0))
Shutter(        'Zeeman_shutter', ni_pcie_6363_0, 'port0/line19', delay=(0,0))
Shutter( 'Zeeman_repump_shutter', ni_pcie_6363_0, 'port0/line20', delay=(0,0))
Shutter(       'imaging_shutter', ni_pcie_6363_0, 'port0/line21', delay=(0,0))
Shutter(            'OP_shutter', ni_pcie_6363_0, 'port0/line22', delay=(0,0))
Shutter(          'atom_shutter', ni_pcie_6363_0,  'port0/line3', delay=(0,0))

# POWER MONITORING
AnalogIn(             'MOT_power', ni_pcie_6363_0,  'ai16')
AnalogIn(          'Zeeman_power', ni_pcie_6363_0,  'ai17')
AnalogIn(      'MOT_repump_power', ni_pcie_6363_0,  'ai18')
AnalogIn(         'imaging_power', ni_pcie_6363_0,  'ai19')
AnalogIn( 'optical_pumping_power', ni_pcie_6363_0,  'ai20')

# FLUORESCENCE MONITORING
AnalogIn( 'MOT_fluoro', ni_pcie_6363_0, 'ai8')

# SUPERNOVA
DDS(                  'MOPA', novatechdds9m_9, 'channel 0', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line4'}, freq_conv_class=detuning, freq_conv_params={'pass':-2, 'detuning_0':-80})
DDS(                   'MOT', novatechdds9m_9, 'channel 1', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line5'}, freq_conv_class=detuning, freq_conv_params={'pass':2, 'detuning_0':-2*MOPA_frequency-80})
StaticDDS(          'Zeeman', novatechdds9m_9, 'channel 2', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line6'}, freq_conv_class=detuning, freq_conv_params={'pass':1, 'detuning_0':-2*MOPA_frequency-80})
StaticDDS( 'MOT_repump_lock', novatechdds9m_9, 'channel 3', digital_gate = {'device': ni_pcie_6363_0, 'connection': 'port0/line7'}, freq_conv_class=detuning, freq_conv_params={'pass':1, 'detuning_0':-80})
DigitalOut(   'table_enable',  ni_pcie_6363_0, 'port0/line23')

# IMAGING SYSTEM
Camera( 'avt_gx1920_0', ni_pcie_6363_0, 'port0/line1', 0.1, 'side')

# PULSEBLASTER 0 DDS
DDS(    'imaging', pulseblaster_0, 'dds 0')
DDS( 'MOT_repump', pulseblaster_0, 'dds 1')

# PULSEBLASTER 1 DDS
DDS(         'rf_evap', pulseblaster_1, 'dds 0')
DDS( 'optical_pumping', pulseblaster_1, 'dds 1')
DigitalOut( 'pulseblaster_1_trigger', pulseblaster_0, 'flag 2')

# AUXILLARY
DigitalOut( 'cro_trigger', ni_pcie_6363_0, 'port0/line15')
AnalogIn(      'aux_in_0', ni_pcie_6363_0, 'ai10')
AnalogIn(      'aux_in_1', ni_pcie_6363_0, 'ai11')
AnalogIn(      'aux_in_2', ni_pcie_6363_0, 'ai22')
AnalogIn(      'aux_in_3', ni_pcie_6363_0, 'ai23')
AnalogOut(    'aux_out_0', ni_pcie_6363_0, 'ao0')
AnalogOut(    'aux_out_1', ni_pcie_6363_0, 'ao1')
AnalogOut(    'aux_out_2',  ni_pci_6733_0, 'ao7')

stop(1)
