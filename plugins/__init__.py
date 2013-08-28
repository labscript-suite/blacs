import os
__plugins__ = []
for module in os.listdir(os.path.split(__file__)[0]):
    if os.path.isdir(os.path.join(os.path.split(__file__)[0],module)):
        try:
            exec 'import %s'%(module)
            __plugins__.append(module)
        except Exception as e:
            pass
del module
del os

