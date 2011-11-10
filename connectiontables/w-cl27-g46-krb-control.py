from labscript import *

PulseBlaster(  'pulseblaster_0')
PulseBlaster(  'pulseblaster_1')
NI_PCIe_6363(  'ni_pcie_6363_0',  pulseblaster_0, 'fast clock')
NovaTechDDS9M( 'novatechdds9m_0', pulseblaster_0, 'slow clock')#flag 6
NovaTechDDS9M( 'novatechdds9m_1', pulseblaster_0, 'slow clock')#flag 1
NovaTechDDS9M( 'novatechdds9m_1', pulseblaster_0, 'slow clock')#flag 7


#DigitalOut(     'Fast_Clock',                           pulseblaster_0,         'flag 0')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 1')                                       #NT_1_T
DigitalOut(     'Novatech_1_1',                          pulseblaster_0,         'flag 2')                                       #NT_1_1
DigitalOut(     'Novatech_1_2',                          pulseblaster_0,         'flag 3')                                       #NT_1_2
DigitalOut(     'K_MOT',                                 pulseblaster_0,         'flag 4')                                       #NT_1_0
#DigitalOut(     'Wait',                                 pulseblaster_0,         'flag 5')
DigitalOut(     'Novatech_0_T',                          pulseblaster_0,         'flag 6')                                       #NT_0_T
DigitalOut(     'Novatech_2_T',                          pulseblaster_0,         'flag 7')                                       #NT_2_T
#DigitalOut(     '',                                     pulseblaster_0,         'flag 8')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 9')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 10')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 11')
#DDS(            'unused1',                              pulseblaster_0,         'dds 0')
#DDS(            'unused2',                              pulseblaster_0,         'dds 1')


#DigitalOut(     '',                                     pulseblaster_0,         'flag 0')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 1')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 2')
#DigitalOut(     '',                                     pulseblaster_0,         'flag 3')
#DDS(            'unused1',                              pulseblaster_0,         'dds 0')
#DDS(            'unused2',                              pulseblaster_0,         'dds 1')



DDS(             'Rb_Central_MOT',                       novatechdds9m_0,        'channel 0')
DDS(             'Rb_Source_MOT',                        novatechdds9m_0,        'channel 1')
StaticDDS(       'Rb_Repump',                            novatechdds9m_0,        'channel 2')
StaticDDS(       'Rb_Main_Lock',                         novatechdds9m_0,        'channel 3')

#DDS(            'K_Main_MOT',                           novatechdds9m_1,        'channel 0')
#DDS(            '',                                     novatechdds9m_1,        'channel 1')
#StaticDDS(      'Rb_Probe',                             novatechdds9m_1,        'channel 2')
StaticDDS(       'K_Lock',                               novatechdds9m_1,        'channel 3')

#DDS(            '',                                     novatechdds9m_2,        'channel 0')
#DoubledDDS(     'K_Repump',                             novatechdds9m_2,        'channel 1')
#StaticDDS(      '',                                     novatechdds9m_2,        'channel 2')
#DoubledStaticDDS('',                                     novatechdds9m_2,        'channel 3')

AnalogOut(      'ASD',                                   ni_pcie_6363_0,         'ao0')
#AnalogOut(      '',                                     ni_pcie_6363_0,         'ao1')
#AnalogOut(      '',                                     ni_pcie_6363_0,         'ao2')
#AnalogOut(      '',                                     ni_pcie_6363_0,         'ao3')

DigitalOut(     'Rb_Central_MOT_RF_Switch',              ni_pcie_6363_0,         'port0/line0')                                  #NT_0_0
DigitalOut(     'Rb_Source_MOT_RF_Switch'                ni_pcie_6363_0,         'port0/line1')                                  #NT_0_1
DigitalOut(     'Rb_Repump_RF_Switch',                   ni_pcie_6363_0,         'port0/line2')                                  #NT_0_2
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line3')
DigitalOut(     'Novatech_2_0',                          ni_pcie_6363_0,         'port0/line4')                                  #NT_2_0
DigitalOut(     'K_Repump_RF_Switch',                    ni_pcie_6363_0,         'port0/line5')                                  #NT_2_1
DigitalOut(     'Novatech_2_2',                          ni_pcie_6363_0,         'port0/line6')                                  #NT_2_2
DigitalOut(     'Novatech_2_3',                          ni_pcie_6363_0,         'port0/line7')                                  #NT_2_3
Shutter(        'Rb_Source_MOT_Shutter',                 ni_pcie_6363_0,         'port0/line8', delay=(5e-3,5e-3))               #Sh_1_1
Shutter(        'Rb_Probe_Shutter',                      ni_pcie_6363_0,         'port0/line9', delay=(5e-3,5e-3))               #Sh_1_2
Shutter(     'Shutter_1_3',                              ni_pcie_6363_0,         'port0/line10', delay=(5e-3,5e-3))              #Sh_1_3
Shutter(     'Shuter_1_4',                               ni_pcie_6363_0,         'port0/line11', delay=(5e-3,5e-3))              #Sh_1_4
Shutter(     'Shutter_0_1',                              ni_pcie_6363_0,         'port0/line12', delay=(5e-3,5e-3))              #Sh_0_1
Shutter(     'Shutter_0_2',                              ni_pcie_6363_0,         'port0/line13', delay=(5e-3,5e-3))              #Sh_0_2
Shutter(     'Shutter_0_3',                              ni_pcie_6363_0,         'port0/line14', delay=(5e-3,5e-3))              #Sh_0_3
Shutter(     'Shutter_0_4',                              ni_pcie_6363_0,         'port0/line15', delay=(5e-3,5e-3))              #Sh_0_4
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line16')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line17')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line18')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line19')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line20')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line21')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line22')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line23')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line24')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line25')
#DigitalOut(     '',                                     ni_pcie_6363_0,         'port0/line26')
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
stop(0)