#####################################################################
#                                                                   #
# /notifications.py                                                 #
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

import logging
import os

from qtutils import UiLoader
from blacs import BLACS_DIR

logger = logging.getLogger('BLACS.NotificationManager') 

class Notifications(object):
    def __init__(self, BLACS):
        self._BLACS = BLACS
        self._notifications = {}
        self._widgets = {}
        self._minimized_widgets = {}
        self._closed_callbacks = {}
        self._hidden_callbacks = {}
        self._shown_callbacks = {}
        
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
            show_func = lambda callback=False: self.show_notification(notification_class, callback)
            hide_func = lambda callback=False: self.minimize_notification(notification_class, callback)
            close_func = lambda callback=False: self.close_notification(notification_class, callback)
            get_state = lambda: self.get_state(notification_class)
            
            # create layout/widget with appropriate buttons and the widget from the notification class
            ui = UiLoader().load(os.path.join(BLACS_DIR, 'notification_widget.ui'))            
            ui.hide_button.setVisible(bool(properties['can_hide']))
            ui.hide_button.clicked.connect(lambda: hide_func(True))
            ui.close_button.setVisible(bool(properties['can_close']))
            ui.close_button.clicked.connect(lambda: close_func(True))
            ui.widget_layout.addWidget(widget)
            #ui.hide()
            
            #save callbacks
            if 'closed_callback' in properties and callable(properties['closed_callback']):
                self._closed_callbacks[notification_class] = properties['closed_callback']
            elif 'closed_callback' in properties:
                logger.warning('"Closed" callback for notification class %s is not callable (and will not be called when the notification is closed. The callback specified was %s.'%(notification_class,properties['closed_callback']))
            
            if 'hidden_callback' in properties and callable(properties['hidden_callback']):
                self._hidden_callbacks[notification_class] = properties['hidden_callback']
            elif 'hidden_callback' in properties:
                logger.warning('"Hidden" callback for notification class %s is not callable (and will not be called when the notification is closed. The callback specified was %s.'%(notification_class,properties['hidden_callback']))
            
            if 'shown_callback' in properties and callable(properties['shown_callback']):
                self._shown_callbacks[notification_class] = properties['shown_callback']
            elif 'shown_callback' in properties:
                logger.warning('"Shown" callback for notification class %s is not callable (and will not be called when the notification is closed. The callback specified was %s.'%(notification_class,properties['shown_callback']))
                        
            
            #TODO: Make the minimized widget
            ui2 = UiLoader().load(os.path.join(BLACS_DIR, 'notification_minimized_widget.ui'))
            #ui2.hide()
            if not hasattr(self._notifications[notification_class], 'name'):
                self._notifications[notification_class].name = notification_class.__name__
            ui2.name.setText(self._notifications[notification_class].name)
            ui2.show_button.setVisible(bool(properties['can_hide'])) #If you can hide, you can also show
            ui2.show_button.clicked.connect(lambda: show_func(True))
            ui2.close_button.setVisible(bool(properties['can_close']))
            ui2.close_button.clicked.connect(lambda: close_func(True))
            
            # pass the show/hide/close functions to the notfication class
            self._widgets[notification_class] = ui
            self._minimized_widgets[notification_class] = ui2
            self._notifications[notification_class].set_functions(show_func,hide_func,close_func,get_state)            
            
        except:
            logger.exception('Failed to instantiate Notification class %s.'%notification_class)
            # Cleanup 
            # TODO: cleanup a little more
            if notification_class in self._notifications:
                del self._notifications[notification_class]
            return False
        
        # add the widgets, initially hidden
        ui.setVisible(False)
        ui2.setVisible(False)
        self._BLACS['ui'].notifications.insertWidget(1,ui)
        self._BLACS['ui'].notifications_minimized.insertWidget(0,ui2)
        
        return True
    
    def get_instance(self, notification_class):
        if notification_class in self._notifications:
            return self._notifications[notification_class]
        return None
    
    def show_notification(self, notification_class, callback):
        self._widgets[notification_class].setVisible(True)
        self._minimized_widgets[notification_class].setVisible(False)
        if callback and notification_class in self._shown_callbacks:
            try:
                self._shown_callbacks[notification_class]()
            except:
                logger.exception('Failed to run "shown" callback for notification class %s'%notification_class)
        
    def close_notification(self, notification_class, callback):
        self._widgets[notification_class].setVisible(False)
        self._minimized_widgets[notification_class].setVisible(False)
        if callback and notification_class in self._closed_callbacks:
            try:
                self._closed_callbacks[notification_class]()
            except:
                logger.exception('Failed to run "closed" callback for notification class %s'%notification_class)
        
    def minimize_notification(self,notification_class, callback):
        self._widgets[notification_class].setVisible(False)
        self._minimized_widgets[notification_class].setVisible(True)
        if callback and notification_class in self._hidden_callbacks:
            try:
                self._hidden_callbacks[notification_class]()
            except:
                logger.exception('Failed to run "hidden" callback for notification class %s'%notification_class)
    
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
                
