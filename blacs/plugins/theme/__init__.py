#####################################################################
#                                                                   #
# /plugins/theme/__init__.py                                        #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
import logging
import os

from qtutils import UiLoader
from qtutils.qt import QtCore, QtGui, QtWidgets

from blacs.plugins import PLUGINS_DIR

name = "GUI Theme"
module = "theme" # should be folder name
logger = logging.getLogger('BLACS.plugin.%s'%module)


# The colours with which we mix the theme's button colour for digital outputs and
# inverted digital outputs that are off, with and without the mouse pointer over them, and
# that are on:
OFF_COLOR = '#053605'
OFF_HOVER_COLOR = '#0b570b'
INVERTED_OFF_COLOR = '#0e2665'
INVERTED_OFF_HOVER_COLOR = '#163a92'
ON_COLOR = '#20e020'
INVERTED_ON_COLOR = '#20a0ff'
OFF_TEXT_COLOR = '#ffffff'
# Fraction by which we mix the button colour towards OFF_COLOR, OFF_HOVER_COLOR,
# INVERTED_OFF_COLOR or INVERTED_OFF_HOVER_COLOR:
OFF_FRACTION = 0.85
# Fraction by which we mix the button colour towards ON_COLOR or INVERTED_ON_COLOR:
ON_FRACTION = 0.9
# Factor by which we scale the HSV value of an output that is on for the top of its
# gradient. The bottom of the gradient has HSV value 1.
ON_TOP_VALUE_FACTOR = 0.85
# Fraction by which we mix the bottom of the gradient towards white under the mouse
# pointer:
ON_HOVER_FRACTION = 0.35
# Fraction by which we mix each fill colour towards the shadow colour for its border:
BORDER_FRACTION = 0.3
# Fraction by which we mix the text colour towards the fill colour for a disabled output:
DISABLED_TEXT_FRACTION = 0.5

STYLESHEET_TEMPLATE = """{name} {{
    font-size: 12px;
    background-color: {off};
    border: 1px solid {off_border};
    border-radius: 3px;
    padding: 2px;
    color: {off_text};
}}

{name}:hover {{
    background-color: {off_hover};
    border: 1px solid {off_hover_border};
}}

{name}:disabled {{
    background-color: {off};
    border: 1px solid {off_border};
    color: {off_disabled_text};
}}

{name}:checked {{
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 {on_top}, stop: 1 {on_bottom});
    border: 1px solid {on_border};
    color: {on_text};
}}

{name}:hover:checked {{
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 {on_top}, stop: 1 {on_hover_bottom});
    border: 1px solid {on_border};
}}

{name}:checked:disabled {{
    background-color: {on};
    border: 1px solid {on_border};
    color: {on_disabled_text};
}}
"""


def mix_colors(color0, color1, fraction):
    """The color that is a fraction of the way from color0 to color1"""
    color0 = QtGui.QColor(color0)
    color1 = QtGui.QColor(color1)
    return QtGui.QColor.fromRgbF(
        *((1 - fraction) * a + fraction * b
          for a, b in zip(color0.getRgbF()[:3], color1.getRgbF()[:3]))
    )


def _with_value(color, value):
    hue, saturation, _, _ = color.getHsvF()
    return QtGui.QColor.fromHsvF(max(hue, 0), saturation, value)


def _rgb(color):
    return 'rgb({}, {}, {})'.format(color.red(), color.green(), color.blue())


def _output_stylesheet(name, palette, off_color, off_hover_color, on_color):
    button = palette.color(QtGui.QPalette.ColorRole.Button)
    shadow = palette.color(QtGui.QPalette.ColorRole.Shadow)
    off = mix_colors(button, off_color, OFF_FRACTION)
    off_hover = mix_colors(button, off_hover_color, OFF_FRACTION)
    off_text = QtGui.QColor(OFF_TEXT_COLOR)
    on_text = QtGui.QColor('black')
    on = mix_colors(button, on_color, ON_FRACTION)
    on_top = _with_value(on, ON_TOP_VALUE_FACTOR * on.valueF())
    on_bottom = _with_value(on, 1)
    colors = {
        'off': off,
        'off_border': mix_colors(off, shadow, BORDER_FRACTION),
        'off_text': off_text,
        'off_hover': off_hover,
        'off_hover_border': mix_colors(off_hover, shadow, BORDER_FRACTION),
        'off_disabled_text': mix_colors(off_text, off, DISABLED_TEXT_FRACTION),
        'on': on,
        'on_top': on_top,
        'on_bottom': on_bottom,
        'on_hover_bottom': mix_colors(on_bottom, 'white', ON_HOVER_FRACTION),
        'on_border': mix_colors(on_top, shadow, BORDER_FRACTION),
        'on_text': on_text,
        'on_disabled_text': mix_colors(on_text, on, DISABLED_TEXT_FRACTION),
    }
    return STYLESHEET_TEMPLATE.format(
        name=name, **{key: _rgb(color) for key, color in colors.items()}
    )


