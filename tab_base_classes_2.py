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
        self.worker.start()
        self.state = {'stage': '', 'state':'idle','since': time.time()}
        self.not_responding_for = 0
        self.timeout = gobject.timeout_add(200,self.check_time)
        self.mainloop_thread = threading.Thread(target = self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        self._work = None
        self._finalisation = None
    
    def set_state(self,parentstate,workerstate):
        if 
        self.state
                
    def restart(self):
        self.worker.terminate()
        gobject.source_remove(self.timeout)
        self.__init__(self.worker.__class__)
    
    def do_work(self,funcname,*args,**kwargs):
        self._work = (funcname,args,kwargs)
        
    def do_after(self,funcname,*args,**kwargs):
        self._finalisation = (funcname,args,kwargs)   
         
    def check_time(self):
        if self.state['state'] is 'idle':
            self.not_responding_for = 0
        else:
            self.not_responding_for = time.time() - self.state['since']
        print self.not_responding_for #TODO: make this update a label
        return True
        
    def mainloop(self):
        print 'Starting producer mainloop'
        while True:
            # Get the next task from the event queue:
            print 'Producer: Waiting for an event to process'
            funcname,args,kwargs = self.event_queue.get()
            print 'Producer: processing event:', funcname
            # Run the task with the GUI lock, catching any exceptions:
            try:
                func = getattr(self,funcname)
                with gtk.gdk.lock:
                    func(self,*args,**kwargs)
            except:
                raise #TODO error handling here
            # Do any work that was queued up:
            results = None
            if self._work is not None:
                print 'Producer: Instructing worker to do some work for', funcname 
                self.to_worker.put(self._work)
                self._work = None
                # Confirm that the worker got the message:
                print 'Producer: Waiting for worker to acknowledge job request'
                success, message = self.from_worker.get()
                if not success:
                    print 'Producer: Worker reported failure to start job'
                    pass #TODO handle this
                # Wait for and get the results of the work:
                print 'Producer: Worker reported job started, waiting for completion'
                success,message,results = self.from_worker.get()
                if not success:
                    print 'Producer: Worker reported exception during job'
                    pass #TODO handle this too
            # Do any finalisation that was queued up, with the GUI lock,
            # catching any exceptions:
            if self._finalisation is not None:
                funcname, args, kwargs = self._finalisation
                try:
                    func = getattr(self,funcname)
                    with gtk.gdk.lock:
                        kwargs['results'] = results
                        func(*args,**kwargs)
                except:
                    raise #TODO error handling here
                self._finalisation = None
                
class Worker(Process):
    def init(self):
        # To be overridden by subclasses
        pass
    
    def run(self):
        self.from_parent, self.to_parent = self._args
        self.init()
        self.mainloop()
        
    def mainloop(self):
        while True:
            # Get the next task to be done:
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
 
 
               
class MyTab(Tab):
    @event
    def foo(self):
        print 'MyTab: entered foo'
        self.do_work('foo', 5,6,7,x='x')
        self.do_after('leave_foo', 1,2,3,bar='baz')
        
    def leave_foo(self,*args,**kwargs):
        print 'Mytab: leaving foo', args, kwargs
        
class MyWorker(Worker):
    def init(self):
        global serial; import serial
        
    def foo(self,*args,**kwargs):
        print 'working on foo!', args, kwargs
        return 'results!!!'
        
tab = MyTab(MyWorker)
tab.foo()
