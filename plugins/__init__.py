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
            module = importlib.import_module('BLACS.plugins.'+module_name)
        except Exception:
            logger.exception('Could not import plugin \'%s\'. Skipping.'%module_name)
        else:
            modules[module_name] = module