def default_stylesheet():
    """The style sheet of the digital outputs, with colours made from the palette of
    QPushButton"""
    palette = QtWidgets.QApplication.palette('QPushButton')
    return '\n'.join(
        [
            _output_stylesheet(
                'DigitalOutput', palette, OFF_COLOR, OFF_HOVER_COLOR, ON_COLOR
            ),
            _output_stylesheet(
                'InvertedDigitalOutput',
                palette,
                INVERTED_OFF_COLOR,
                INVERTED_OFF_HOVER_COLOR,
                INVERTED_ON_COLOR,
            ),
        ]
    )


def is_default_stylesheet(stylesheet):
    """Return whether a stylesheet is the same as the default stylesheet, modulo whitespace"""

    def no_whitespace(s):
        return "".join(s.split())

    return no_whitespace(str(stylesheet)) == no_whitespace(default_stylesheet())


class Plugin(object):
    def __init__(self,initial_settings):
        self.menu = None
        self.notifications = {}
        self.BLACS = None
        self.initial_settings = initial_settings
        
    def get_menu_class(self):
        return None
        
    def get_notification_classes(self):
        return []
        
    def get_setting_classes(self):
        return [Setting]
        
    def get_callbacks(self):
        return {'settings_changed':self.update_stylesheet}
        
    def update_stylesheet(self):
        if self.BLACS is not None:
            # show centralwidget as a workaround to fix stylsheets
            # not beeing applied under PyQt5 on first draw
            self.BLACS['ui'].centralwidget.show()
            stylesheet_settings = self.BLACS['settings'].get_value(Setting,"stylesheet")
            if stylesheet_settings is None:
                stylesheet_settings = default_stylesheet()
            self.BLACS['ui'].centralwidget.setStyleSheet(self.unmodified_stylesheet + stylesheet_settings)
        
    def set_menu_instance(self,menu):
        self.menu = menu
                
    def set_notification_instances(self,notifications):
        self.notifications = notifications
        
    def plugin_setup_complete(self, BLACS):
        self.BLACS = BLACS
        self.unmodified_stylesheet = self.BLACS['ui'].centralwidget.styleSheet()
        self.update_stylesheet()
        # When the application palette changes, Qt sets the palettes of the platform theme
        # for each widget class after emitting paletteChanged:
        QtWidgets.QApplication.instance().paletteChanged.connect(
            lambda: QtCore.QTimer.singleShot(0, self.update_stylesheet)
        )
    
    def get_save_data(self):
        return {}
    
    def close(self):
        pass
        
    
class Setting(object):
    name = name

    def __init__(self,data):
        # This is our data store!
        self.data = data
        
        if not self.data.get('stylesheet'):
            # If it's absent or an empty string, use the default stylesheet:
            self.data.pop('stylesheet', None)
        # The default stylesheet shown in the dialog, if there is no custom stylesheet:
        self.shown_default = None
    
    def on_set_green_button_theme(self):
        self.widgets['stylesheet'].appendPlainText(default_stylesheet())
        
    # Create the page, return the page and an icon to use on the label (the class name attribute will be used for the label text)   
    def create_dialog(self,notebook):
        ui = UiLoader().load(os.path.join(PLUGINS_DIR, module, 'theme.ui'))
        
        # restore current stylesheet
        if 'stylesheet' in self.data:
            ui.stylesheet_text.setPlainText(self.data['stylesheet'])
            self.shown_default = None
        else:
            self.shown_default = default_stylesheet()
            ui.stylesheet_text.setPlainText(self.shown_default)
        ui.example_button.clicked.connect(self.on_set_green_button_theme)
        
        # save reference to widget
        self.widgets = {}
        self.widgets['stylesheet'] = ui.stylesheet_text
        self.widgets['example_button'] = ui.example_button
        
        return ui,None
    
    def get_value(self,name):
        if name in self.data:
            return self.data[name]
        
        return None
    
    def save(self):
        stylesheet = str(self.widgets['stylesheet'].toPlainText())
        if not stylesheet.endswith('\n'):
            # This is a way to distinguish between an intentionally blank
            # stylesheet, and an empty string, which used to be what was
            # stored When the user had made no changes, which now we take to
            # imply that they want to use the default stylesheet:
            stylesheet += '\n'
        if is_default_stylesheet(stylesheet) or (
            self.shown_default is not None and stylesheet.strip() == self.shown_default.strip()
        ):
            # Only save if it is not the default stylesheet:
            self.data.pop('stylesheet', None)
        else:
            self.data['stylesheet'] = stylesheet
        return self.data.copy()
        
    def close(self):
        self.widgets['example_button'].clicked.disconnect(self.on_set_green_button_theme)
        
    
