#####################################################################
#                                                                   #
# __main__.py                                                       #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
import labscript_utils.excepthook

import os

# Associate app windows with OS menu shortcuts:
import desktop_app
desktop_app.set_process_appid('blacs')


# Splash screen
from labscript_utils.splash import Splash
splash = Splash(os.path.join(os.path.dirname(__file__), 'blacs.svg'))
splash.show()

splash.update_text('importing standard library modules')
import subprocess
import sys
import time
from pathlib import Path
import platform
WINDOWS = platform.system() == 'Windows'

# No splash update for Qt - the splash code has already imported it:
import qtutils
from qtutils import *
import qtutils.icons
from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *
from qtutils.qt import QT_ENV


splash.update_text("importing zmq and zprocess")
import zmq
import zprocess
from zprocess import raise_exception_in_thread
import zprocess.locking


splash.update_text('importing h5_lock and h5py')
import labscript_utils.h5_lock, h5py


splash.update_text('importing labscript suite modules')
import labscript_utils
from labscript_utils.ls_zprocess import ProcessTree, ZMQServer
from labscript_utils.setup_logging import setup_logging
import labscript_utils.shared_drive
import blacs


process_tree = ProcessTree.instance()
process_tree.zlock_client.set_process_name('BLACS')


# Setup logging
logger = setup_logging('BLACS')
labscript_utils.excepthook.set_logger(logger)

logger.info(f'Python version {sys.version}')
logger.info(f'Platform: {sys.platform}')
logger.info(f'windows version: {sys.getwindowsversion() if WINDOWS else None}')
logger.info(f'PyZMQ version: {zmq.__version__}')
logger.info(f'ZMQ version: {zmq.zmq_version()}')
logger.info(f'h5py version: {h5py.version.info}')
logger.info(f'Qt enviroment: {QT_ENV}')
logger.info(f'PySide/PyQt version: {PYQT_VERSION_STR}')
logger.info(f'Qt version: {QT_VERSION_STR}')
logger.info(f'qtutils version: {qtutils.__version__}')
logger.info(f'zprocess version: {zprocess.__version__}')
logger.info(f'labscript_utils version: {labscript_utils.__version__}')
logger.info(f'BLACS version: {blacs.__version__}')

# Connection Table Code
from labscript_utils.connections import ConnectionTable
#Draggable Tab Widget Code
from labscript_utils.qtwidgets.dragdroptab import DragDropTabWidget
# Lab config code
from labscript_utils.labconfig import LabConfig
from labscript_profile import hostname
# Analysis Submission code
from blacs.analysis_submission import AnalysisSubmission
# Queue Manager Code
from blacs.experiment_queue import QueueManager, QueueTreeview
# Module containing hardware compatibility:
import labscript_devices
# Save/restore frontpanel code
from blacs.front_panel_settings import FrontPanelSettings
# Notifications system
from blacs.notifications import Notifications
# Preferences system
from labscript_utils.settings import Settings
#import settings_pages
import blacs.plugins as plugins

from blacs import BLACS_DIR


class BLACSWindow(QMainWindow):

    def closeEvent(self, event):
        if self.blacs.exit_complete:
            event.accept()
            if self.blacs._relaunch:
                logger.info('relaunching BLACS after quit')
                subprocess.Popen([sys.executable] + sys.argv)
        else:
            event.ignore()
            logger.info('destroy called')
            if not self.blacs.exiting:
                self.blacs.exiting = True
                self.blacs.queue.manager_running = False
                self.blacs.settings.close()
                experiment_server.shutdown()
                for module_name, plugin in self.blacs.plugins.items():
                    try:
                        plugin.close()
                    except Exception as e:
                        logger.error('Could not close plugin %s. Error was: %s'%(module_name,str(e)))

                inmain_later(self.blacs.on_save_exit)

            QTimer.singleShot(100,self.close)


