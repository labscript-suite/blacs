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
from labscript_utils.labconfig import LabConfig

default_plugins = ['connection_table', 'general', 'memory', 'theme']

logger = logging.getLogger('BLACS.plugins')

exp_config = LabConfig()
if not exp_config.has_section('BLACS/plugins'):
    exp_config.add_section('BLACS/plugins')

modules = {}
this_dir = os.path.dirname(os.path.abspath(__file__))
for module_name in os.listdir(this_dir):
    if os.path.isdir(os.path.join(this_dir, module_name)):
        # is it a new plugin?
        # If so lets add it to the config
        if not module_name in [name for name, val in exp_config.items('BLACS/plugins')]:
            exp_config.set('BLACS/plugins', module_name, str(module_name in default_plugins))

        # only load activated plugins
        if exp_config.getboolean('BLACS/plugins', module_name):
            try:
                module = importlib.import_module('blacs.plugins.'+module_name)
            except Exception:
                logger.exception('Could not import plugin \'%s\'. Skipping.'%module_name)
            else:
                modules[module_name] = module
