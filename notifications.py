import os

from PySide.QtCore import *
from PySide.QtGui import *
from PySide.QtUiTools import QUiLoader

class Notifications(object):
    def __init__(self, BLACS):
        self._BLACS = BLACS
        self._notifications = {}
        self._widgets = {}
        self._minimized_widgets = {}
        
    def add_notification(self, notification_class):
        if notification_class in self._notifications:
            return False        
        
        try:
            # instantiate the notification class
            # TODO: Do we need to pass anything in here?
            self._notifications[notification_class] = notification_class(self._BLACS) 
            
            # get the widget
            widget = self._notifications[notification_class].get_widget()
          
            # get details on whether the widget can be closed or hidden
            properties = self._notifications[notification_class].get_properties()
            
            # Function shortcuts
            show_func = lambda: self.show_notification(notification_class)
            hide_func = lambda: self.minimize_notification(notification_class)
            close_func = lambda: self.close_notification(notification_class)
            get_state = lambda: self.get_state(notification_class)
            
            # create layout/widget with appropriate buttons and the widget from the notification class
            ui = QUiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'notification_widget.ui'))            
            ui.hide_button.setVisible(bool(properties['can_hide']))
            ui.hide_button.clicked.connect(hide_func)
            ui.close_button.setVisible(bool(properties['can_close']))
            ui.close_button.clicked.connect(close_func)
            ui.widget_layout.addWidget(widget)
            #ui.hide()
            
            #TODO: Make the minimized widget
            ui2 = QUiLoader().load(os.path.join(os.path.dirname(os.path.realpath(__file__)),'notification_minimized_widget.ui'))
            #ui2.hide()
            if not hasattr(self._notifications[notification_class], 'name'):
                self._notifications[notification_class].name = notification_class.__name__
            ui2.name.setText(self._notifications[notification_class].name)
            ui2.show_button.setVisible(bool(properties['can_hide'])) #If you can hide, you can also show
            ui2.show_button.clicked.connect(show_func)
            ui2.close_button.setVisible(bool(properties['can_close']))
            ui2.close_button.clicked.connect(close_func)
            
            # pass the show/hide/close functions to the notfication class
            self._widgets[notification_class] = ui
            self._minimized_widgets[notification_class] = ui2
            self._notifications[notification_class].set_functions(show_func,hide_func,close_func,get_state)            
            
        except:
            # Cleanup 
            # TODO: cleanup a little more
            if notification_class in self._notifications:
                del self._notifications[notification_class]
            return False
        
        # add the widgets, initially hidden
        ui.setVisible(False)
        ui2.setVisible(False)
        self._BLACS['ui'].notifications.addWidget(ui)
        self._BLACS['ui'].notifications_minimized.addWidget(ui2)
        
        return True
    
    def get_instance(self, notification_class):
        if notification_class in self._notifications:
            return self._notifications[notification_class]
        return None
    
    def show_notification(self, notification_class):
        self._widgets[notification_class].setVisible(True)
        self._minimized_widgets[notification_class].setVisible(False)
        
    def close_notification(self, notification_class):
        self._widgets[notification_class].setVisible(False)
        self._minimized_widgets[notification_class].setVisible(False)
        
    def minimize_notification(self,notification_class):
        self._widgets[notification_class].setVisible(False)
        self._minimized_widgets[notification_class].setVisible(True)
    
    def get_state(self,notification_class):
        if self._widgets[notification_class].isVisible():
            return 'shown'
        elif self._minimized_widgets[notification_class].isVisible():
            return 'hidden'
        else:
            return 'closed'
    
    def close_all(self):
        for notification in self._notifications:
            try:
                notification.close()
            except:
                pass
                