class EasterEggButton(QToolButton):
    def __init__(self):
        QToolButton.__init__(self)
        self.setFixedSize(24, 24) # Ensure we're the same size as the other buttons
        self.icon_atom = QIcon(':qtutils/custom/atom')
        self.icon_smiley = QIcon(':qtutils/fugue/smiley-lol')
        self.icon_none = QIcon(None)
        self.icon_mouse_over = self.icon_atom
        self.clicked.connect(self.on_click)

    def enterEvent(self, event):
        """Make the icon only visible on mouse-over"""
        self.setIcon(self.icon_mouse_over)
        return QToolButton.enterEvent(self, event)

    def leaveEvent(self, event):
        if self.icon_mouse_over is self.icon_atom:
            self.setIcon(self.icon_none)
        return QToolButton.leaveEvent(self, event)

    def on_click(self):
        """Run Measure Ball"""
        # Change icon so the user knows something happened, since the game can take a
        # few seconds to start
        self.icon_mouse_over = self.icon_smiley
        self.setIcon(self.icon_mouse_over)
        # Ensure they can't run the game twice at once:
        self.setEnabled(False)
        # Wait for the subprocess in a thread so that we know when it quits:
        qtutils.inthread(self.run_measure_ball)

    def run_measure_ball(self):
        try:
            from subprocess import check_call
            MEASURE_BALL = os.path.join(BLACS_DIR, 'measure_ball', 'RabiBall.exe')
            if not WINDOWS:
                try:
                    check_call(['wine', '--version'])
                except OSError:
                    msg = 'Game cannot be run on Linux or OSX unless WINE is installed'
                    main_window = inmain(self.window)
                    inmain(QMessageBox.warning, main_window, 'BLACS', msg)
                    return
                else:
                    cmd = ['wine', MEASURE_BALL]
            else:
                cmd = [MEASURE_BALL]
            check_call(cmd, cwd=os.path.dirname(MEASURE_BALL))
        finally:
            # Remove smiley, go back to hiding if mouse not over button:
            self.icon_mouse_over = self.icon_atom
            inmain(self.setIcon, self.icon_none)
            inmain(self.setEnabled, True)


