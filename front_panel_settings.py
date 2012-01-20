import os
import socket
import logging

import excepthook
import gtk
import numpy
import h5py


# Connection Table Code
from connections import ConnectionTable

logger = logging.getLogger('BLACS.FrontPanelSettings')  

class FrontPanelSettings(object):
    def __init__(self,blacs):
        self.tablist = blacs.tablist
        self.attached_devices = blacs.attached_devices
        self.notebook = blacs.notebook
        self.window = blacs.window
        self.panes = blacs.panes
        self.connection_table = blacs.connection_table
        self.blacs = blacs

    def get_save_data(self):
        states = {}
        tab_positions = {}
        for devicename,tab in self.tablist.items():
            deviceclass_name = self.attached_devices[devicename]
            states[devicename] = self.get_front_panel_state(tab)
        
            # Find the notebook it is in
            current_notebook = tab._toplevel.get_parent()
            # By default we assume it is in notebook1. This way, if a tab gets lost somewhere, and isn't found to be a child of any notebook we know about, 
            # it will revert back to notebook 1 when the file is loaded upon program restart!
            current_notebook_name = "1" 
            
            for notebook_name,notebook in self.notebook.items():
                if notebook == current_notebook:
                    current_notebook_name = notebook_name                       
            
            # find the page it is in
            page = current_notebook.page_num(tab._toplevel)
            visible = True if current_notebook.get_current_page() == page else False
            
            tab_positions[devicename] = {"notebook":current_notebook_name,"page":page, "visible":visible}
         
        # save window data
        window_data = {}
        
        # Size of window
        win_size = self.window.get_size()
        win_pos = self.window.get_position()
        
        window_data["window"] = {"width":win_size[0],"height":win_size[1],"xpos":win_pos[0],"ypos":win_pos[1]}
        # Main Hpane
        for k,v in self.panes.items():
            window_data[k] = v.get_position()
        
        return states,tab_positions,window_data 
    
    def save_conn_table_to_h5_file(self,hdf5_file):
        h5_file = os.path.join("connectiontables", socket.gethostname()+".h5")
        with h5py.File(h5_file,'r') as conn_table:
            conn_data = numpy.array(conn_table['/connection table'][:])
            hdf5_file['/'].create_dataset('connection table',data=conn_data)

    def save_front_panel_to_h5(self,current_file,states,tab_positions,window_data,silent = {}):        
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
            save_conn_table = False
            try:
                new_conn = ConnectionTable(current_file)
            except:
                # no connection table is present, so also save the connection table!
                save_conn_table = True
            
            # if save_conn_table is True, we don't bother checking to see if the connection tables match, because save_conn_table is only true when the connection table doesn't exist in the current file
            # As a result, if save_conn_table is True, we ignore connection table checking, and save the connection table in the h5file.
            if save_conn_table or self.connection_table.compare_to(new_conn):
                with h5py.File(current_file,'r+') as hdf5_file:
                    if hdf5_file['/'].get('front_panel') != None:
                        # Create a dialog to ask whether we can overwrite!
                        overwrite = False
                        if not silent:                                
                            message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_YES_NO, "Do you wish to replace the existing front panel configuration in this file?")                             
                            resp = message.run()
                            
                            if resp == gtk.RESPONSE_YES:
                                overwrite = True                              
                            message.destroy()
                        else:
                            overwrite = silent["overwrite"]
                        
                        if overwrite:
                            # Delete Front panel group, save new front panel
                            del hdf5_file['/front_panel']
                            self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table)
                        else:
                            if not silent:
                                message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_CANCEL, "Front Panel not saved.") 
                                message.run()  
                                message.destroy()
                            else:
                                logger.info("Front Panel not saved as it already existed in the h5 file '"+current_file+"'")
                            return
                    else: 
                        # Save Front Panel in here
                        self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table)
            else:
                # Create Error dialog (invalid connection table)
                if not silent:
                    message = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_CANCEL, "The Front Panel was not saved as the file selected contains a connection table which is not a subset of the current connection table.") 
                    message.run()  
                    message.destroy()   
                else:
                    logger.info("Front Panel not saved as the connection table in the h5 file '"+current_file+"' didn't match the current connection table.")
                return
        else:
            with h5py.File(current_file,'w') as hdf5_file:
                # save connection table, save front panel                    
                self.store_front_panel_in_h5(hdf5_file,states,tab_positions,window_data,save_conn_table=True)
        
    
    def store_front_panel_in_h5(self, hdf5_file,states,tab_positions,window_data,save_conn_table = False):
        if save_conn_table:
            self.save_conn_table_to_h5_file(hdf5_file)
        
        #with h5py.File(current_file,'a') as hdf5_file:
        data_group = hdf5_file['/'].create_group('front_panel')
        
        ao_list = []
        do_list = []
        dds_list = []
        other_data_list = []
       
        ao_dtype = [('name','a256'),('channel','a256'),('value',float),('locked',bool),('step_size',float),('units','a256')]
        do_dtype = [('name','a256'),('channel','a256'),('value',bool),('locked',bool)]
        dds_dtype = ao_dtype
        max_od_length = 2
            
        # Iterate over each device within a class
        for devicename, device_state in states.items():
            logger.debug("saving front panel for device:" + devicename) 
            print device_state
            # Insert AO data into dataset
            for data in device_state["AO"].values():
                if data != {}:
                    ao_list.append((data['name'],data['channel'],data['value'],data['locked'],data['step_size'],data['units']))
                
            # Insert DO data into dataset
            for data in device_state["DO"].values():
                if data != {}:
                    do_list.append((data['name'],data['channel'],data['value'],data['locked']))
            
            # Insert DDS data into dataset
            for data in device_state["DDS"].values():
                # If we have the gate entry, pad it so we can store it in the dds list with teh AO channels
                if data != {}:
                    if 'step_size' not in data:
                        data['value'] = float(data['value']) # Convert to float to match AO value type
                        data['step_size'] = 0
                        data['units'] = ''
                    dds_list.append((data['name'],data['channel'],data['value'],data['locked'],data['step_size'],data['units']))
                
            # Save "other data"
            od = repr(device_state["other_data"])
            other_data_list.append((devicename,od))            
            max_od_length = len(od) if len(od) > max_od_length else max_od_length
            
        
        other_data_dtype = [('device_name','a256'),('data','a'+str(max_od_length))]
        
        
        # Create AO/DO/DDS/other_data datasets
        ao_array = numpy.empty(len(ao_list),dtype=ao_dtype)
        for i, row in enumerate(ao_list):
            ao_array[i] = row
        data_group.create_dataset('AO',data=ao_array)
        
        do_array = numpy.empty(len(do_list),dtype=do_dtype)
        for i, row in enumerate(do_list):
            do_array[i] = row
        data_group.create_dataset('DO',data=do_array)
        
        dds_array = numpy.empty(len(dds_list),dtype=dds_dtype)
        for i, row in enumerate(dds_list):
            dds_array[i] = row
        data_group.create_dataset('DDS',data=dds_array)
        
        od_array = numpy.empty(len(other_data_list),dtype=other_data_dtype)
        for i, row in enumerate(other_data_list):
            od_array[i] = row
        data_group.create_dataset('TAB_DATA',data=od_array)
        
        # Save BLACS Main GUI Info
        # Save tab positions
        i = 0
        tab_data = numpy.empty(len(tab_positions),dtype=[('tab_name','a256'),('notebook','a2'),('page',int),('visible',bool)])
        for k,v in tab_positions.items():
            tab_data[i] = (k,v["notebook"],v["page"],v["visible"])
            i += 1
        dataset = data_group.create_dataset("_notebook_data",data=tab_data)
        dataset.attrs["window_width"] = window_data["window"]["width"]
        dataset.attrs["window_height"] = window_data["window"]["height"]
        dataset.attrs["window_xpos"] = window_data["window"]["xpos"]
        dataset.attrs["window_ypos"] = window_data["window"]["ypos"]
        for k,v in window_data.items():
            if k != "window":
                dataset.attrs[k] = v
        
        # Save analysis server settings:
        dataset = data_group.create_group("analysis_server")
        dataset.attrs['send_for_analysis'] = self.blacs.toggle_analysis.get_active()
        dataset.attrs['server'] = self.blacs.analysis_host.get_text()
        
    
    def get_front_panel_state(self, tab):    
        
        # instatiate AO/DO dict
        ao_dict = {}
        do_dict = {}
        dds_dict = {}
        
        if hasattr(tab,'num_AO') and tab.num_AO > 0:
            for i in range(tab.num_AO):
                ao_chnl = tab.analog_outs[i]
                ao_dict[ao_chnl.channel] = self.get_ao_dict(ao_chnl)
                
        if hasattr(tab,'num_DDS') and tab.num_DDS > 0:            
            for i in range(tab.num_DDS):
                for ao_chnl in [tab.dds_outputs[i].freq,tab.dds_outputs[i].amp,tab.dds_outputs[i].phase]:
                    dds_dict[ao_chnl.channel] = self.get_ao_dict(ao_chnl)
                
                dds_dict[tab.dds_outputs[i].gate.channel] = self.get_do_dict(tab.dds_outputs[i].gate)
        
        if hasattr(tab,'num_DO') and tab.num_DO > 0:
            for i in range(tab.num_DO):
                do_chnl = tab.digital_outs[i]
                do_dict[do_chnl.channel] = self.get_do_dict(do_chnl)
        
        return {'other_data':tab.get_save_data() if hasattr(tab,'get_save_data') else {},
                'AO':ao_dict,
                'DO':do_dict,
                'DDS':dds_dict}
                
    def get_ao_dict(self,ao_chnl):
        if not hasattr(ao_chnl,'name'):
            return {}
        return {'name':ao_chnl.name,
                'channel':ao_chnl.channel,         
                'value':ao_chnl.adjustment.get_value(), 
                'locked':ao_chnl.locked,
                'step_size':ao_chnl.adjustment.get_step_increment(),
                'units':ao_chnl.current_units}
    
    def get_do_dict(self,do_chnl):
        if not hasattr(do_chnl,'name'):
            return {}
        return {'name':do_chnl.name, 
                'channel':do_chnl.channel, 
                'value':bool(do_chnl.action.get_active()),
                'locked':do_chnl.locked}
         