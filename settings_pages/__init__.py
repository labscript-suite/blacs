import os
for module in os.listdir(os.path.split(__file__)[0]):
    if module.endswith('.py'):
        exec 'from %s import *'%module[:-3]
del module