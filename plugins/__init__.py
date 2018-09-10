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
from __future__ import division, unicode_literals, print_function, absolute_import

import os
import sys
import logging
import importlib
from collections import defaultdict
from labscript_utils.labconfig import LabConfig
from blacs import BLACS_DIR
PLUGINS_DIR = os.path.join(BLACS_DIR, 'plugins')

default_plugins = ['connection_table', 'general', 'theme']

logger = logging.getLogger('BLACS.plugins')

exp_config = LabConfig()
if not exp_config.has_section('BLACS/plugins'):
    exp_config.add_section('BLACS/plugins')

modules = {}
for module_name in os.listdir(PLUGINS_DIR):
    if os.path.isdir(os.path.join(PLUGINS_DIR, module_name)) and module_name != '__pycache__':
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


DEFAULT_PRIORITY = 10

class Callback(object):
    """Class wrapping a callable. At present only differs from a regular
    function in that it has a "priority" attribute - lower numbers means
    higher priority. If there are multiple callbacks triggered by the same
    event, they will be returned in order of priority by get_callbacks"""
    def __init__(self, func, priority=DEFAULT_PRIORITY):
        self.priority = priority
        self.func = func

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


class callback(object):
    """Decorator to turn a function into a Callback object. Presently
    optional, and only required if the callback needs to have a non-default
    priority set"""
    # Instantiate the decorator:
    def __init__(self, priority=DEFAULT_PRIORITY):
        self.priority = priority
    # Call the decorator
    def __call__(self, func):
        return Callback(func, priority)


_callbacks = None


def get_callbacks(self, name, update_cache=False):
    """Return all the callbacks for a particular name, in order of priority"""
    global _callbacks
    import __main__
    BLACS = __main__.app

    if update_cache or _callbacks is None:
        _callbacks = defaultdict(list)
        for plugin in BLACS.plugins.values():
            try:
                callbacks = plugin.get_callbacks()
                if callbacks is not None:
                    for callback_name, callback in callbacks.items():
                        _callbacks[callback_name].append(callback)
            except Exception as e:
                logger.exception('Error getting callbacks from %s.' % str(plugin))
                

        # Sort all callbacks by priority:
        for name in _callbacks:
            _callbacks[name].sort(key=lambda callback: getattr(callback, 'priority', DEFAULT_PRIORITY))

    return _callbacks.get(name, [])
