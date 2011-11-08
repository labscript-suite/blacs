from multiprocessing import Process, Queue
import gtk, gobject
import time
import traceback
import threading

def event(function):
    def f(self,*args,**kwargs):
        setattr(self,'_' + function.__name__,function)
        self.event_queue.put(('_' + function.__name__,args,kwargs))
    return f
        
class Tab(object):
    def __init__(self,WorkerClass):
        self.event_queue = Queue()
        self.to_worker = Queue()
        self.from_worker = Queue()
        self.worker = WorkerClass(args = [self.to_worker, self.from_worker])
        self.worker.daemon = True
        self.worker.start()
        self.not_responding_for = 0
        self.hide_not_responding_error_until = 0
        self.timeout = gobject.timeout_add(1000,self.check_time)
        self.mainloop_thread = threading.Thread(target = self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        self._work = None
        self._finalisation = None
        
        builder = gtk.Builder()
        builder.add_from_file('tab_frame.glade')
        toplevel = builder.get_object('toplevel')
        self._close = builder.get_object('close')
        self._close.connect('clicked',self.hide_error)
        self.statusbar = builder.get_object('statusbar')
        self.context_id = self.statusbar.get_context_id("State")
        self.notresponding = builder.get_object('not_responding')
        self.errorlabel = builder.get_object('notrespondinglabel')
        self.viewport = builder.get_object('viewport')
        builder.get_object('restart').connect('clicked',self.restart)
        w.add(toplevel)
        toplevel.show()
        w.resize(800,600)
        self.set_state('idle')
    
    def set_state(self,state):
        print 'Producer: state changed to', state
        self.state = state
        self.time_of_last_state_change = time.time()
        self.statusbar.push(self.context_id, state)
                
    def restart(self,*args):
        self.worker.terminate()
        gobject.source_remove(self.timeout)
        # The mainloop is blocking waiting for something out of the
        # from_worker queue or the event_queue. Closing the queues doesn't
        # seem to raise an EOF for them, likely because it only closes
        # them from our end, and an EOFError would only be raised if it
        # was closed from the other end, which we can't make happen. But
        # we can instruct it to quit by telling it to do so through the
        # queue itself. That way we don't leave extra threads running
        # (albeit doing nothing) that we don't need:
        print self.mainloop_thread.is_alive()
        if self.mainloop_thread.is_alive():
            self.from_worker.put((False,'quit',None))
            self.event_queue.put(('_quit',None,None))
            print 'joining'
            self.mainloop_thread.join()
        w.remove(w.get_child())
        print '***RESTART***'
        self.__init__(self.worker.__class__)
    
    def queue_work(self,funcname,*args,**kwargs):
        self._work = (funcname,args,kwargs)
        
    def do_after(self,funcname,*args,**kwargs):
        self._finalisation = (funcname,args,kwargs)   
    
    def hide_error(self,button):
        # dont show the error again until the not responding time has doubled:
        self.hide_not_responding_error_until = 2*self.not_responding_for
        self.notresponding.hide()     
            
    def check_time(self):
        if self.state in ['idle','fatal error']:
            self.not_responding_for = 0
        else:
            self.not_responding_for = time.time() - self.time_of_last_state_change
        if self.not_responding_for > 5 + self.hide_not_responding_error_until:
            self.hide_not_responding_error_for = 0
            self.notresponding.show()
            hours, remainder = divmod(int(self.not_responding_for), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                s = '%s hours'%hours
            elif minutes:
                s = '%s minutes'%minutes
            else:
                s = '%s seconds'%seconds
            self.errorlabel.set_text('The hardware process has not responded for %s.'%s)
        return True
        
    def mainloop(self):
        print 'Starting producer mainloop'
        try:
            while True:
                # Get the next task from the event queue:
                print 'Producer: Waiting for an event to process'
                funcname,args,kwargs = self.event_queue.get()
                if funcname == '_quit':
                    # The user has requested a restart:
                    print 'Producer: Recieved quit signal'
                    break
                if self._work is not None or self._finalisation is not None:
                    message = ('There has been work queued up for the subprocess, '
                               'or a finalisation queued up, even though no initial event'
                               ' has been processed that could have done this! Did someone '
                               'forget to decorate an earlier event callback with @event?\n'
                               'Details:\n'
                               'queue_work: ' + str(self._work) + '\n'
                               'do_after: ' + str(self._finalisation))  
                    raise RuntimeError(message)    
                print 'Producer: processing event:', funcname
                # Run the task with the GUI lock, catching any exceptions:
                func = getattr(self,funcname)
                with gtk.gdk.lock:
                    func(self,*args,**kwargs)
                # Do any work that was queued up:
                results = None
                if self._work is not None:
                    print 'Producer: Instructing worker to do some work for', funcname 
                    self.to_worker.put(self._work)
                    with gtk.gdk.lock:
                        self.set_state(self._work[0])
                    self._work = None
                    # Confirm that the worker got the message:
                    print 'Producer: Waiting for worker to acknowledge job request'
                    success, message = self.from_worker.get()
                    if not success:
                        if message == 'quit':
                            # The user has requested a restart:
                            print 'Producer: Recieved quit signal'
                            break
                        print 'Producer: Worker reported failure to start job.'
                        print message
                    # Wait for and get the results of the work:
                    print 'Producer: Worker reported job started, waiting for completion'
                    success,message,results = self.from_worker.get()
                    if not success and message == 'quit':
                        # The user has requested a restart:
                        print 'Producer: Recieved quit signal'
                        break
                    with gtk.gdk.lock:
                        self.set_state('idle')
                        self.notresponding.hide()
                        self.hide_not_responding_error_until = 0
                    if not success:
                        print 'Producer: Worker reported exception during job'
                        with gtk.gdk.lock:
                            self.errorlabel.set_markup('Exception in worker:\n' + 
                                                     '<span foreground="red">%s</span>'%message)
                            self.notresponding.show()
                # Do any finalisation that was queued up, with the GUI lock:
                if self._finalisation is not None:
                    funcname, args, kwargs = self._finalisation
                    func = getattr(self,funcname)
                    try:
                        with gtk.gdk.lock:
                            kwargs['_results'] = results
                            func(*args,**kwargs)
                    except:
                        # If the subprocess had an exception, then it
                        # is likely finalisation will fail, since the
                        # user probably can't handle the 'results' object
                        # being None for their finalisation function. We
                        # don't want the resulting exception popping
                        # up and hiding the one that happened in the
                        # subprocess, since that's where the real error
                        # lies. So don't raise in that case.
                        if success:
                            raise
                    self._finalisation = None
        except:
            # Some unhandled error happened. Inform the user, and give the option to restart
            message = traceback.format_exc()
            with gtk.gdk.lock:
                self.set_state('fatal error')
                self.errorlabel.set_markup('Unhandled exception in main process:\n ' + 
                                         '<span foreground="red">%s</span>'%message)
                self._close.hide()
                self.notresponding.show()
        print 'Producer: Main loop quit'
        
        
        
class Worker(Process):
    def init(self):
        # To be overridden by subclasses
        pass
    
    def run(self):
        self.from_parent, self.to_parent = self._args
        self.init()
        self.mainloop()
        
    def mainloop(self):
        print 'Starting consumer mainloop'
        while True:
            # Get the next task to be done:
            print 'Consumer: Waiting for a job to process'
            funcname, args, kwargs = self.from_parent.get()
            try:
                # See if we have a method with that name:
                func = getattr(self,funcname)
                success = True
                message = ''
            except AttributeError:
                success = False
                message = traceback.format_exc()
            # Report to the parent whether method lookup was successful or not:
            self.to_parent.put((success,message))
            if success:
                # Try to do the requested work:
                try:
                    results = func(*args,**kwargs)
                    success = True
                    message = ''
                except:
                    results = None
                    success = False
                    message = traceback.format_exc()
                # Report to the parent whether work was successful or not,
                # and what the results were:
                self.to_parent.put((success,message,results))
 
 
if __name__ == '__main__':  
    # Example code! Two classes are defined below, which are subclasses
    # of the ones defined above.  They show how to make a Tab class,
    # and a Worker class, and get the Tab to request work to be done by
    # the worker in response to GUI events.
    class MyTab(Tab):
        def __init__(self,workerclass):
            Tab.__init__(self,workerclass) # Make sure to call this first in your __init__!
            foobutton = gtk.Button('foo, 10 seconds!')
            barbutton = gtk.Button('bar, 10 seconds, then error!')
            bazbutton = gtk.Button('baz, 0.5 seconds!')
            fatalbutton = gtk.Button('fatal error, forgot to add @event to callback!')
            buttonbox = gtk.VBox()
            buttonbox.pack_start(foobutton)
            buttonbox.pack_start(barbutton)
            buttonbox.pack_start(bazbutton)
            buttonbox.pack_start(fatalbutton)
            
            foobutton.connect('clicked', self.foo)
            barbutton.connect('clicked', self.bar)
            bazbutton.connect('clicked', self.baz)
            fatalbutton.connect('clicked',self.fatal )
            # These two lines are required to top level widget (buttonbox
            # in this case) to the existing GUI:
            self.viewport.add(buttonbox) 
            buttonbox.show_all()        

        # It is critical that you decorate your callbacks with @event
        # as below. This makes the function get queued up and executed
        # in turn by our state machine instead of immediately by the
        # GTK mainloop. Only don't decorate if you're certain that your
        # callback can safely happen no matter what state the system is
        # in (for example, adjusting the axis range of a plot, or other
        # appearance settings). You should never be calling queue_work
        # or do_after from un undecorated callback.
        @event
        def foo(self, button):
            print 'MyTab: entered foo'
            # Here's how you instruct the worker process to do
            # something. When this callback returns, the worker will be
            # requested to do whatever you ask in queue_work (in this
            # case, MyWorker.foo(5,6,7,x='x') ). Then, no events will
            # be processed until that work is done. Once the work is
            # done, whatever has been set with do_after will be executed
            # (in this case self.leave_foo(1,2,3,bar=baz) ).
            self.queue_work('foo', 5,6,7,x='x')
            self.do_after('leave_foo', 1,2,3,bar='baz')
        
        # So this function will get executed when the worker process is
        # finished with foo():
        def leave_foo(self,*args,**kwargs):
            print 'Mytab: leaving foo', args, kwargs
        
        # Here's what's NOT to do: forgetting to decorate a callback with @event
        # when it's not something that can safely be done asynchronously
        # to the state machine:
        def fatal(self,button):
            # This bug could be hard to track because nothing will happen
            # when you click the button -- only once you do some other,
            # correcly decorated callback will it become apparant that
            # something is wrong. So don't make this mistake!
            self.queue_work('foo', 5,6,7,x='x')
            
        @event
        def bar(self, button):
            print 'MyTab: entered bar'
            self.queue_work('bar', 5,6,7,x='x')
            self.do_after('leave_bar', 1,2,3,bar='baz')
            
        def leave_bar(self,*args,**kwargs):
            print 'Mytab: leaving bar', args, kwargs
            
        @event
        def baz(self, button):
            print 'MyTab: entered baz'
            self.queue_work('baz', 5,6,7,x='x')
            self.do_after('leave_baz', 1,2,3,bar='baz')
            
        def leave_baz(self,*args,**kwargs):
            print 'Mytab: leaving baz', args, kwargs
            
    class MyWorker(Worker):
        def init(self):
            # You read correctly, this isn't __init__, it's init. It's the
            # first thing that will be called in the new process. You should
            # do imports here, define instance variables, that sort of thing. You
            # shouldn't import the hardware modules at the top of your file,
            # because then they will be imported in both the parent and
            # the child processes and wont be cleanly restarted when the subprocess
            # is restarted. Since we're inside a method call though, you'll
            # have to use global statements for the module imports, as shown
            # below. Either that or you can make them instance variables, ie:
            # import module; self.module = module. Up to you, I prefer
            # the former.
            global serial; import serial
            self.x = 5
        
        # Here's a function that will be called when requested by the parent
        # process. There's nothing special about it really. Its return
        # value will be passed as a keyword argument _results to the
        # function which was queued with do_after, if there was one.
        def foo(self,*args,**kwargs):
            print 'working on foo!', args, kwargs
            time.sleep(10)
            return 'results!!!'
            
        def bar(self,*args,**kwargs):
            print 'working on foo!', args, kwargs
            time.sleep(10)
            raise Exception('error!')
            return 'results!!!'
            
        def baz(self,*args,**kwargs):
            print 'working on foo!', args, kwargs
            time.sleep(0.5)
            return 'results!!!'


    # Run the demo!:
    gtk.gdk.threads_init() 
    w = gtk.Window()   
    w.connect('destroy',lambda widget: gtk.main_quit())  
    w.show()  
    tab = MyTab(MyWorker)
    with gtk.gdk.lock:
        gtk.main()
