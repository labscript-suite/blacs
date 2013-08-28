import os
from IPython import embed
for module in os.listdir(os.path.split(__file__)[0]):
    if os.path.isdir(os.path.join(os.path.split(__file__)[0],module)):
        exec 'import %s'%(module)
del module