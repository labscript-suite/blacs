from labscript import *

PulseBlaster(  'pulseblaster_0')
PulseBlaster(  'pulseblaster_1')
NI_PCIe_6363(  'ni_pcie_6363_0',  pulseblaster_0, 'fast clock','/ni_pcie_6363_0/PFI0')
NI_PCI_6733(    'ni_pci_6733_0',  pulseblaster_0, 'fast clock','/ni_pcie_6363_0/PFI0')
NovaTechDDS9M( 'novatechdds9m_0', pulseblaster_0, 'slow clock')#flag 1
NovaTechDDS9M( 'novatechdds9m_1', pulseblaster_0, 'slow clock')#flag 1
NovaTechDDS9M( 'novatechdds9m_2', pulseblaster_0, 'slow clock')#flag 1
NovaTechDDS9M( 'novatechdds9m_3', pulseblaster_1, 'fast clock')

#DigitalOut(     'Fast_Clock',                           pulseblaster_0,         'flag 0')
#DigitalOut(     'Slow_Clock',                           pulseblaster_0,         'flag 1')                                       #NT_1,2,3
DigitalOut(     'Novatech_1_1',                          pulseblaster_0,         'flag 2')                                       #NT_1_1 gate
#DigitalOut(     '',          pulseblaster_0,         'flag 3')                                       #NT_1_2 gate -- In use in Rb_Push DDS
#DigitalOut(     '',          pulseblaster_0,         'flag 4')                                       #NT_1_0 gate -- In use in Rb_Optical_Pumping DDS
#DigitalOut(     'Wait',                                 pulseblaster_0,         'flag 5')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 6')                                       
#DigitalOut(     '',                                     pulseblaster_0,         'flag 7')                                       
#DigitalOut(     '',                                     pulseblaster_0,         'flag 8')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 9')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 10')
DigitalOut(     'Novatech_Gate',                         pulseblaster_0,         'flag 11')
#DDS(            'dipole_main',                           pulseblaster_0,         'dds 0')
#DDS(            'dipole_secondary',                      pulseblaster_0,         'dds 1')


#DigitalOut(     '',                                     pulseblaster_1,         'flag 0')
#DigitalOut(     '',                                     pulseblaster_1,         'flag 1')
#DigitalOut(     '',                                     pulseblaster_1,         'flag 2')
#DigitalOut(     '',                                     pulseblaster_1,         'flag 3')
DDS(            'dipole_main',                           pulseblaster_1,         'dds 0')
DDS(            'dipole_secondary',                      pulseblaster_1,         'dds 1')



