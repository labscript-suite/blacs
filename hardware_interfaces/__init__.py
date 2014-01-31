#####################################################################
#                                                                   #
# /hardware_interfaces/__init__.py                                  #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import os
device_list=[name.split('.py')[0] for name in os.listdir(os.path.dirname(__file__)) if name.endswith('.py') and name not in ['output_classes.py','__init__.py']]
