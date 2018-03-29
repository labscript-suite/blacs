#####################################################################
#                                                                   #
# /__init__.py                                                      #
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

__version__ = '2.2.0'


import os
from labscript_utils import labscript_suite_install_dir
if labscript_suite_install_dir is not None:
    BLACS_DIR = os.path.join(labscript_suite_install_dir, 'blacs')
else:
    # No labscript install directory found? Fall back to relying on __file__ and
    # hope that it is not a relative path that has been invalidated by a call to
    # os.chdir() between interpreter start and now (this can happen if blacs is run
    # with python 2 using "python -m blacs" whilst the current directory is the
    # parent of the blacs directory):
    BLACS_DIR = os.path.dirname(os.path.realpath(__file__))
if not os.path.isdir(BLACS_DIR):
    # Don't want to continue if we have not found the directory:
    msg = "Cannot locate the directory BLACS is installed in."
    raise RuntimeError(msg)