class BLACS(object):

    tab_widget_ids = 7

    def __init__(self,application):
        splash.update_text('loading graphical interface')
        self.qt_application = application
        #self.qt_application.aboutToQuit.connect(self.destroy)
        self._relaunch = False
        self.exiting = False
        self.exit_complete = False

        logger.info('Loading BLACS ui')
        #self.ui = BLACSWindow(self).ui
        loader = UiLoader()
        loader.registerCustomWidget(QueueTreeview)
        #loader.registerCustomPromotion('BLACS',BLACSWindow)
        self.ui = loader.load(os.path.join(BLACS_DIR, 'main.ui'), BLACSWindow())
        logger.info('BLACS ui loaded')
        self.ui.blacs=self
        self.tab_widgets = {}
        self.exp_config = exp_config # Global variable
        self.settings_path = settings_path # Global variable
        self.connection_table = connection_table # Global variable
        self.connection_table_h5file = self.exp_config.get('paths','connection_table_h5')
        self.connection_table_labscript = self.exp_config.get('paths','connection_table_py')

        # Setup the UI
        self.ui.main_splitter.setStretchFactor(0,0)
        self.ui.main_splitter.setStretchFactor(1,1)

        self.tablist = {}
        self.panes = {}
        self.settings_dict = {}

        splash.update_text('loading device front panel settings')
        # Find which devices are connected to BLACS, and what their labscript class names are:
        logger.info('finding connected devices in connection table')
        self.attached_devices = self.connection_table.get_attached_devices()

        # Store the panes in a dictionary for easy access
        self.panes['tab_top_vertical_splitter'] = self.ui.tab_top_vertical_splitter
        self.panes['tab_bottom_vertical_splitter'] = self.ui.tab_bottom_vertical_splitter
        self.panes['tab_horizontal_splitter'] = self.ui.tab_horizontal_splitter
        self.panes['main_splitter'] = self.ui.main_splitter

        # Get settings to restore
        logger.info('Loading front panel settings')
        self.front_panel_settings = FrontPanelSettings(self.settings_path, self.connection_table)
        self.front_panel_settings.setup(self)
        settings,question,error,tab_data = self.front_panel_settings.restore()

        # TODO: handle question/error cases

        logger.info('restoring window data')
        self.restore_window(tab_data)

        splash.update_text('creating device tabs...')
        # Create the notebooks
        logger.info('Creating tab widgets')
        for i in range(4):
            self.tab_widgets[i] = DragDropTabWidget(self.tab_widget_ids)
            self.tab_widgets[i].setElideMode(Qt.ElideRight)
            getattr(self.ui,'tab_container_%d'%i).addWidget(self.tab_widgets[i])

        logger.info('Instantiating devices')
        self.failed_device_settings = {}
        for device_name, labscript_device_class_name in list(self.attached_devices.items()):
            try:
                self.settings_dict.setdefault(device_name,{"device_name":device_name})
                # add common keys to settings:
                self.settings_dict[device_name]["connection_table"] = self.connection_table
                self.settings_dict[device_name]["front_panel_settings"] = settings[device_name] if device_name in settings else {}
                self.settings_dict[device_name]["saved_data"] = tab_data[device_name]['data'] if device_name in tab_data else {}
                # Instantiate the device
                logger.info('instantiating %s'%device_name)
                TabClass = labscript_devices.get_BLACS_tab(labscript_device_class_name)
                self.tablist[device_name] = TabClass(self.tab_widgets[0],self.settings_dict[device_name])
            except Exception:
                self.failed_device_settings[device_name] = {"front_panel": self.settings_dict[device_name]["front_panel_settings"], "save_data": self.settings_dict[device_name]["saved_data"]}
                del self.settings_dict[device_name]
                del self.attached_devices[device_name]
                self.connection_table.remove_device(device_name)
                raise_exception_in_thread(sys.exc_info())

        splash.update_text('instantiating plugins')
        logger.info('Instantiating plugins')
        # setup the plugin system
        settings_pages = []
        self.plugins = {}
        plugin_settings = eval(tab_data['BLACS settings']['plugin_data']) if 'plugin_data' in tab_data['BLACS settings'] else {}
        for module_name, module in plugins.modules.items():
            try:
                # instantiate the plugin
                self.plugins[module_name] = module.Plugin(plugin_settings[module_name] if module_name in plugin_settings else {})
            except Exception:
                logger.exception('Could not instantiate plugin \'%s\'. Skipping' % module_name)

        logger.info('creating plugin tabs')
        # setup the plugin tabs
        for module_name, plugin in self.plugins.items():
            try:
                if hasattr(plugin, 'get_tab_classes'):
                    tab_dict = {}

                    for tab_name, TabClass in plugin.get_tab_classes().items():
                        settings_key = "{}: {}".format(module_name, tab_name)
                        self.settings_dict.setdefault(settings_key, {"tab_name": tab_name})
                        self.settings_dict[settings_key]["front_panel_settings"] = settings[settings_key] if settings_key in settings else {}
                        self.settings_dict[settings_key]["saved_data"] = tab_data[settings_key]['data'] if settings_key in tab_data else {}

                        self.tablist[settings_key] = TabClass(self.tab_widgets[0], self.settings_dict[settings_key])
                        tab_dict[tab_name] = self.tablist[settings_key]

                    if hasattr(plugin, 'tabs_created'):
                        plugin.tabs_created(tab_dict)

            except Exception:
                logger.exception('Could not instantiate tab for plugin \'%s\'. Skipping')

        logger.info('reordering tabs')
        self.order_tabs(tab_data)

        splash.update_text("initialising analysis submission")
        logger.info('starting analysis submission thread')
        # setup analysis submission
        self.analysis_submission = AnalysisSubmission(self,self.ui)
        if 'analysis_data' not in tab_data['BLACS settings']:
            tab_data['BLACS settings']['analysis_data'] = {}
        else:
            tab_data['BLACS settings']['analysis_data'] = eval(tab_data['BLACS settings']['analysis_data'])
        self.analysis_submission.restore_save_data(tab_data['BLACS settings']["analysis_data"])

        splash.update_text("starting queue manager")
        logger.info('starting queue manager thread')
        # Setup the QueueManager
        self.queue = QueueManager(self,self.ui)
        if 'queue_data' not in tab_data['BLACS settings']:
            tab_data['BLACS settings']['queue_data'] = {}
        else:
            # quick fix for qt objects not loading that were saved before qtutil 2 changes
            try:
                tab_data['BLACS settings']['queue_data'] = eval(tab_data['BLACS settings']['queue_data'])
            except NameError:
                tab_data['BLACS settings']['queue_data'] = {}
        self.queue.restore_save_data(tab_data['BLACS settings']['queue_data'])

        blacs_data = {'exp_config':self.exp_config,
                      'ui':self.ui,
                      'set_relaunch':self.set_relaunch,
                      'plugins':self.plugins,
                      'connection_table_h5file':self.connection_table_h5file,
                      'connection_table_labscript':self.connection_table_labscript,
                      'experiment_queue':self.queue
                     }

        def create_menu(parent, menu_parameters):
            if 'name' in menu_parameters:
                if 'menu_items' in menu_parameters:
                    child = parent.addMenu(menu_parameters['name'])
                    for child_menu_params in menu_parameters['menu_items']:
                        create_menu(child,child_menu_params)
                else:
                    if 'icon' in menu_parameters:
                        child = parent.addAction(QIcon(menu_parameters['icon']), menu_parameters['name'])
                    else:
                        child = parent.addAction(menu_parameters['name'])

                if 'action' in menu_parameters:
                    child.triggered.connect(menu_parameters['action'])

            elif 'separator' in menu_parameters:
                parent.addSeparator()

        # setup the Notification system
        logger.info('setting up notification system')
        splash.update_text('setting up notification system')
        self.notifications = Notifications(blacs_data)

        settings_callbacks = []
        for module_name, plugin in self.plugins.items():
            try:
                # Setup settings page
                settings_pages.extend(plugin.get_setting_classes())
                # Setup menu
                if plugin.get_menu_class():
                    # must store a reference or else the methods called when the menu actions are triggered
                    # (contained in this object) will be garbaged collected
                    menu = plugin.get_menu_class()(blacs_data)
                    create_menu(self.ui.menubar,menu.get_menu_items())
                    plugin.set_menu_instance(menu)

                # Setup notifications
                plugin_notifications = {}
                for notification_class in plugin.get_notification_classes():
                    self.notifications.add_notification(notification_class)
                    plugin_notifications[notification_class] = self.notifications.get_instance(notification_class)
                plugin.set_notification_instances(plugin_notifications)

                # Register callbacks
                callbacks = plugin.get_callbacks()
                # save the settings_changed callback in a separate list for setting up later
                if isinstance(callbacks,dict) and 'settings_changed' in callbacks:
                    settings_callbacks.append(callbacks['settings_changed'])

            except Exception:
                logger.exception('Plugin \'%s\' error. Plugin may not be functional.'%module_name)


        # setup the BLACS preferences system
        splash.update_text('setting up preferences system')
        logger.info('setting up preferences system')
        self.settings = Settings(file=self.settings_path, parent = self.ui, page_classes=settings_pages)
        for callback in settings_callbacks:
            self.settings.register_callback(callback)

        # update the blacs_data dictionary with the settings system
        blacs_data['settings'] = self.settings

        for module_name, plugin in self.plugins.items():
            try:
                plugin.plugin_setup_complete(blacs_data)
            except Exception:
                logger.exception('Error in plugin_setup_complete() for plugin \'%s\'. Trying again with old call signature...' % module_name)
                # backwards compatibility for old plugins
                try:
                    plugin.plugin_setup_complete()
                    logger.warning('Plugin \'%s\' using old API. Please update Plugin.plugin_setup_complete method to accept a dictionary of blacs_data as the only argument.'%module_name)
                except Exception:
                    logger.exception('Plugin \'%s\' error. Plugin may not be functional.'%module_name)

        # Connect menu actions
        self.ui.actionOpenPreferences.triggered.connect(self.on_open_preferences)
        self.ui.actionSave.triggered.connect(self.on_save_front_panel)
        self.ui.actionOpen.triggered.connect(self.on_load_front_panel)
        self.ui.actionExit.triggered.connect(self.ui.close)

        # Add hidden easter egg button to a random tab:
        logger.info('hiding easter eggs')
        import random
        if self.tablist:
            random_tab = random.choice(list(self.tablist.values())) 
            self.easter_egg_button = EasterEggButton()
            # Add the button before the other buttons in the tab's header:
            header = random_tab._ui.horizontalLayout
            for i in range(header.count()):
                if isinstance(header.itemAt(i).widget(), QToolButton):
                    header.insertWidget(i, self.easter_egg_button)
                    break

        splash.update_text('done')
        logger.info('showing UI')
        self.ui.show()

    def set_relaunch(self,value):
        self._relaunch = bool(value)

    def restore_window(self,tab_data):
        # read out position settings:
        try:
            # There are some dodgy hacks going on here to try and restore the window position correctly
            # Unfortunately Qt has two ways of measuring teh window position, one with the frame/titlebar
            # and one without. If you use the one that measures including the titlebar, you don't
            # know what the window size was when the window was UNmaximized.
            #
            # Anyway, no idea if this works cross platform (tested on windows 8)
            # Feel free to rewrite this, along with the code in front_panel_settings.py
            # which stores the values
            #
            # Actually this is a waste of time because if you close when maximized, reoopen and then
            # de-maximize, the window moves to a random position (not the position it was at before maximizing)
            # so bleh!
            self.ui.move(tab_data['BLACS settings']["window_xpos"]-tab_data['BLACS settings']['window_frame_width']/2,tab_data['BLACS settings']["window_ypos"]-tab_data['BLACS settings']['window_frame_height']+tab_data['BLACS settings']['window_frame_width']/2)
            self.ui.resize(tab_data['BLACS settings']["window_width"],tab_data['BLACS settings']["window_height"])

            if 'window_maximized' in tab_data['BLACS settings'] and tab_data['BLACS settings']['window_maximized']:
                self.ui.showMaximized()

            for pane_name,pane in self.panes.items():
                pane.setSizes(tab_data['BLACS settings'][pane_name])

        except Exception as e:
            logger.warning("Unable to load window and notebook defaults. Exception:"+str(e))

    def order_tabs(self,tab_data):
        # Move the tabs to the correct notebook
        for tab_name in self.tablist.keys():
            notebook_num = 0
            if tab_name in tab_data:
                notebook_num = int(tab_data[tab_name]["notebook"])
                if notebook_num not in self.tab_widgets:
                    notebook_num = 0

            #Find the notebook the tab is in, and remove it:
            for notebook in self.tab_widgets.values():
                tab_index = notebook.indexOf(self.tablist[tab_name]._ui)
                if tab_index != -1:
                    tab_text = notebook.tabText(tab_index)
                    notebook.removeTab(tab_index)
                    self.tab_widgets[notebook_num].addTab(self.tablist[tab_name]._ui,tab_text)
                    break

        splash.update_text('restoring tab positions...')
        # # Now that all the pages are created, reorder them!
        for tab_name in self.tablist.keys():
            if tab_name in tab_data:
                notebook_num = int(tab_data[tab_name]["notebook"])
                if notebook_num in self.tab_widgets:
                    self.tab_widgets[notebook_num].tab_bar.moveTab(self.tab_widgets[notebook_num].indexOf(self.tablist[tab_name]._ui),int(tab_data[tab_name]["page"]))

        # # Now that they are in the correct order, set the correct one visible
        for tab_name, data in tab_data.items():
            if tab_name == 'BLACS settings':
                continue
            # if the notebook still exists and we are on the entry that is visible
            if bool(data["visible"]) and int(data["notebook"]) in self.tab_widgets:
                self.tab_widgets[int(data["notebook"])].tab_bar.setCurrentIndex(int(data["page"]))

    def update_all_tab_settings(self,settings,tab_data):
        for tab_name,tab in self.tablist.items():
            self.settings_dict[tab_name]["front_panel_settings"] = settings[tab_name] if tab_name in settings else {}
            self.settings_dict[tab_name]["saved_data"] = tab_data[tab_name]['data'] if tab_name in tab_data else {}
            tab.update_from_settings(self.settings_dict[tab_name])


    def on_load_front_panel(self,*args,**kwargs):
        # get the file:
        # create file chooser dialog
        dialog = QFileDialog(None,"Select file to load", self.exp_config.get('paths','experiment_shot_storage'), "HDF5 files (*.h5 *.hdf5)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setFileMode(QFileDialog.ExistingFile)
        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            filepath = str(selected_files[0])
            # Qt has this weird behaviour where if you type in the name of a file that exists
            # but does not have the extension you have limited the dialog to, the OK button is greyed out
            # but you can hit enter and the file will be selected.
            # So we must check the extension of each file here!
            if filepath.endswith('.h5') or filepath.endswith('.hdf5'):
                try:
                    # TODO: Warn that this will restore values, but not channels that are locked
                    message = QMessageBox()
                    message.setText("""Warning: This will modify front panel values and cause device output values to update.
                    \nThe queue and files waiting to be sent for analysis will be cleared.
                    \n
                    \nNote: Channels that are locked will not be updated.\n\nDo you wish to continue?""")
                    message.setIcon(QMessageBox.Warning)
                    message.setWindowTitle("BLACS")
                    message.setStandardButtons(QMessageBox.Yes|QMessageBox.No)

                    if message.exec_() == QMessageBox.Yes:
                        front_panel_settings = FrontPanelSettings(filepath, self.connection_table)
                        settings,question,error,tab_data = front_panel_settings.restore()
                        #TODO: handle question/error

                        # Restore window data
                        self.restore_window(tab_data)
                        self.order_tabs(tab_data)
                        self.update_all_tab_settings(settings,tab_data)

                        # restore queue data
                        if 'queue_data' not in tab_data['BLACS settings']:
                            tab_data['BLACS settings']['queue_data'] = {}
                        else:
                            # quick fix for qt objects not loading that were saved before qtutil 2 changes
                            try:
                                tab_data['BLACS settings']['queue_data'] = eval(tab_data['BLACS settings']['queue_data'])
                            except NameError:
                                tab_data['BLACS settings']['queue_data'] = {}
                        self.queue.restore_save_data(tab_data['BLACS settings']['queue_data'])
                        # restore analysis data
                        if 'analysis_data' not in tab_data['BLACS settings']:
                            tab_data['BLACS settings']['analysis_data'] = {}
                        else:
                            tab_data['BLACS settings']['analysis_data'] = eval(tab_data['BLACS settings']['analysis_data'])
                        self.analysis_submission.restore_save_data(tab_data['BLACS settings']["analysis_data"])
                except Exception as e:
                    logger.exception("Unable to load the front panel in %s."%(filepath))
                    message = QMessageBox()
                    message.setText("Unable to load the front panel. The error encountered is printed below.\n\n%s"%str(e))
                    message.setIcon(QMessageBox.Information)
                    message.setWindowTitle("BLACS")
                    message.exec_()
                finally:
                    dialog.deleteLater()
            else:
                dialog.deleteLater()
                message = QMessageBox()
                message.setText("You did not select a file ending with .h5 or .hdf5. Please try again")
                message.setIcon(QMessageBox.Information)
                message.setWindowTitle("BLACS")
                message.exec_()
                QTimer.singleShot(10,self.on_load_front_panel)

    def on_save_exit(self):
        # Save front panel
        data = self.front_panel_settings.get_save_data()

        if len(self.failed_device_settings) > 0:
            message = ('Save data from broken tabs? \n Broken tabs are: \n {}'.format(list(self.failed_device_settings.keys())))
            reply = QMessageBox.question(self.ui, 'Save broken tab data?', message,
                                               QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                data[0].update(self.failed_device_settings)

        # with h5py.File(self.settings_path,'r+') as h5file:
           # if 'connection table' in h5file:
               # del h5file['connection table']

        self.front_panel_settings.save_front_panel_to_h5(self.settings_path,data[0],data[1],data[2],data[3],{"overwrite":True},force_new_conn_table=True)
        logger.info('Shutting down workers')
        for tab in self.tablist.values():
            # Tell tab to shutdown its workers if it has a method to do so.
            if hasattr(tab, 'shutdown_workers'):
                tab.shutdown_workers()

        QTimer.singleShot(100, self.finalise_quit)

    def finalise_quit(self, deadline=None, pending_threads=None):
        logger.info('finalise_quit called')
        WORKER_SHUTDOWN_TIMEOUT = 2
        if deadline is None:
            deadline = time.time() + WORKER_SHUTDOWN_TIMEOUT
        if pending_threads is None:
            pending_threads = {}
        overdue = time.time() > deadline
        # Check for worker shutdown completion:
        for name, tab in list(self.tablist.items()):
            # Immediately close tabs that don't support finalise_close_tab()
            if not hasattr(tab, 'finalise_close_tab'):
                try:
                    current_page = tab.close_tab(finalise=False)
                except Exception as e:
                    logger.error('Couldn\'t close tab:\n%s' % str(e))
                del self.tablist[name]
                continue
            fatal_error = tab.state == 'fatal error'
            if not tab.shutdown_workers_complete and overdue or fatal_error:
                # Give up on cleanly shutting down this tab's worker processes:
                tab.shutdown_workers_complete = True
            if tab.shutdown_workers_complete:
                if name not in pending_threads:
                    # Either worker shutdown completed or we gave up. Close the tab.
                    try:
                        current_page = tab.close_tab(finalise=False)
                    except Exception as e:
                        logger.error('Couldn\'t close tab:\n%s' % str(e))
                        del self.tablist[name]
                    else:
                        # Call finalise_close_tab in a thread since it can be blocking.
                        # It has its own timeout however, so we do not need to keep
                        # track of whether tabs are taking too long to finalise_close()
                        pending_threads[name] = inthread(
                            tab.finalise_close_tab, current_page
                        )
                elif not pending_threads[name].is_alive():
                    # finalise_close_tab completed, tab is closed and worker terminated
                    pending_threads[name].join()
                    del pending_threads[name]
                    del self.tablist[name]
        if not self.tablist:
            # All tabs are closed.
            self.exit_complete = True
            logger.info('quitting')
            return
        QTimer.singleShot(100, lambda: self.finalise_quit(deadline, pending_threads))
            

    def on_save_front_panel(self,*args,**kwargs):
        data = self.front_panel_settings.get_save_data()

        # Open save As dialog
        dialog = QFileDialog(None,"Save BLACS state", self.exp_config.get('paths','experiment_shot_storage'), "HDF5 files (*.h5)")
        try:
            dialog.setViewMode(QFileDialog.Detail)
            dialog.setFileMode(QFileDialog.AnyFile)
            dialog.setAcceptMode(QFileDialog.AcceptSave)

            if dialog.exec_():
                current_file = str(dialog.selectedFiles()[0])
                if not current_file.endswith('.h5'):
                    current_file += '.h5'
                self.front_panel_settings.save_front_panel_to_h5(current_file,data[0],data[1],data[2],data[3])
        except Exception:
            raise
        finally:
            dialog.deleteLater()

    def on_open_preferences(self,*args,**kwargs):
        self.settings.create_dialog()

class ExperimentServer(ZMQServer):
    def handler(self, h5_filepath):
        print(h5_filepath)
        message = self.process(h5_filepath)
        logger.info('Request handler: %s ' % message.strip())
        return message

    @inmain_decorator(wait_for_return=True)
    def process(self,h5_filepath):
        # Convert path to local slashes and shared drive prefix:
        logger.info('received filepath: %s'%h5_filepath)
        h5_filepath = labscript_utils.shared_drive.path_to_local(h5_filepath)
        logger.info('local filepath: %s'%h5_filepath)
        return app.queue.process_request(h5_filepath)


if __name__ == '__main__':
    if 'tracelog' in sys.argv:
        ##########
        import labscript_utils.tracelog
        labscript_utils.tracelog.log(os.path.join(BLACS_DIR, 'blacs_trace.log'),
                                     ['__main__','BLACS.tab_base_classes',
                                      'qtutils',
                                      'labscript_utils.qtwidgets.ddsoutput',
                                      'labscript_utils.qtwidgets.analogoutput',
                                      'BLACS.hardware_interfaces.ni_pcie_6363',
                                      'BLACS.hardware_interfaces.output_classes',
                                      'BLACS.device_base_class',
                                      'BLACS.tab_base_classes',
                                      'BLACS.plugins.connection_table',
                                      'BLACS.recompile_and_restart',
                                      'filewatcher',
                                      'queue',
                                      'notifications',
                                      'connections',
                                      'analysis_submission',
                                      'settings',
                                      'front_panel_settings',
                                      'labscript_utils.h5_lock',
                                      'labscript_utils.shared_drive',
                                      'labscript_utils.labconfig',
                                      'zprocess',
                                     ], sub=True)

    splash.update_text('loading labconfig')
    required_config_params = {
        "DEFAULT": ["apparatus_name", "app_saved_configs"],
        "programs": ["text_editor", "text_editor_arguments",],
        "paths": ["shared_drive", "connection_table_h5", "connection_table_py",],
        "ports": ["BLACS", "lyse"],
    }
    exp_config = LabConfig(required_params=required_config_params)
    settings_dir = Path(exp_config.get('DEFAULT', 'app_saved_configs'), 'blacs')
    if not settings_dir.exists():
        os.makedirs(settings_dir, exist_ok=True)
    settings_path = str(settings_dir / f'{hostname()}_BLACS.h5')

    port = int(exp_config.get('ports','BLACS'))

    # Start experiment server
    splash.update_text('starting experiment server')
    experiment_server = ExperimentServer(port)

    # Create Connection Table object
    splash.update_text('loading connection table')
    logger.info('About to load connection table: %s'%exp_config.get('paths','connection_table_h5'))
    connection_table_h5_file = exp_config.get('paths','connection_table_h5')
    connection_table = ConnectionTable(connection_table_h5_file, logging_prefix='BLACS', exceptions_in_thread=True)

    logger.info('connection table loaded')

    splash.update_text('initialising Qt application')
    qapplication = QApplication.instance()
    if qapplication is None:
        qapplication = QApplication(sys.argv)
    qapplication.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    logger.info('QApplication instantiated')
    app = BLACS(qapplication)

    logger.info('BLACS instantiated')
    splash.hide()

    def execute_program():
        qapplication.exec_()

    sys.exit(execute_program())
