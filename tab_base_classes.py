from multiprocessing import Process, Queue, Lock
import time
import threading
import cPickle
import traceback
import logging
import cgi
import gtk, gobject
import excepthook

class Counter(object):
    """A class with a single method that 
    returns a different integer each time it's called."""
    def __init__(self):
        self.i = 0
    def get(self):
        self.i += 1
        return self.i
        
# Make this function available globally:       
get_unique_id = Counter().get

def define_state(function):
    unescaped_name = function.__name__
    escapedname = '_' + function.__name__
    def f(self,*args,**kwargs):
        function.__name__ = escapedname
        setattr(self,escapedname,function)
        self.event_args.append([args,kwargs])
        self.event_queue.put(escapedname)
    f.__name__ = unescaped_name
    return f
    
        
class Tab(object):
    def __init__(self,WorkerClass,notebook,settings,workerargs={},restart=False):
        self.notebook = notebook
        self.settings = settings
        self.logger = logging.getLogger('BLACS.%s'%settings['device_name'])   
        self.logger.debug('Started')     
        self.event_queue = Queue()
        self.event_args = []
        self.to_worker = Queue()
        self.from_worker = Queue()
        self.worker = WorkerClass(args = [settings['device_name'], self.to_worker, self.from_worker,workerargs])
        self.worker.start()
        self.not_responding_for = 0
        self.hide_not_responding_error_until = 0
        self.timeout = gobject.timeout_add(1000,self.check_time)
        self.mainloop_thread = threading.Thread(target = self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        self._work = None
        self._finalisation = None
        self.timeouts = set()
        self.timeout_ids = {}
        
        builder = gtk.Builder()
        builder.add_from_file('tab_frame.glade')
        self._toplevel = builder.get_object('toplevel')
        self._close = builder.get_object('close')
        self._close.connect('clicked',self.hide_error)
        self.statusbar = builder.get_object('statusbar')
        self.context_id = self.statusbar.get_context_id("State")
        self.notresponding = builder.get_object('not_responding')
        self.errorlabel = builder.get_object('notrespondinglabel')
        self.viewport = builder.get_object('viewport')
        builder.get_object('restart').connect('clicked',self.restart)
        
        tablabelbuilder = gtk.Builder()
        tablabelbuilder.add_from_file('tab_label.glade')
        tablabel = tablabelbuilder.get_object('toplevel')
        self.tab_label_widgets = {"working": tablabelbuilder.get_object('working'),
                                  "ready": tablabelbuilder.get_object('ready'),
                                  "error": tablabelbuilder.get_object('error'),
                                  "buffered": tablabelbuilder.get_object('buffered_mode')}
        tablabelbuilder.get_object('label').set_label(self.settings["device_name"])
        
        self.notebook.append_page(self._toplevel, tablabel)
        self.notebook.set_tab_reorderable(self._toplevel, True)
        self.notebook.set_tab_detachable(self._toplevel, True)
        self._toplevel.show()
        self.error = ''
        self.set_state('idle')

    @define_state
    def gobject_timeout_add(self,*args,**kwargs):
        """A wrapper around gobject_timeout_add so that it can be queued in our state machine"""
        gobject.timeout_add(*args,**kwargs)
        
    def statemachine_timeout_add(self,delay,statefunction,*args,**kwargs):
        # Add the timeout to our set of registered timeouts. Timeouts
        # can thus be removed by the user at ay time by calling
        # self.timeouts.remove(function)
        self.timeouts.add(statefunction)
        # Here's a function which executes the timeout once, then queues
        # itself up again after a delay:
        def execute_timeout():
            # queue up the state function, but only if it hasn't been
            # removed from self.timeouts:
            if statefunction in self.timeouts and self.timeout_ids[statefunction] == unique_id:
                statefunction(*args, **kwargs)
                # queue up another call to this function (execute_timeout)
                # after the delay time:
                self.gobject_timeout_add(delay,execute_timeout)
            # Return false so at to cancel the gobject.timeout so we
            # don't call more than required:
            return False
        # queue the first run:
        self.gobject_timeout_add(delay,execute_timeout)        
        # Store a unique ID for this timeout so that we don't confuse 
        # other timeouts for this one when checking to see that this
        # timeout hasn't been removed:
        unique_id = get_unique_id()
        self.timeout_ids[statefunction] = unique_id
        
    def set_state(self,state):
        ready = self.tab_label_widgets['ready']
        working = self.tab_label_widgets['working']
        error = self.tab_label_widgets['error']
        self.logger.info('State changed to %s'% state)
        self.state = state
        if state == 'idle':
            working.hide()
            if self.error:
                error.show()
            else:
                ready.show()
                error.hide()
        elif state == 'fatal error':
            working.hide()
            error.show()
            ready.hide()
        else:
            ready.hide()
            working.show()
        self.time_of_last_state_change = time.time()
        self.statusbar.push(self.context_id, state)
    
    def close_tab(self,*args):
        self.logger.info('close_tab called')
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
        if self.mainloop_thread.is_alive():
            self.from_worker.put((False,'quit',None))
            self.event_queue.put('_quit')
        self.notebook = self._toplevel.get_parent()
        currentpage = None
        if self.notebook:
            currentpage = self.notebook.get_current_page()
            self.notebook.remove_page(currentpage)       
        return currentpage
        
    def restart(self,*args):
        currentpage = self.close_tab()
        self.logger.info('***RESTART***')
        # Note: the following function call will break if the user hasn't
        # overridden the __init__ function to take these arguments. So
        # make sure you do that!
        self.__init__(self.notebook, self.settings,restart=True)
        self.notebook.reorder_child(self._toplevel,currentpage)
        self.notebook.set_current_page(currentpage)
    
    def queue_work(self,funcname,*args,**kwargs):
        self._work = (funcname,args,kwargs)
        
    def do_after(self,funcname,*args,**kwargs):
        self._finalisation = (funcname,args,kwargs)   
    
    def hide_error(self,button):
        # dont show the error again until the not responding time has doubled:
        self.hide_not_responding_error_until = 2*self.not_responding_for
        self.notresponding.hide()  
        self.error = '' 
        self.tab_label_widgets['error'].hide()
        if self.state == 'idle':
            self.tab_label_widgets['ready'].show()
            
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
            self.errorlabel.set_markup('The hardware process has not responded for %s.\n'%s
                                      + self.error)
        return True
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.mainloop'%self.settings['device_name'])   
        logger.debug('Starting')
        try:
            while True:
                # Get the next task from the event queue:
                logger.debug('Waiting for next event')
                funcname = self.event_queue.get()
                if funcname == '_quit':
                    # The user has requested a restart:
                    logger.debug('Received quit signal')
                    break
                args,kwargs = self.event_args.pop(0)
                if self._work is not None or self._finalisation is not None:
                    message = ('There has been work queued up for the subprocess, '
                               'or a finalisation queued up, even though no initial event'
                               ' has been processed that could have done this! Did someone '
                               'forget to decorate an earlier event callback with @define_state?\n'
                               'Details:\n'
                               'queue_work: ' + str(self._work) + '\n'
                               'do_after: ' + str(self._finalisation))  
                    raise RuntimeError(message)    
                logger.debug('Processing event %s' % funcname)
                # Run the task with the GUI lock, catching any exceptions:
                func = getattr(self,funcname)
                with gtk.gdk.lock:
                    func(self,*args,**kwargs)
                # Do any work that was queued up:
                results = None
                if self._work is not None:
                    logger.debug('Instructing worker to do job %s'%self._work[0] )
                    # This line is to catch if you try to pass unpickleable objects.
                    try:
                        cPickle.dumps(self._work)
                    except:
                        self.error += 'Attempt to pass unserialisable object to child process:'
                        raise
                    self.to_worker.put(self._work)
                    with gtk.gdk.lock:
                        self.set_state(self._work[0])
                    self._work = None
                    # Confirm that the worker got the message:
                    logger.debug('Waiting for worker to acknowledge job request')
                    success, message, results = self.from_worker.get()
                    if not success:
                        if message == 'quit':
                            # The user has requested a restart:
                            logger.debug('Received quit signal')
                            break
                        logger.info('Worker reported failure to start job')
                        raise Exception(message)
                    # Wait for and get the results of the work:
                    logger.debug('Worker reported job started, waiting for completion')
                    success,message,results = self.from_worker.get()
                    if not success and message == 'quit':
                        # The user has requested a restart:
                        logger.debug('Received quit signal')
                        break
                    if not success:
                        logger.info('Worker reported exception during job')
                        now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
                        self.error += ('\nException in worker - %s:\n' % now +
                                       '<span foreground="red" font_family="mono">%s</span>'%cgi.escape(message))
                        while self.error.startswith('\n'):
                            self.error = self.error[1:]
                        with gtk.gdk.lock:
                            self.errorlabel.set_markup(self.error)
                            self.notresponding.show()
                    else:
                        logger.debug('Job completed')
                    with gtk.gdk.lock:
                        self.set_state('idle')
                        if not self.error:
                            self.notresponding.hide()
                            self.hide_not_responding_error_until = 0
                            
                # Do any finalisation that was queued up, with the GUI lock:
                if self._finalisation is not None:
                    logger.debug('doing finalisation function %s' % self._finalisation[0])
                    funcname, args, kwargs = self._finalisation
                    func = getattr(self,funcname)
                    with gtk.gdk.lock:
                        kwargs['_results'] = results
                        func(*args,**kwargs)
                    self._finalisation = None
        except:
            # Some unhandled error happened. Inform the user, and give the option to restart
            message = traceback.format_exc()
            logger.critical('A fatal exception happened:\n %s'%message)
            now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
            self.error += ('\nFatal exception in main process - %s:\n '%now +
                           '<span foreground="red" font_family="mono">%s</span>'%cgi.escape(message))
            while self.error.startswith('\n'):
                self.error = self.error[1:]
            with gtk.gdk.lock:
                self.set_state('fatal error')
                self.errorlabel.set_markup(self.error)
                self._close.set_sensitive(False)
                self.notresponding.show()
        logger.info('Exiting')
        
        
class Worker(Process):
    def init(self):
        # To be overridden by subclasses
        pass
    
    def run(self):
        self.name, self.from_parent, self.to_parent, extraargs = self._args
        for argname in extraargs:
            setattr(self,argname,extraargs[argname])
        self.logger = logging.getLogger('BLACS.%s.worker'%self.name)
        self.logger.debug('Starting')
        self.init()
        self.mainloop()
        
    def mainloop(self):
        while True:
            # Get the next task to be done:
            self.logger.debug('Waiting for next job request')
            funcname, args, kwargs = self.from_parent.get()
            self.logger.debug('Got job request %s' % funcname)
            try:
                # See if we have a method with that name:
                func = getattr(self,funcname)
                success = True
                message = ''
            except AttributeError:
                success = False
                message = traceback.format_exc()
                self.logger.error('Couldn\'t start job:\n %s'%message)
            # Report to the parent whether method lookup was successful or not:
            self.to_parent.put((success,message,None))
            if success:
                # Try to do the requested work:
                self.logger.debug('Starting job %s'%funcname)
                try:
                    results = func(*args,**kwargs)
                    success = True
                    message = ''
                    self.logger.debug('Job complete')
                except:
                    results = None
                    success = False
                    traceback_lines = traceback.format_exception(sys.exc_type, sys.exc_value, sys.exc_traceback)
                    del traceback_lines[1]
                    message = ''.join(traceback_lines)
                    self.logger.error('Exception in job:\n%s'%message)
                # Check if results object is serialisable:
                try:
                    cPickle.dumps(results)
                except:
                    message = traceback.format_exc()
                    self.logger.error('Job returned unserialisable datatypes, cannot pass them back to parent.\n' + message)
                    message = 'Attempt to pass unserialisable object %s to parent process:\n' % str(results) + message
                    success = False
                    results = None
                # Report to the parent whether work was successful or not,
                # and what the results were:
                self.to_parent.put((success,message,results))
 
 
 
     
# Example code! Two classes are defined below, which are subclasses
# of the ones defined above.  They show how to make a Tab class,
# and a Worker class, and get the Tab to request work to be done by
# the worker in response to GUI events.
class MyTab(Tab):
    def __init__(self,notebook,settings,restart=False): # restart will be true if __init__ was called due to a restart
        Tab.__init__(self,MyWorker,notebook,settings,{'x':7}) # Make sure to call this first in your __init__!
        foobutton = gtk.Button('foo, 10 seconds!')
        barbutton = gtk.Button('bar, 10 seconds, then error!')
        bazbutton = gtk.Button('baz, 0.5 seconds!')
        addbazbutton = gtk.Button('add 2 second timeout to baz')
        removebazbutton = gtk.Button('remove baz timeout')
        bazunpickleable= gtk.Button('try to pass baz a multiprocessing.Lock()')
        fatalbutton = gtk.Button('fatal error, forgot to add @define_state to callback!')
        self.checkbutton=gtk.CheckButton('have baz\nreturn a Queue')
        self.toplevel = gtk.VBox()
        self.toplevel.pack_start(foobutton)
        self.toplevel.pack_start(barbutton)
        hbox = gtk.HBox()
        self.toplevel.pack_start(hbox)
        hbox.pack_start(bazbutton)
        hbox.pack_start(addbazbutton)
        hbox.pack_start(removebazbutton)
        hbox.pack_start(bazunpickleable)
        hbox.pack_start(self.checkbutton)
        
        self.toplevel.pack_start(fatalbutton)
        
        foobutton.connect('clicked', self.foo)
        barbutton.connect('clicked', self.bar)
        bazbutton.connect('clicked', self.baz)
        fatalbutton.connect('clicked',self.fatal )
        addbazbutton.connect('clicked',self.add_baz_timeout)
        removebazbutton.connect('clicked',self.remove_baz_timeout)
        bazunpickleable.connect('clicked', self.baz_unpickleable)
        # These two lines are required to top level widget (buttonbox
        # in this case) to the existing GUI:
        self.viewport.add(self.toplevel) 
        self.toplevel.show_all()        

    # It is critical that you decorate your callbacks with @define_state
    # as below. This makes the function get queued up and executed
    # in turn by our state machine instead of immediately by theargs,kwargs = self.event_args.pop(0)
    # GTK mainloop. Only don't decorate if you're certain that your
    # callback can safely happen no matter what state the system is
    # in (for example, adjusting the axis range of a plot, or other
    # appearance settings). You should never be calling queue_work
    # or do_after from un undecorated callback.
    @define_state
    def foo(self, button):
        self.logger.debug('entered foo')
        self.toplevel.set_sensitive(False)
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
        self.toplevel.set_sensitive(True)
        self.logger.debug('leaving foo')
    
    # Here's what's NOT to do: forgetting to decorate a callback with @define_state
    # when it's not something that can safely be done asynchronously
    # to the state machine:
    def fatal(self,button):
        # This bug could be hard to track because nothing will happen
        # when you click the button -- only once you do some other,
        # correcly decorated callback will it become apparant that
        # something is wrong. So don't make this mistake!
        self.queue_work('foo', 5,6,7,x='x')
        
    @define_state
    def bar(self, button):
        self.logger.debug('entered bar')
        self.queue_work('bar', 5,6,7,x=5)
        self.do_after('leave_bar', 1,2,3,bar='baz')
        
    def leave_bar(self,*args,**kwargs):
        self.logger.debug('leaving bar')
        
    @define_state
    def baz(self, button=None):
        self.logger.debug('entered baz')
        self.queue_work('baz', 5,6,7,x='x',return_queue=self.checkbutton.get_active())
        self.do_after('leave_baz', 1,2,3,bar='baz')
    
    # This event shows what happens if you try to send a unpickleable
    # event through a queue to the subprocess:
    @define_state    
    def baz_unpickleable(self, button):
        self.logger.debug('entered bar')
        self.queue_work('baz', 5,6,7,x=Lock())
        self.do_after('leave_bar', 1,2,3,bar='baz')
        
    def leave_baz(self,*args,**kwargs):
        self.logger.debug('leaving baz')
    
    # You don't need to decorate with @define_state if all you're
    # doing is adding a timeout -- adding a timeout can safely be done
    # asynchronously. But you can still decorate if you want, and you
    # should if you're doing other work in the same function call which
    # can't be done asynchronously.
    def add_baz_timeout(self,button):
        self.statemachine_timeout_add(2000,self.baz)
    
    # Similarly, no @define_state is required here -- same applies as above.    
    def remove_baz_timeout(self,button):
        self.timeouts.remove(self.baz)
    
        
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
        self.logger.info('got x! %d' % self.x)
    
    # Here's a function that will be called when requested by the parent
    # process. There's nothing special about it really. Its return
    # value will be passed as a keyword argument _results to the
    # function which was queued with do_after, if there was one.
    def foo(self,*args,**kwargs):
        self.logger.debug('working on foo!')
        time.sleep(10)
        return 'results!!!'
        
    def bar(self,*args,**kwargs):
        self.logger.debug('working on bar!')
        time.sleep(10)
        raise Exception('error!')
        return 'results!!!'
        
    def baz(self,*args,**kwargs):
        self.logger.debug('working on baz: time is %s'%repr(time.time()))
        time.sleep(0.5)
        if kwargs['return_queue']:
            return Queue()
        return 'results!!!'

if __name__ == '__main__':
    import sys
    import logging.handlers
    # Setup logging:
    logger = logging.getLogger('BLACS')
    handler = logging.handlers.RotatingFileHandler('BLACS.log', maxBytes=1024**2, backupCount=0)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if sys.stdout.isatty():
        terminalhandler = logging.StreamHandler(sys.stdout)
        terminalhandler.setFormatter(formatter)
        terminalhandler.setLevel(logging.INFO)
        logger.addHandler(terminalhandler)
    else:
        sys.stdout = sys.stderr = open(os.devnull)
    logger.setLevel(logging.DEBUG)
    excepthook.set_logger(logger)
    logger.info('\n\n===============starting===============\n')

if __name__ == '__main__':
    # Run the demo!:
    gtk.gdk.threads_init() 
    window = gtk.Window() 
    notebook = gtk.Notebook()
    window.connect('destroy',lambda widget: gtk.main_quit())  
    window.add(notebook)
    notebook.show()
    window.show()  
    window.resize(800,600)
    tab1 = MyTab(notebook,settings = {'device_name': 'Example'})
    tab2 = MyTab(notebook,settings = {'device_name': 'Example2'})
    with gtk.gdk.lock:
        gtk.main()
