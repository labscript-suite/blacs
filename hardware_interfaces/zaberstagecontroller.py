import gtk
from output_classes import AO
from tab_base_classes import Tab, Worker, define_state
import time
class zaberstagecontroller(Tab):


    
    base_units = 'steps'
    base_min = 0
    base_step = 100
    
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,ZaberWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.device = self.settings['connection_table'].find_by_name(self.device_name)
        self.num_stages = len(self.device.child_list)
        
        self.static_mode = True
        self.destroy_complete = False
        
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/zaberstagecontroller.glade')
        self.builder.connect_signals(self)
        self.zaber_notebook = self.builder.get_object('zaber_notebook')
        self.toplevel = self.builder.get_object('toplevel')
        self.title = self.builder.get_object('title')
        self.title.set_text(self.device_name)
        
        
        self.analog_outs = []
        #print self.device.child_list
        self.childwidgets={}
        self.ports = {}
        self.stages={}
        self.types = {}
        self.ao_objects = {}
        self.home_buttons = {}
        self.save_labels = {}
        self.save_set = {}
        self.save_recall = {}
        for child in self.device.child_list:
            
            self.ports[child] = [int(s) for s in self.device.child_list[child].parent_port.split() if s.isdigit()][0]
            self.stages[self.ports[child]] = child
            self.types[child] = self.device.child_list[child].device_class
            if self.types[child] == "ZaberStageTLSR150D":
                self.base_max = 76346
            elif self.types[child] == "ZaberStageTLSR300D":
                self.base_max = 151937
            else:
                self.base_max = 282879
            childbuilder = gtk.Builder()
            childbuilder.add_from_file('hardware_interfaces/zaberstage.glade')
            childtoplevel = childbuilder.get_object('toplevel')
            childbuilder.connect_signals(self)
            position = childbuilder.get_object('position')
            posunits = childbuilder.get_object('units')
            position_adjustment = childbuilder.get_object('position_adjustment')
            position_adjustment.set_upper(self.base_max)
            childbuilder.get_object('stagelabel').set_text(self.types[child])
            self.home_buttons[childbuilder.get_object('home')] = self.ports[child]
            self.save_labels[child] = [childbuilder.get_object('save_%s'%i) for i in range(16)]
            for i in range(16):
                self.save_set[childbuilder.get_object('set_%s'%i)] = [self.ports[child],i]
                self.save_recall[childbuilder.get_object('recall_%s'%i)] = [self.ports[child],i]
                
            
            
            self.childwidgets[child]=[position_adjustment,posunits]
            
            self.zaber_notebook.append_page(childtoplevel, gtk.Label(child))
            
            
            #conn_table_entry = self.settings['connection_table'].find_child(self.settings['device_name'],'stage %d'%i)
            
            #name =  conn_table_entry.name if conn_table_entry else '-'
            
            #self.builder.get_object('stage_%d_label'%i).set_text(channel + '-' + name)
            
            calib = None
            calib_params = {}
            #if conn_table_entry:
            #    calib = chnl_entry.calibration_class
            #    calib_params = eval(chnl_entry.calibration_parameters)
            #spinbutton = self.builder.get_object('position_%d'%i)
            #unit_selection = self.builder.get_object('unit_%d'%i)
            self.ao_objects[child]=AO(self.device_name,child,position,posunits,calib,calib_params,self.base_units,self.program_static,self.base_min,self.base_max,self.base_step)
            #ao_objects.update(settings)
        
        self.viewport.add(self.toplevel)
        self.initialise_zaber()
        self.program_static()
    
    
    @define_state
    def initialise_zaber(self):
        print "*******transition to initialise zaber*******"
        self.queue_work('initialise_zaber_worker',self.ports,self.types, self.settings["COM"])
        
    def get_front_panel_position_state(self):
        returndict = {}
        for stage in self.stages.values():
            returndict[self.ports[stage]] = self.ao_objects[stage].value
        return returndict
    
    @define_state
    def program_static(self,widget=None):
        # Skip if in buffered mode:
        if self.static_mode:
            self.queue_work('program_static',self.get_front_panel_position_state())
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.queue_work('program_buffered',self.device_name,h5file)
        self.do_after('leave_trans_buff',notify_queue)
    def leave_trans_buff(self,notify_queue,_results):
        notify_queue.put(self.device_name)
        
    @define_state
    def transition_to_static(self,notify_queue):
        notify_queue.put(self.device_name)
        
    @define_state
    def abort_buffered(self):
        pass
    
    @define_state
    def destroy(self):
        self.queue_work('shutdown')
        self.do_after('leave_destroy')
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
        
    @define_state
    def home_stage(self,widget):
        print "**************HOME**************"
        self.queue_work('home_stage',self.home_buttons[widget])
        self.do_after('set_zero',self.home_buttons[widget])
    def set_zero(self,port,_results):
        self.ao_objects[self.stages[port]].set_value(0)
        
        
    @define_state
    def save_position(self,widget):
        print "**saving pos"
        self.queue_work('save_position',self.save_set[widget])
        
    @define_state
    def recall_position(self,widget):
        self.queue_work('recall_position',self.save_recall[widget])
        self.do_after('set_gui',self.save_recall[widget][0])
    def set_gui(self,port,_results):
        self.ao_objects[port].set_value(_results)
    
