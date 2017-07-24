#####################################################################
#                                                                   #
# /front_panel_settings.py                                          #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

import os
import logging

from qtutils.qt.QtCore import *
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *

import labscript_utils.excepthook
import numpy
import labscript_utils.h5_lock, h5py
from qtutils import *

# Connection Table Code
from connections import ConnectionTable

logger = logging.getLogger('BLACS.FrontPanelSettings')  

class FrontPanelSettings(object):
    def __init__(self,settings_path,connection_table):
        self.settings_path = settings_path
        self.connection_table = connection_table
        with h5py.File(settings_path,'a') as h5file:
            pass
        
    def setup(self,blacs):
        self.tablist = blacs.tablist
        self.attached_devices = blacs.attached_devices
        self.notebook = blacs.tab_widgets
        self.window = blacs.ui
        self.panes = blacs.panes
        self.blacs = blacs

    def restore(self):
        
        # Get list of DO/AO
        # Does the object have a name?
        #    yes: Then, find the device in the BLACS connection table that matches that name
        #         Also Find the device in the saved connection table.
        #         Do the connection table entries match?
        #             yes: Restore as is
        #             no:  Is it JUST the parent device and "connected to" that has changed?
        #                      yes: Restore to new device
        #                      no:  Show error that this device could not be restored
        #    no: Ok, so it isn't in the saved connection table
        #        Does this device/channel exist in the BLACS connection table?
        #            yes: Don't restore, show error that this chanel is now in use by a new device
        #                 Give option to restore anyway...
        #            no: Restore as is
        #
        # Display errors, give option to cancel starting of BLACS so that the connection table can be edited
        
        # Create saved connection table
        settings = {}
        question = {}
        error = {}
        tab_data = {'BLACS settings':{}}
        try:
            saved_ct = ConnectionTable(self.settings_path)
            ct_match,error = self.connection_table.compare_to(saved_ct)
            
            with h5py.File(self.settings_path,'r') as hdf5_file:
                # Get Tab Data
                dataset = hdf5_file['/front_panel'].get('_notebook_data',[])
                
                for row in dataset:
                    tab_data.setdefault(row['tab_name'],{})
                    try:
                        tab_data[row['tab_name']] = {'notebook':row['notebook'], 'page':row['page'], 'visible':row['visible'], 'data':eval(row['data'])}
                    except:
                        logger.info("Could not load tab data for %s"%row['tab_name'])
                
                #now get dataset attributes
                tab_data['BLACS settings'] = dict(dataset.attrs)
                
                # Get the front panel values
                if 'front_panel' in hdf5_file["/front_panel"]:
                    dataset = hdf5_file["/front_panel"].get('front_panel', [])
                    for row in dataset:
                        result = self.check_row(row,ct_match,self.connection_table,saved_ct)
                        columns = ['name', 'device_name', 'channel', 'base_value', 'locked', 'base_step_size', 'current_units']
                        data_dict = {}
                        for i in range(len(row)):
                            data_dict[columns[i]] = row[i]
                        settings,question,error = self.handle_return_code(data_dict,result,settings,question,error)
      
                # Else Legacy restore from GTK save data!
                else:
                    # open Datasets
                    type_list = ["AO", "DO", "DDS"]
                    for key in type_list:
                        dataset = hdf5_file["/front_panel"].get(key, [])
                        for row in dataset:
                            result = self.check_row(row,ct_match,self.connection_table,saved_ct)
                            columns = ['name', 'device_name', 'channel', 'base_value', 'locked', 'base_step_size', 'current_units']
                            data_dict = {}
                            for i in range(len(row)):
                                data_dict[columns[i]] = row[i]
                            settings,question,error = self.handle_return_code(data_dict,result,settings,question,error)
        except Exception,e:
            logger.info("Could not load saved settings")
            logger.info(e.message)
        return settings,question,error,tab_data
    
    def handle_return_code(self,row,result,settings,question,error):
        # 1: Restore to existing device
        # 2: Send to new device
        # 3: Device now exists, use saved values from unnamed device?
        #    Note that if 2 has happened, 3 will also happen
        #    This is because we have the original channel, and the moved channel in the same place
        #-1: Device no longer in the connection table, throw error
        #-2: Device parameters not compatible, throw error
        if type(result) == tuple:
            connection = result[1]
            result = result[0]
        
        if result == 1:
            settings.setdefault(row['device_name'],{})
            settings[row['device_name']][row['channel']] = row
        elif result == 2:
            settings.setdefault(connection.parent.name,{})
            settings[connection.parent.name][connection.parent_port] = row
        elif result == 3:
            question.setdefault(connection.parent.name,{})
            question[connection.parent.name][connection.parent_port] = row
        elif result == -1:
            error[row['device_name']+'_'+row['channel']] = row,"missing"
        elif result == -2:
            error[row['device_name']+'_'+row['channel']] = row,"changed"
            
        return settings,question,error
    
    def check_row(self,row,ct_match,blacs_ct,saved_ct):            
        # If it has a name
        if row[0] != "-":
            if ct_match:
                # Restore
                return 1
            else:
                # Find if this device is in the connection table
                connection = blacs_ct.find_by_name(row[0])
                connection2 = saved_ct.find_by_name(row[0])
                
                if connection:
                    # compare the two connections, see what differs
                    # if compare fails only on parent, connected to:
                    #    send to new parent
                    # else:
                    #     show error, device parameters not compatible with saved data
                    result,error = connection.compare_to(connection2)
                    
                    allowed_length = 0
                    if "parent_port" in error:
                        allowed_length += 1
                        
                    if len(error) > allowed_length:
                        return -2 # failure, device parameters not compatible                        
                    elif error == {} and connection.parent.name == connection2.parent.name:
                        return 1 # All details about this device match
                    else:
                        return 2,connection # moved to new device
                else:
                    # no longer in connection table, throw error
                    return -1
        else:
            # It doesn't have a name
            # Does the channel exist for this device in the connection table
            connection = blacs_ct.find_child(row[1],row[2])
            if connection:
                # throw error, device now exists, should we restore?
                return 3,connection
            else:
                # restore to device
                return 1
    
    @inmain_decorator(wait_for_return=True)    
    def get_save_data(self):
        tab_data = {}
        notebook_data = {}
        window_data = {}
        plugin_data = {}
        
        # iterate over all tabs
        for device_name,tab in self.tablist.items():
            tab_data[device_name] = {'front_panel':tab.settings['front_panel_settings'],
                                     'save_data':tab.get_save_data() if hasattr(tab,'get_save_data') else {}
                                  }
            
            # Find the notebook the tab is in
            #            
            # By default we assume it is in notebook0, on page 0. This way, if a tab gets lost somewhere, 
            # and isn't found to be a child of any notebook we know about, 
            # it will revert back to notebook 1 when the file is loaded upon program restart!
            current_notebook_name = 0 
            page = 0
            visible = False
            
            for notebook_name,notebook in self.notebook.items():
                if notebook.indexOf(tab._ui) != -1:                
                    current_notebook_name = notebook_name 
                    page = notebook.indexOf(tab._ui) 
                    visible = True if notebook.currentIndex() == page else False   
                    break
                                
            notebook_data[device_name] = {"notebook":current_notebook_name,"page":page, "visible":visible}
        
        # iterate over all plugins
        for module_name, plugin in self.blacs.plugins.items():
            try:
                plugin_data[module_name] = plugin.get_save_data()
            except Exception as e:
                logger.error('Could not save data for plugin %s. Error was: %s'%(module_name,str(e)))
        
        # save window data
        # Size of window       
        window_data["_main_window"] = {"width":self.window.normalGeometry().width(), 
                                       "height":self.window.normalGeometry().height(),
                                       "xpos":self.window.normalGeometry().x(),
                                       "ypos":self.window.normalGeometry().y(),
                                       "maximized":self.window.isMaximized(),
                                       "frame_height":abs(self.window.frameGeometry().height()-self.window.normalGeometry().height()),
                                       "frame_width":abs(self.window.frameGeometry().width()-self.window.normalGeometry().width()),
                                       "_analysis":self.blacs.analysis_submission.get_save_data(),
                                       "_queue":self.blacs.queue.get_save_data(),
                                      }
        # Pane positions
        for name,pane in self.panes.items():
            window_data[name] = pane.sizes()
        
        return tab_data,notebook_data,window_data,plugin_data
    
    @inmain_decorator(wait_for_return=True)
    def save_front_panel_to_h5(self,current_file,states,tab_positions,window_data,plugin_data,silent = {}, force_new_conn_table = False):        
        # Save the front panel!

        # Does the file exist?            
        #   Yes: Check connection table inside matches current connection table. Does it match?
        #        Yes: Does the file have a front panel already saved in it?
        #               Yes: Can we overwrite?
        #                  Yes: Delete front_panel group, save new front panel
        #                  No:  Create error dialog!
        #               No: Save front panel in here
        #   
        #        No: Return
        #   No: Create new file, place inside the connection table and front panel
            
        if os.path.isfile(current_file):
            save_conn_table = True if force_new_conn_table else False
            result = False
            if not save_conn_table:
                try:
                    new_conn = ConnectionTable(current_file)
                    result,error = self.connection_table.compare_to(new_conn)
                except:
                    # no connection table is present, so also save the connection table!
                    save_conn_table = True
            
            # if save_conn_table is True, we don't bother checking to see if the connection tables match, because save_conn_table is only true when the connection table doesn't exist in the current file
            # As a result, if save_conn_table is True, we ignore connection table checking, and save the connection table in the h5file.
            
            if save_conn_table or result:
                with h5py.File(current_file,'r+') as hdf5_file:
                    if hdf5_file['/'].get('front_panel') != None:
                        # Create a dialog to ask whether we can overwrite!
                        overwrite = False
                        if not silent:
                            message = QMessageBox()
                            message.setText("This file '%s' already contains a connection table."%current_file)
                            message.setInformativeText("Do you wish to replace the existing front panel configuration in this file?")
                            message.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                            message.setDefaultButton(QMessageBox.No)
                            message.setIcon(QMessageBox.Question)
                            message.setWindowTitle("BLACS")
                            resp = message.exec_()
                                                
                            if resp == QMessageBox.Yes :
                                overwrite = True   
                        else:
                            overwrite = silent["overwrite"]
                        
                        if overwrite:
                            # Delete Front panel group, save new front panel
                            del hdf5_file['/front_panel']
                            self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,plugin_data,save_conn_table)
                        else:
                            if not silent:                               
                                message = QMessageBox()
                                message.setText("Front Panel not saved.")
                                message.setIcon(QMessageBox.Information)
                                message.setWindowTitle("BLACS")
                                message.exec_()
                            else:
                                logger.info("Front Panel not saved as it already existed in the h5 file '"+current_file+"'")
                            return
                    else: 
                        # Save Front Panel in here
                        self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,plugin_data,save_conn_table)
            else:
                # Create Error dialog (invalid connection table)
                if not silent:
                    message = QMessageBox()
                    message.setText("The Front Panel was not saved as the file selected contains a connection table which is not a subset of the BLACS connection table.")
                    message.setIcon(QMessageBox.Information)
                    message.setWindowTitle("BLACS")
                    message.exec_() 
                else:
                    logger.info("Front Panel not saved as the connection table in the h5 file '"+current_file+"' didn't match the current connection table.")
                return
        else:
            with h5py.File(current_file,'w') as hdf5_file:
                # save connection table, save front panel                    
                self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,plugin_data,save_conn_table=True)
    
    @inmain_decorator(wait_for_return=True)
    def store_front_panel_in_h5(self, hdf5_file,tab_data,notebook_data,window_data,plugin_data,save_conn_table = False):
        if save_conn_table:
            if 'connection table' in hdf5_file:
                del hdf5_file['connection table']
            hdf5_file.create_dataset('connection table',data=self.connection_table.table)
        
        data_group = hdf5_file['/'].create_group('front_panel')
        
        front_panel_list = []
        other_data_list = []       
        front_panel_dtype = [('name','a256'),('device_name','a256'),('channel','a256'),('base_value',float),('locked',bool),('base_step_size',float),('current_units','a256')]
        max_od_length = 2 # empty dictionary
            
        # Iterate over each device within a class
        for device_name, device_state in tab_data.items():
            logger.debug("saving front panel for device:" + device_name) 
            # Insert front panel data into dataset
            for hardware_name, data in device_state["front_panel"].items():
                if data != {}:
                    front_panel_list.append((data['name'],
                                             device_name,
                                             hardware_name,
                                             data['base_value'],
                                             data['locked'],
                                             data['base_step_size'] if 'base_step_size' in data else 0,
                                             data['current_units'] if 'current_units' in data else ''
                                            )
                                           )               
            
            # Save "other data"
            od = repr(device_state["save_data"])
            other_data_list.append(od)            
            max_od_length = len(od) if len(od) > max_od_length else max_od_length            
        
        # Create datasets
        if front_panel_list:
            front_panel_array = numpy.empty(len(front_panel_list),dtype=front_panel_dtype)
            for i, row in enumerate(front_panel_list):
                front_panel_array[i] = row
            data_group.create_dataset('front_panel',data=front_panel_array)
                
        # Save tab data
        i = 0
        tab_data = numpy.empty(len(notebook_data),dtype=[('tab_name','a256'),('notebook','a2'),('page',int),('visible',bool),('data','a'+str(max_od_length))])
        for device_name,data in notebook_data.items():
            tab_data[i] = (device_name,data["notebook"],data["page"],data["visible"],other_data_list[i])
            i += 1
            
        # Save BLACS Main GUI Info
        dataset = data_group.create_dataset("_notebook_data",data=tab_data)
        dataset.attrs["window_width"] = window_data["_main_window"]["width"]
        dataset.attrs["window_height"] = window_data["_main_window"]["height"]
        dataset.attrs["window_xpos"] = window_data["_main_window"]["xpos"]
        dataset.attrs["window_ypos"] = window_data["_main_window"]["ypos"]
        dataset.attrs["window_maximized"] = window_data["_main_window"]["maximized"]
        dataset.attrs["window_frame_height"] = window_data["_main_window"]["frame_height"]
        dataset.attrs["window_frame_width"] = window_data["_main_window"]["frame_width"]
        dataset.attrs['plugin_data'] = repr(plugin_data)
        dataset.attrs['analysis_data'] = repr(window_data["_main_window"]["_analysis"])
        dataset.attrs['queue_data'] = repr(window_data["_main_window"]["_queue"])
        for pane_name,pane_position in window_data.items():
            if pane_name != "_main_window":
                dataset.attrs[pane_name] = pane_position
        
        # Save analysis server settings:
        #dataset = data_group.create_group("analysis_server")
        #dataset.attrs['send_for_analysis'] = self.blacs.analysis_submission.toggle_analysis.get_active()
        #dataset.attrs['server'] = self.blacs.analysis_submission.analysis_host.get_text()
