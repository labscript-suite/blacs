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
import logging
from labscript_utils.labconfig import LabConfig
from labscript_utils.plugins import (
    DEFAULT_PRIORITY,
    BasePlugin,
    Callback,
    PluginManager,
    callback,
)
from blacs import BLACS_DIR

PLUGINS_DIR = os.path.join(BLACS_DIR, 'plugins')

default_plugins = ['connection_table', 'general', 'theme']

logger = logging.getLogger('BLACS.plugins')

PLUGIN_CONFIG_SECTION = 'BLACS/plugins'


def get_callbacks(name):
    """Return all the callbacks for a particular name, in order of priority."""
    return manager.get_event_handlers(name)


exp_config = LabConfig()
manager = PluginManager(
    'blacs.plugins',
    PLUGINS_DIR,
    exp_config,
    PLUGIN_CONFIG_SECTION,
    default_plugins,
    logger,
)
modules = manager.discover_modules()
