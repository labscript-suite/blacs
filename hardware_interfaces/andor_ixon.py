import gobject
import pygtk
import gtk
import time
import pyandor
import h5py
import numpy

class andor_ixon(object):

    # settings should contain a dictionary of information from the connection table, relevant to this device.
    # aka, it could be parent: pb_0/flag_0 (pseudoclock)
    #                  device_name: ni_pcie_6363_0
    #
    # or for a more complex device,
    #   parent:
    #   name:
    #   com_port:
    #
    #
    def __init__(self,notebook,settings):
        
        # is the init method finished...no!
        self.init_done = False
        self.static_mode = False
        pyandor.lock.acquire()
        self.cam = pyandor.Andor()
        self.cam.Initialize()
        self.cam.SetCoolerMode(1)
        
        pyandor.lock.release()
        ###############
        # PyGTK stuff #
        ###############
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/andor_ixon.glade')
        self.tab = self.builder.get_object('toplevel')
   
        
        
        # Need to connect signals!
        self.builder.connect_signals(self)
        self.shutter=[self.builder.get_object('shutteropen'),self.builder.get_object('shutterclosed'),self.builder.get_object('shutterauto')]
        self.pregain=self.builder.get_object('pregain')
        self.horizontal=self.builder.get_object('horizontal')
        self.vertical=self.builder.get_object('vertical')
        self.exposure=self.builder.get_object('exposure')
        self.emccd=self.builder.get_object('emccd')
        self.emon=self.builder.get_object('emon')
        self.preview = self.builder.get_object('image')
        self.tempbar = self.builder.get_object('tempbar')
        self.tempon = self.builder.get_object('tempon')
        self.tempworking = self.builder.get_object('tempworking')
        self.tempoff = self.builder.get_object('tempoff')
        self.tempstable = self.builder.get_object('tempstable')
        self.enabletemp=self.builder.get_object('enabletemp')
        self.templabel=self.builder.get_object('templabel')
        self.settemp=self.builder.get_object('settemp')
        self.save0=self.builder.get_object('save0')
        self.save1=self.builder.get_object('save1')
        self.save2=self.builder.get_object('save2')
        #set some default values
        self.emon.set_active(False)
        self.emccd_enable(self.emon)
        self.tempworking.start()
        self.tempworking.show()
        self.tempon.hide()
        self.tempoff.hide()
        self.shutter[2].set_active(True)
        self.pregain.set_active(0)
        self.horizontal.set_active(2)
        self.vertical.set_active(1)
        self.exposure.set_value(20.00)
        

        if self.cam.IsCoolerOn():
            
            self.enabletemp.set_active(True)
            pyandor.lock.acquire()
            self.cam.GetTemperature()
            pyandor.lock.release()
            if self.cam.temperature < 20:
                self.settemp.set_value(self.cam.temperature)
            
        else:
            
            self.enabletemp.set_active(False)
            
        
        #self.previewimage = gtk.gdk.Pixmap(None,512,512,24)
        
        self.timeout = gtk.timeout_add(50,self.temperature_monitor)
        
        # We are done with the init!
        self.init_done = True 
        self.static_mode = True
        self.test = 0
        
        notebook.append_page(self.tab,gtk.Label("Andor iXon"))
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method cleans up the class before the program exits. In this case, we close the worker thread!
    #
    def destroy(self):        
        gtk.timeout_remove(self.timeout)
        pyandor.lock.acquire()
        self.cam.ShutDown()
        pyandor.lock.release()
        
    
    #
    # ** This method should be common to all hardware interfaces **
    #
    # This method sets the values of front panel controls to "defaults"
    #    
    def set_defaults(self):    
        pass
           

    
    # 
    # This function gets the status of the Pulseblaster from the spinapi, and updates the front panel widgets!
    #
    def temperature_monitor(self):
        #if self.pause_status is True:
        #    return True
        
        pyandor.lock.acquire()
        self.tempstatus=self.cam.GetTemperature()
        self.cooler = self.cam.IsCoolerOn()
        self.tempstatus = self.tempstatus[4:]
        self.tempstatus = self.tempstatus.replace('_',' ')
        if self.tempstatus == "NOT INITIALIZED" or self.tempstatus == "ACQUIRING" or self.tempstatus == "ERROR ACK" or self.tempstatus == "TEMP OFF":
            self.tempstable.set_markup('<span foreground="red" size="100">%s</span>'%self.tempstatus)
            self.tempworking.hide()
            self.tempon.hide()
            self.tempoff.show()
        elif self.tempstatus == "TEMP NOT REACHED" or self.tempstatus == "TEMP_DRIFT" or self.tempstatus == "TEMP NOT STABILIZED":
            self.tempstable.set_markup('<span foreground="orange" size="100">%s</span>'%self.tempstatus)
            self.tempworking.show()
            self.tempon.hide()
            self.tempoff.hide()
        elif self.tempstatus == "TEMP STABILIZED":
            self.tempstable.set_markup('<span foreground="green" size="100">%s</span>'%self.tempstatus)
            self.tempworking.hide()
            self.tempon.show()
            self.tempoff.hide()
        else:
            self.tempstable.set_markup('<span foreground="red" size="100">ERROR!</span>')
            self.tempworking.hide()
            self.tempon.hide()
            self.tempoff.show()
        self.templabel.set_text(str(self.cam.temperature))
        pyandor.lock.release()
        
        return True
        
  
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Program experimental sequence
    #
    # Needs to handle seemless transition from static to experiment sequence
    #
    def transition_to_buffered(self,h5file):        
        # disable static update
        self.static_mode = False
        self.shutter.set_sensitive(False)
    
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # return to unbuffered (static) mode
    #
    # Needs to handle seemless transition from experiment sequence to static mode
    #    
    def transition_to_static(self):
        # need to be careful with the order of things here, to make sure outputs don't jump around, in case a virtual device is sending out updates.
                
        #reenable static updates
        self.static_mode = True
        self.shutter.set_active(False)
        self.shutter.set_sensitive(True)
    #
    # ** This method should be common to all hardware interfaces **
    #        
    # Returns the DO/RF/AO/DDS object associated with a given channel.
    # This is called before instantiating virtual devices, so that they can
    # be given a reference to channels they use 
    #     
    def get_child(self,type,channel):
        return None
    
    #########################
    # PyGTK Event functions #
    #########################
    def toggle_shutter(self,widget):
 
        if widget.get_active():
            if widget == self.shutter[0]:
                print 'shutter open'
                pyandor.lock.acquire()
                self.cam.SetShutter(1,1,10,10)
                pyandor.lock.release()
            elif widget == self.shutter[1]:
                print 'shutter closed'
                pyandor.lock.acquire()
                self.cam.SetShutter(1,2,10,10)
                pyandor.lock.release()
            else:
                print 'auto shutter'
                pyandor.lock.acquire()
                self.cam.SetShutter(1,0,10,10)
                pyandor.lock.release()
    def take_picture(self,widget):
        pyandor.lock.acquire()
        self.cam.SetSingleScan()
        self.cam.SetTriggerMode(0)
        #self.cam.SetShutter(1,1,0,0)
        self.cam.SetPreAmpGain(1)
        self.cam.SetEMCCDGain(0)
        self.cam.SetExposureTime(0.002)
        self.cam.SetCoolerMode(1)
        self.cam.StartAcquisition()
        data = []
        self.cam.GetAcquiredData(data)
        #maxIntensity = max(data)
        #if maxIntensity > 0:
        #   for i in range(len(data)):
        #       data[i] = int(round(data[i]*255.0/maxIntensity))
        #
        #data=numpy.array([data[i:i+512] for i in range(0, len(data), 512)])
        #pixels=gtk.gdk.pixbuf_new_from_array(data,gtk.gdk.COLORSPACE_RGB,24)
        self.cam.SaveAsBmpNormalised('manual_img.bmp')
        self.preview.set_from_file('manual_img.bmp')
        #self.preview.set_from_pixbuf(pixels)
        pyandor.lock.release()
        self.save0.set_sensitive(True)
        self.save1.set_sensitive(True)
        self.save2.set_sensitive(True)
    def horizontal_speed(self,widget):
        speed = widget.get_active()
        if speed > -1 and speed <4:
            pyandor.lock.acquire()
            self.cam.SetHSSpeed(0,speed)
            pyandor.lock.release()
        
    def vertical_shift(self,widget):
        speed = widget.get_active()
        if speed > -1 and speed < 5:
            pyandor.lock.acquire()
            self.cam.SetVSSpeed(speed)
            pyandor.lock.release()
            
    def preamp_gain(self,widget):
        gain = widget.get_active()
        if gain > -1 and gain < 3:
            pyandor.lock.acquire()
            self.cam.SetPreAmpGain(gain)
            pyandor.lock.release()
            
    def exposure_time(self,widget):
        t = widget.get_value()
        t = t/1e3
        pyandor.lock.acquire()
        self.cam.SetExposureTime(t)
        pyandor.lock.release()
        
    def set_emccd(self,widget):
        if widget.is_sensitive():
            gain = int(widget.get_value())
            if gain < 300:
                pyandor.lock.acquire()
                self.cam.SetEMCCDGain(gain)
                pyandor.lock.release()
            
    def emccd_enable(self,widget):
        if widget.get_active():
            self.emccd.set_sensitive(True)
            gain = int(self.emccd.get_value())
            self.cam.SetEMCCDGain(gain)
        else:
            self.emccd.set_sensitive(False)
            self.cam.SetEMCCDGain(0)
    def set_temp(self,widget):
        if not self.init_done:
            return
        if widget.is_sensitive():
            temp = int(widget.get_value())
            pyandor.lock.acquire()
            self.cam.SetTemperature(temp)
            pyandor.lock.release()
    def enable_temp(self,widget):
        if not self.init_done:
            return
        if widget.is_sensitive():
            if widget.get_active():
                pyandor.lock.acquire()
                self.cam.CoolerON()
                pyandor.lock.release()
            else:
                pyandor.lock.acquire()
                self.cam.CoolerOFF()
                pyandor.lock.release()
    
    def save_file(self,widget):
        chooser = gtk.FileChooserDialog(title='Save',action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                        buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                                   gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        chooser.set_default_response(gtk.RESPONSE_OK)

        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_folder_uri(r'C:\Users\beclab\Pictures')
        chooser.set_current_name('manual_photo.bmp')
        response = chooser.run()
        if response == gtk.RESPONSE_OK:
            self.current_file = chooser.get_filename()
        else:
            chooser.destroy()
            return 'not saved'
        chooser.destroy()
        with open(self.current_file,'w') as current_file:
            self.cam.SaveAsBmp(current_file)
    def save_norm(self,widget):
        chooser = gtk.FileChooserDialog(title='Save',action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                        buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                                   gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        chooser.set_default_response(gtk.RESPONSE_OK)

        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_folder_uri(r'C:\Users\beclab\Pictures')
        chooser.set_current_name('manual_photo.bmp')
        response = chooser.run()
        if response == gtk.RESPONSE_OK:
            self.current_file = chooser.get_filename()
        else:
            chooser.destroy()
            return 'not saved'
        chooser.destroy()
        with open(self.current_file,'w') as current_file:
            self.cam.SaveAsBmpNormalised(current_file)
            
    def save_text(self,widget):
        chooser = gtk.FileChooserDialog(title='Save',action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                        buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                                   gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        chooser.set_default_response(gtk.RESPONSE_OK)

        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_folder_uri(r'C:\Users\beclab\Pictures')
        chooser.set_current_name('manual_photo.txt')
        response = chooser.run()
        if response == gtk.RESPONSE_OK:
            self.current_file = chooser.get_filename()
        else:
            chooser.destroy()
            return 'not saved'
        chooser.destroy()
        with open(self.current_file,'w') as current_file:
            self.cam.SaveAsTxt(current_file)