DDS(             'Rb_Central_MOT',                       novatechdds9m_0,        'channel 0', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line0'})
DDS(             'Rb_Source_MOT',                        novatechdds9m_0,        'channel 1', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line1'})
StaticDDS(       'Rb_Repump',                            novatechdds9m_0,        'channel 2', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line2'})
StaticDDS(       'Rb_Main_Lock',                         novatechdds9m_0,        'channel 3')

DDS(            'Rb_Optical_Pumping',                    novatechdds9m_1,        'channel 0', digital_gate={'device':pulseblaster_0,'connection':'flag 4'})
#DDS(            '',                                     novatechdds9m_1,        'channel 1', digital_gate={'device':pulseblaster_0,'connection':'flag 2'})
StaticDDS(      'Rb_Push',                            novatechdds9m_1,        'channel 2', digital_gate={'device':pulseblaster_0,'connection':'flag 3'})
#StaticDDS(       '',                                    novatechdds9m_1,        'channel 3')

DDS(            'K_Main_MOT',                           novatechdds9m_2,        'channel 0', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line4'})
DDS(            'K_Repump',                             novatechdds9m_2,        'channel 1', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line5'})
StaticDDS(      'K_Lock',                               novatechdds9m_2,        'channel 2')
StaticDDS(      'K_Push',                               novatechdds9m_2,        'channel 3', digital_gate={'device':ni_pcie_6363_0,'connection':'port0/line7'})

DDS(            'Dipole_Trap',                           novatechdds9m_3,        'channel 0')
#DDS(            '',                             novatechdds9m_3,        'channel 1')
#StaticDDS(      '',                               novatechdds9m_3,        'channel 2')
#StaticDDS(      '',                               novatechdds9m_3,        'channel 3')


#AnalogOut(      '',                                   ni_pcie_6363_0,         'ao0')
#AnalogOut(      '',                                     ni_pcie_6363_0,         'ao1')
AnalogOut(      'top_racetrack',                         ni_pcie_6363_0,         'ao2')
AnalogOut(      'bottom_racetrack',                      ni_pcie_6363_0,         'ao3')

AnalogOut(      'Rb_Central_Bq',                      ni_pci_6733_0,         'ao0')
AnalogOut(      'Rb_Source_Bq',                      ni_pci_6733_0,         'ao1')
AnalogOut(      'Unused',                      ni_pci_6733_0,         'ao3')
AnalogOut(      'Central_bias_z',                      ni_pci_6733_0,         'ao4')

#DigitalOut(     '',              ni_pcie_6363_0,         'port0/line0')                                  #NT_0_0 gate -- In use in RB_Central_MOT DDS
#DigitalOut(     '',              ni_pcie_6363_0,         'port0/line1')                                  #NT_0_1 gate -- In use in RB_Source_MOT DDS
#DigitalOut(     '',              ni_pcie_6363_0,         'port0/line2')                                  #NT_0_2 -- In use in Rb_Repump DDS
# DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line3')
#DigitalOut(     '',                                 ni_pcie_6363_0,         'port0/line4')                                  #NT_2_0 gate -- In use in K_Main_MOT DDS
#DigitalOut(     '',                    ni_pcie_6363_0,         'port0/line5')                                  #NT_2_1 gate -- In use in K_Repump DDS
DigitalOut(     'K_Lock_RF_Switch',                      ni_pcie_6363_0,         'port0/line6')                                  #NT_2_2
#DigitalOut(     '',                      ni_pcie_6363_0,         'port0/line7')                                  #NT_2_3 gate -- In use in K_Push DDS
Shutter(        'Rb_Source_MOT_Shutter',                 ni_pcie_6363_0,         'port0/line8', delay=(3e-3,3e-3))               #Sh_1_1
Shutter(        'Rb_MOT_and_Probe_Shutter',              ni_pcie_6363_0,         'port0/line9', delay=(3e-3,3.25e-3))               #Sh_1_2
Shutter(        'Rb_Probe_Shutter',                      ni_pcie_6363_0,         'port0/line10', delay=(3e-3,3.5e-3))              #Sh_1_3
Shutter(        'Rb_Push_Shutter',                       ni_pcie_6363_0,         'port0/line11', delay=(3e-3,3e-3))              #Sh_1_4
#Shutter(     'Shutter_0_1',                              ni_pcie_6363_0,         'port0/line12', delay=(5e-3,5e-3))              #Sh_0_1
#Shutter(     'Shutter_0_2',                              ni_pcie_6363_0,         'port0/line13', delay=(5e-3,5e-3))              #Sh_0_2
#Shutter(     'Shutter_0_3',                              ni_pcie_6363_0,         'port0/line14', delay=(5e-3,5e-3))              #Sh_0_3
#Shutter(     'Shutter_0_4',                              ni_pcie_6363_0,         'port0/line15', delay=(5e-3,5e-3))              #Sh_0_4

Camera(           'camera',                              ni_pcie_6363_0,         'port0/line17', 0.1, 'side')
Camera(     'red_camera',                                     ni_pcie_6363_0,         'port0/line20',0.1,'side')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line21')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line22')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line23')
Shutter(     'Shutter_Rb_Central_MOT',                   ni_pcie_6363_0,         'port0/line24', delay=(2.5e-3,3.5e-3))              #Sh_0_4
Shutter(     'Shutter_Rb_Repump_Source_MOT',             ni_pcie_6363_0,         'port0/line25', delay=(2.5e-3,3.5e-3))              #Sh_0_4
Shutter(     'Shutter_Rb_Repump_Central_MOT',            ni_pcie_6363_0,         'port0/line26', delay=(4e-3,2.5e-3))              #Sh_0_4
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line27')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line28')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line29')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line30')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line31')

AnalogIn(       'ai0',                                     ni_pcie_6363_0,         'ai0')
AnalogIn(       'ai1',                                     ni_pcie_6363_0,         'ai1')
AnalogIn(       'ai2',                                     ni_pcie_6363_0,         'ai2')
AnalogIn(       'ai3',                                     ni_pcie_6363_0,         'ai3')
AnalogIn(       'ai4',                                     ni_pcie_6363_0,         'ai4')
AnalogIn(       'ai5',                                     ni_pcie_6363_0,         'ai5')
AnalogIn(       'ai6',                                     ni_pcie_6363_0,         'ai6')
AnalogIn(       'ai7',                                     ni_pcie_6363_0,         'ai7')
AnalogIn(       'ai8',                                     ni_pcie_6363_0,         'ai8')
AnalogIn(       'ai9',                                     ni_pcie_6363_0,         'ai9')
AnalogIn(       'ai10',                                     ni_pcie_6363_0,         'ai10')
AnalogIn(       'ai11',                                     ni_pcie_6363_0,         'ai11')
AnalogIn(       'ai12',                                     ni_pcie_6363_0,         'ai12')
AnalogIn(       'ai13',                                     ni_pcie_6363_0,         'ai13')
AnalogIn(       'ai14',                                     ni_pcie_6363_0,         'ai14')
AnalogIn(       'ai15',                                     ni_pcie_6363_0,         'ai15')
AnalogIn(       'ai16',                                     ni_pcie_6363_0,         'ai16')
AnalogIn(       'ai17',                                     ni_pcie_6363_0,         'ai17')
AnalogIn(       'ai18',                                     ni_pcie_6363_0,         'ai18')
AnalogIn(       'ai19',                                     ni_pcie_6363_0,         'ai19')
AnalogIn(       'ai20',                                     ni_pcie_6363_0,         'ai20')
AnalogIn(       'ai21',                                     ni_pcie_6363_0,         'ai21')
AnalogIn(       'ai22',                                     ni_pcie_6363_0,         'ai22')
AnalogIn(       'ai23',                                     ni_pcie_6363_0,         'ai23')
AnalogIn(       'ai24',                                     ni_pcie_6363_0,         'ai24')
AnalogIn(       'ai25',                                     ni_pcie_6363_0,         'ai25')
AnalogIn(       'ai26',                                     ni_pcie_6363_0,         'ai26')
AnalogIn(       'ai27',                                     ni_pcie_6363_0,         'ai27')
AnalogIn(       'ai28',                                     ni_pcie_6363_0,         'ai28')
AnalogIn(       'ai29',                                     ni_pcie_6363_0,         'ai29')
AnalogIn(       'ai30',                                     ni_pcie_6363_0,         'ai30')
AnalogIn(       'ai31',                                     ni_pcie_6363_0,         'ai31')


stop(1)