class ZaberWorker(Worker):
    def init(self):
        global serial; import serial
        global h5py; import h5_lock, h5py
        global zaberapi; import zaberapi
        
    def initialise_zaber_worker(self,ports,types,COM):
        self.ports = ports
        self.connection = serial.Serial(port = COM, timeout = 0.1)
        response = True
        while response is not None:
            response = zaberapi.read(self.connection)
        
        #controller.renumber(0)
        
        #self.connections = {}
        #for stage in self.ports:
        #    type = types[stage]
        #    if type == "ZaberStageTLSR150D":
        #        steps_per_rev = 200
        #        mm_per_rev = 25.4
        #    elif type == "ZaberStageTLSR300D":
        #        steps_per_rev = 200
        #        mm_per_rev = 25.4
        #    else:
        #        steps_per_rev = 48
        #        mm_per_rev = 0.3048
            
            #print "*************************************************"
        #print "******************INIT STAGES*********************"
        #self.stages = zaber_multidevice(io,self.ports,'stages',verbose = True)
        #print "*************STAGES CONNECTED*******************"
        #    #self.connections[stage] = linear_slide(io,self.ports[stage],stage,steps_per_rev,mm_per_rev,'m')
        #    #self.connections[stage].move_absolute(50000)
        #    
        #    #self.connections[stage].home()
        ##print self.connections
        
    
    def program_static(self,settings):
        print "***************programming static*******************"
        #self.stages.move_absolute(settings)
        for stage in settings:
            zaberapi.move(self.connection,stage,data=settings[stage])
        t0 = time.time()
        ret = []
        while len(ret)<len(settings):
            if time.time()-t0 > 45:
                print "****replace with warning***"
                break
            line = zaberapi.read(self.connection)
            if line is not None:
                ret.append(line)
        print ret
        
        
        
        
    def home_stage(self,stage):
        print "*****HOMING*****"
        zaberapi.command(self.connection,stage,'home',0)
        t0 = time.time()
        ret = []
        while len(ret)<1:
            if time.time()-t0 > 45:
                print "****replace with warning***"
                break
            line = zaberapi.read(self.connection)
            if line is not None:
                ret.append(line)
        print ret
    
    
    
    def program_buffered(self,device_name,h5file):
        with h5py.File(h5file) as hdf5_file:
            group = hdf5_file['/devices/'+device_name]
            if 'static_values' in group:
                data = group['static_values'][0]
                for stage in data.dtype.names:
                    port = [int(s) for s in stage.split() if s.isdigit()][0]
                    zaberapi.move(self.connection,port,data=data[stage])
                t0 = time.time()
                ret = []
                while len(ret) < len(data):
                    if time.time()-t0 > 45:
                        print "****replace with warning***"
                        break
                    line = zaberapi.read(self.connection)
                    if line is not None:
                        ret.append(line)
    def shutdown(self):
        self.connection.close()
    def initialise_zaber(self):
        pass
    
    def save_pos(self,params):
        dev = params[0]
        id = params[1]
        zaberapi.command(self.connection,dev,"store_current_position",id)
        t0 = time.time()
        ret = []
        while len(ret)<1:
            if time.time()-t0 > 45:
                print "****replace with warning***"
                break
            line = zaberapi.read(self.connection)
            if line is not None:
                ret.append(line)
        print ret
    
    
    def recall_pos(self,params):
        dev = params[0]
        id = params[1]
        zaberapi.move(self.connection,dev,"stored_position",id)
        t0 = time.time()
        ret = []
        while len(ret)<1:
            if time.time()-t0 > 45:
                print "****replace with warning***"
                break
            line = zaberapi.read(self.connection)
            if line is not None:
                ret.append(line)
        print ret
        return ret[2]
