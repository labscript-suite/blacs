import os
device_list=[name.split('.py')[0] for name in os.listdir(os.path.dirname(__file__)) if name.endswith('.py') and name not in ['output_classes.py','__init__.py']]
