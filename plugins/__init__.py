#####################################################################
#                                                                   #
# /plugins/__init__.py                                              #
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
import sys
import logging
import importlib

logger = logging.getLogger('BLACS.plugins')

modules = {}
this_dir = os.path.dirname(os.path.abspath(__file__))
for module_name in os.listdir(this_dir):
    if os.path.isdir(os.path.join(this_dir, module_name)):
        try:
            module = importlib.import_module('blacs.plugins.'+module_name)
        except Exception:
            logger.exception('Could not import plugin \'%s\'. Skipping.'%module_name)
        else:
            modules[module_name] = module
