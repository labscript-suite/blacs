from multiprocessing import Process, Queue, Lock
from Queue import Queue as NormalQueue
import time
import sys
import threading
import cPickle
import traceback
import logging
import cgi
from types import GeneratorType

#import excepthook

from PySide.QtCore import *
from PySide.QtGui import *
from PySide.QtUiTools import QUiLoader

from qtutils import *

class Counter(object):
    """A class with a single method that 
    returns a different integer each time it's called."""
    def __init__(self):
        self.i = 0
    def get(self):
        self.i += 1
        return self.i
        
        
STATE_MANUAL = 1
STATE_TRANSITION_TO_BUFFERED = 2
STATE_TRANSITION_TO_MANUAL = 4
STATE_BUFFERED = 8  
      
class StateQueue(object):
    def __init__(self):
        self.list = []
        self.last_requested_state = None
        # A queue that blocks the get(requested_state) method until an entry in the queue has a state that matches the requested_state
        self.get_blocking_queue = NormalQueue()
    
    # this should only happen in the main thread, as my implementation is not thread safe!
    @inmain_decorator(True)   
    def put(self,allowed_states,queue_state_indefinitely,data):
        self.list.append([allowed_states,queue_state_indefinitely,data]) 
        # if this state is one the get command is waiting for, notify it!
        if self.last_requested_state and allowed_states&self.last_requested_state:
            self.get_blocking_queue.put('new item')
    
    # this should only happen in the main thread, as my implementation is not thread safe!
    @inmain_decorator(True)
    def check_for_next_item(self,state):
        # We reset the queue here, as we are about to traverse the tree, which contains any new items that
        # are described in messages in this queue, so let's not keep those messages around anymore.
        # Put another way, we want to block until a new item is added, if we don't find an item in this function
        # So it's best if the queue is empty now!
        self.get_blocking_queue = NormalQueue()
        
        # traverse the list
        delete_index_list = []
        success = False
        for i,item in enumerate(self.list):
            allowed_states,queue_state_indefinitely,data = item
            if allowed_states&state:
                delete_index_list.append(i)
                success = True
                break
            elif not queue_state_indefinitely:
                delete_index_list.append(i)
        
        # do this in reverse order so that the first delete operation doesn't mess up the indices of subsequent ones
        for index in reversed(sorted(delete_index_list)):
            del self.list[index]
            
        if not success:
            data = None
            
        return success,data    
        
    # this method should not be called in the main thread, because it will block until something is found...
    # Please, only have one thread ever accessing this...I have no idea how it will behave if multiple threads are trying to get
    # items from the queue...
    #
    # This method will block until a item found in the queue is found to be allowed during the specified 'state'.
    def get(self,state):
        if self.last_requested_state:
            raise Exception('You have multiple threads trying to get from this queue at the same time. I won\'t allow it!')
    
        self.last_requested_state = state
        while True:
            status,data = self.check_for_next_item(state)
            if not status:
                # we didn't find anything useful, so we'll wait until a useful state is added!
                self.get_blocking_queue.get()
            else:
                self.last_requested_state = None
                return data
                
                    
        
# Make this function available globally:       
get_unique_id = Counter().get


def define_state(allowed_states,queue_state_indefinitely):
    def wrap(function):
        unescaped_name = function.__name__
        escapedname = '_' + function.__name__
        if allowed_states < 1 or allowed_states > 15:
            raise RuntimeError('Function %s has been set to run in unknown states. Please make sure allowed states is one or more of STATE_MANUAL,'%unescaped_name+
            'STATE_TRANSITION_TO_BUFFERED, STATE_TRANSITION_TO_MANUAL and STATE_BUFFERED (or-ed together using the | symbol, eg STATE_MANUAL|STATE_BUFFERED')
        def f(self,*args,**kwargs):
            function.__name__ = escapedname
            setattr(self,escapedname,function)
            self.event_queue.put(allowed_states,queue_state_indefinitely,[escapedname,[args,kwargs]])
        f.__name__ = unescaped_name
        return f        
    return wrap
    
        
class Tab(object):
    def __init__(self,notebook,settings,restart=False):        
        self.notebook = notebook
        self.settings = settings
        self._device_name = self.settings["device_name"]
        
        self._ui = QUiLoader().load('tab_frame.ui')
        self.device_widget = self._ui.device_controls
        self._ui.notresponding.hide()  
        
        self.error = ''
        self._state = ''
        self._time_of_last_state_change = time.time()
        self.not_responding_for = 0
        self.hide_not_responding_error_until = 0
        self.timeouts = set()
        self.timeout_ids = {}
        
        self._work = None
        self._finalisation = None
        
        self.logger = logging.getLogger('BLACS.%s'%self.device_name)   
        self.logger.debug('Started')     
        
        self.event_queue = StateQueue()
        self.workers = {}
        
        #self.timeout = gobject.timeout_add(1000,self.check_time)
        self.timeout = QTimer()
        self.timeout.timeout.connect(self.check_time)
        self.timeout.start(1000)
        
        self.mainloop_thread = threading.Thread(target = self.mainloop)
        self.mainloop_thread.daemon = True
        self.mainloop_thread.start()
        
        self.mode = STATE_MANUAL
        self.state = 'idle'
        
        
        
        
        # connect signals
        self._ui.button_close.clicked.connect(self.hide_error)
        self._ui.button_restart.clicked.connect(self.restart)
        
        # Add the tab to the notebook
        self.notebook.addTab(self._ui,self.device_name)
        self._ui.show()
        

    
    @property
    def device_name(self):
        return self._device_name
    
    # sets the mode, switches between MANUAL, BUFFERED, TRANSITION_TO_BUFFERED and TRANSITION_TO_STATIC
    @property
    def mode(self):
        return self._mode
    
    @mode.setter
    def mode(self,mode):
        self._mode = mode
        self._update_state_label()
        
    @property
    def state(self):
        return self._state
        
    @state.setter
    def state(self,state):
        self._state = state        
        self._time_of_last_state_change = time.time()
        self._update_state_label()
    
    @inmain_decorator(True)
    def _update_state_label(self):
        if self.mode == 1:
            mode = 'Manual'
        elif self.mode == 2:
            mode = 'Transitioning to buffered'
        elif self.mode == 4:
            mode = 'Transitioning to manual'
        elif self.mode == 8:
            mode = 'Buffered'
        else:
            raise RuntimeError('self.mode for device %s is invalid. It must be one of STATE_MANUAL, STATE_TRANSITION_TO_BUFFERED, STATE_TRANSITION_TO_MANUAL or STATE_BUFFERED'%(self.device_name))
    
        self._ui.state_label.setText('<b>%s mode</b> - State: %s'%(mode,self.state))
        
        # Todo: Update icon in tab
    
    def create_worker(self,name,WorkerClass,workerargs={}):
        if name in self.workers:
            raise Exception('There is already a worker process with name: %s'%name) 
        if name == 'GUI':
            raise Exception('You cannot call a worker process "GUI". Why would you want to? Your worker process cannot interact with the BLACS GUI directly, so you are just trying to confuse yourself!')
        to_worker = Queue()
        from_worker = Queue()
        worker = WorkerClass(args = ['%s_%s'%(self.settings['device_name'],name), to_worker, from_worker, workerargs])
        worker.start()
        self.workers[name] = (worker,to_worker,from_worker)
       
    # def btn_release(self,widget,event):
        # if event.button == 3:
            # menu = gtk.Menu()
            # menu_item = gtk.MenuItem("Restart device tab")
            # menu_item.connect("activate",self.restart)
            # menu_item.show()
            # menu.append(menu_item)
            # menu.popup(None,None,None,event.button,event.time)
        
    @define_state(STATE_MANUAL|STATE_BUFFERED|STATE_TRANSITION_TO_BUFFERED|STATE_TRANSITION_TO_MANUAL,True)  
    def _timeout_add(self,delay,execute_timeout):
        QTimer.singleShot(delay,execute_timeout)
    
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
                self._timeout_add(delay,execute_timeout)
            
        # queue the first run:
        self._timeout_add(delay,execute_timeout)        
        # Store a unique ID for this timeout so that we don't confuse 
        # other timeouts for this one when checking to see that this
        # timeout hasn't been removed:
        unique_id = get_unique_id()
        self.timeout_ids[statefunction] = unique_id
        
    # def set_state(self,state):
        # ready = self.tab_label_widgets['ready']
        # working = self.tab_label_widgets['working']
        # error = self.tab_label_widgets['error']
        # self.logger.info('State changed to %s'% state)
        # self.state = state
        # if state == 'idle':
            # working.hide()
            # if self.error:
                # error.show()
            # else:
                # ready.show()
                # error.hide()
        # elif state == 'fatal error':
            # working.hide()
            # error.show()
            # ready.hide()
        # else:
            # ready.hide()
            # working.show()
        # self._time_of_last_state_change = time.time()
        # self.statusbar.push(self.context_id, state)
    
    def close_tab(self,*args):
        self.logger.info('close_tab called')
        self.timeout.stop()
        for name,worker_data in self.workers.items():            
            worker_data[0].terminate()
            # The mainloop is blocking waiting for something out of the
            # from_worker queue or the event_queue. Closing the queues doesn't
            # seem to raise an EOF for them, likely because it only closes
            # them from our end, and an EOFError would only be raised if it
            # was closed from the other end, which we can't make happen. But
            # we can instruct it to quit by telling it to do so through the
            # queue itself. That way we don't leave extra threads running
            # (albeit doing nothing) that we don't need:
            if self.mainloop_thread.is_alive():
                worker_data[2].put((False,'quit',None))
                self.event_queue.put(STATE_MANUAL|STATE_BUFFERED|STATE_TRANSITION_TO_BUFFERED|STATE_TRANSITION_TO_MANUAL,True,['_quit',None])
        self.notebook = self._ui.parentWidget().parentWidget()
        currentpage = None
        if self.notebook:
            #currentpage = self.notebook.get_current_page()
            currentpage = self.notebook.indexOf(self._ui)
            self.notebook.removeTab(currentpage)       
        return currentpage
        
    def restart(self,*args):
        currentpage = self.close_tab()
        self.logger.info('***RESTART***')
        # Note: the following function call will break if the user hasn't
        # overridden the __init__ function to take these arguments. So
        # make sure you do that!
        self.__init__(self.notebook, self.settings,restart=True)
        
        self.notebook = self._ui.parentWidget().parentWidget()
        self.notebook.removeTab(self.notebook.indexOf(self._ui))
        self.notebook.insertTab(currentpage,self._ui,self.device_name)
        self.notebook.setCurrentWidget(self._ui)
            
        # If BLACS is waiting on this tab for something, tell it to abort!
        # self.BLACS.current_queue.put('abort')
    
    def queue_work(self,worker_process,worker_function,*args,**kwargs):
        return worker_process,worker_function,args,kwargs
            
    def hide_error(self):
        # dont show the error again until the not responding time has doubled:
        self.hide_not_responding_error_until = 2*self.not_responding_for
        self._ui.notresponding.hide()  
        self.error = '' 
        #self.tab_label_widgets['error'].hide()
        #if self.state == 'idle':
        #    self.tab_label_widgets['ready'].show()
            
    def check_time(self):
        if self.state in ['idle','fatal error']:
            self.not_responding_for = 0
            self._ui.error_message.setText(self.error)
        else:
            self.not_responding_for = time.time() - self._time_of_last_state_change
        if self.not_responding_for > 5 + self.hide_not_responding_error_until:
            self.hide_not_responding_error_for = 0
            self._ui.notresponding.show()
            hours, remainder = divmod(int(self.not_responding_for), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                s = '%s hours'%hours
            elif minutes:
                s = '%s minutes'%minutes
            else:
                s = '%s seconds'%seconds
            self._ui.error_message.setText('The hardware process has not responded for %s.\n\n'%s
                                      + self.error)
        return True
        
    def mainloop(self):
        logger = logging.getLogger('BLACS.%s.mainloop'%self.settings['device_name'])   
        logger.debug('Starting')
        try:
            while True:
                # Get the next task from the event queue:
                logger.debug('Waiting for next event')
                funcname, data = self.event_queue.get(self.mode)
                if funcname == '_quit':
                    # The user has requested a restart:
                    logger.debug('Received quit signal')
                    break
                args,kwargs = data
                logger.debug('Processing event %s' % funcname)
                self.state = '%s (GUI)'%funcname
                # Run the task with the GUI lock, catching any exceptions:
                func = getattr(self,funcname)
                # run the function in the Qt main thread
                generator = inmain(func,self,*args,**kwargs)
                # Do any work that was queued up:(we only talk to the worker if work has been queued up through the yield command)
                if type(generator) == GeneratorType:
                    # We need to call next recursively, queue up work and send the results back until we get a StopIteration exception
                    generator_running = True
                    break_main_loop = False
                    # get the data from the first yield function
                    worker_process,worker_function,worker_args,worker_kwargs = inmain(generator.next)
                    # Continue until we get a StopIteration exception, or the user requests a restart
                    while generator_running:
                        try:
                            logger.debug('Instructing worker %s to do job %s'%(worker_process,worker_function) )
                            worker_arg_list = (worker_function,worker_args,worker_kwargs)
                            # This line is to catch if you try to pass unpickleable objects.
                            try:
                                cPickle.dumps(worker_arg_list)
                            except:
                                self.error += 'Attempt to pass unserialisable object to child process:'
                                raise
                            # Send the command to the worker
                            to_worker = self.workers[worker_process][1]
                            from_worker = self.workers[worker_process][2]
                            to_worker.put(worker_arg_list)
                            self.state = '%s (%s)'%(worker_function,worker_process)
                            self._work = None
                            # Confirm that the worker got the message:
                            logger.debug('Waiting for worker to acknowledge job request')
                            success, message, results = from_worker.get()
                            if not success:
                                if message == 'quit':
                                    # The user has requested a restart:
                                    logger.debug('Received quit signal')
                                    # This variable is set so we also break out of the toplevel main loop
                                    break_main_loop = True
                                    break
                                logger.info('Worker reported failure to start job')
                                raise Exception(message)
                            # Wait for and get the results of the work:
                            logger.debug('Worker reported job started, waiting for completion')
                            success,message,results = from_worker.get()
                            if not success and message == 'quit':
                                # The user has requested a restart:
                                logger.debug('Received quit signal')
                                # This variable is set so we also break out of the toplevel main loop
                                break_main_loop = True
                                break
                            if not success:
                                logger.info('Worker reported exception during job')
                                now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
                                self.error += ('\nException in worker - %s:\n' % now +
                                               '<FONT COLOR=\'#ff0000\'>%s</FONT>'%cgi.escape(message))
                                while self.error.startswith('\n'):
                                    self.error = self.error[1:]
                                
                                def show_error():
                                    self._ui.error_message.setText(self.error)
                                    self._ui.notresponding.show()
                                # do the contents of the above function in the Qt main thread
                                inmain(show_error)
                            else:
                                logger.debug('Job completed')
                                                    
                            # do the GUI stuff in the Qt main thread
                            if not self.error:
                                inmain(self._ui.notresponding.hide)
                            self.hide_not_responding_error_until = 0
                                
                            # Send the results back to the GUI function
                            logger.debug('returning worker results to function %s' % funcname)
                            self.state = '%s (GUI)'%funcname
                            next_yield = inmain(generator.send,results) 
                            # If there is another yield command, put the data in the required variables for the next loop iteration
                            if next_yield:
                                worker_process,worker_function,worker_args,worker_kwargs = next_yield
                        except StopIteration:
                            # The generator has finished. Ignore the error, but stop the loop
                            logger.debug('Finalising function')
                            generator_running = False
                    # Break out of the main loop if the user requests a restart
                    if break_main_loop:
                        break
                self.state = 'idle'
        except:
            # Some unhandled error happened. Inform the user, and give the option to restart
            message = traceback.format_exc()
            logger.critical('A fatal exception happened:\n %s'%message)
            now = time.strftime('%a %b %d, %H:%M:%S ',time.localtime())
            self.error += ('\nFatal exception in main process - %s:\n '%now +
                           '<FONT COLOR=\'#ff0000\'>%s</FONT>'%cgi.escape(message))
            while self.error.startswith('\n'):
                self.error = self.error[1:]
            
            def show_fatal_error():
                self._ui.error_message.setText(self.error)
                self._ui.button_close.setEnabled(False)
                self._ui.notresponding.show()
                
            self.state = 'fatal error'
            # do the contents of the above function in the Qt main thread
            inmain(show_fatal_error)
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
        Tab.__init__(self,notebook,settings,restart) # Make sure to call this first in your __init__!
        
        self.create_worker('My worker',MyWorker,{'x':7})
        
        # foobutton = gtk.Button('foo, 10 seconds!')
        # barbutton = gtk.Button('bar, 10 seconds, then error!')
        # bazbutton = gtk.Button('baz, 0.5 seconds!')
        # addbazbutton = gtk.Button('add 2 second timeout to baz')
        # removebazbutton = gtk.Button('remove baz timeout')
        # bazunpickleable= gtk.Button('try to pass baz a multiprocessing.Lock()')
        # fatalbutton = gtk.Button('fatal error, forgot to add @define_state to callback!')
        # self.checkbutton=gtk.CheckButton('have baz\nreturn a Queue')
        # self.toplevel = gtk.VBox()
        # self.toplevel.pack_start(foobutton)
        # self.toplevel.pack_start(barbutton)
        # hbox = gtk.HBox()
        # self.toplevel.pack_start(hbox)
        # hbox.pack_start(bazbutton)
        # hbox.pack_start(addbazbutton)
        # hbox.pack_start(removebazbutton)
        # hbox.pack_start(bazunpickleable)
        # hbox.pack_start(self.checkbutton)
        
        # self.toplevel.pack_start(fatalbutton)
        
        # foobutton.connect('clicked', self.foo)
        # barbutton.connect('clicked', self.bar)
        # bazbutton.connect('clicked', self.baz)
        # fatalbutton.connect('clicked',self.fatal )
        # addbazbutton.connect('clicked',self.add_baz_timeout)
        # removebazbutton.connect('clicked',self.remove_baz_timeout)
        # bazunpickleable.connect('clicked', self.baz_unpickleable)
        # # These two lines are required to top level widget (buttonbox
        # # in this case) to the existing GUI:
        # self.viewport.add(self.toplevel) 
        # self.toplevel.show_all()    

        self.initUI()
        
    def initUI(self):
        self.layout = QVBoxLayout(self.device_widget)

        foobutton = QPushButton('foo, 10 seconds!')
        barbutton = QPushButton('bar, 10 seconds, then error!')
        bazbutton = QPushButton('baz, 0.5 seconds!')
        addbazbutton = QPushButton('add 2 second timeout to baz')
        removebazbutton = QPushButton('remove baz timeout')
        bazunpickleable= QPushButton('try to pass baz a multiprocessing.Lock()')
        fatalbutton = QPushButton('fatal error, forgot to add @define_state to callback!')
        
        self.checkbutton = QPushButton('have baz\nreturn a Queue')
        self.checkbutton.setCheckable(True)
        
        #self.device_widget.addWidget(layout)
        self.layout.addWidget(foobutton)
        self.layout.addWidget(barbutton)
        self.layout.addWidget(bazbutton)
        self.layout.addWidget(addbazbutton)
        self.layout.addWidget(removebazbutton)
        self.layout.addWidget(bazunpickleable)
        self.layout.addWidget(fatalbutton)
        self.layout.addWidget(self.checkbutton)
        
        foobutton.clicked.connect(self.foo)
        barbutton.clicked.connect(self.bar)
        bazbutton.clicked.connect(self.baz)
        fatalbutton.clicked.connect(self.fatal )
        addbazbutton.clicked.connect(self.add_baz_timeout)
        removebazbutton.clicked.connect(self.remove_baz_timeout)
        bazunpickleable.clicked.connect(self.baz_unpickleable)

        
    # It is critical that you decorate your callbacks with @define_state
    # as below. This makes the function get queued up and executed
    # in turn by our state machine instead of immediately by the
    # GTK mainloop. Only don't decorate if you're certain that your
    # callback can safely happen no matter what state the system is
    # in (for example, adjusting the axis range of a plot, or other
    # appearance settings). You should never be calling queue_work
    # or do_after from un undecorated callback.
    @define_state(STATE_MANUAL,True)  
    def foo(self):
        self.logger.debug('entered foo')
        #self.toplevel.set_sensitive(False)
        # Here's how you instruct the worker process to do
        # something. When this callback returns, the worker will be
        # requested to do whatever you ask in queue_work (in this
        # case, MyWorker.foo(5,6,7,x='x') ). Then, no events will
        # be processed until that work is done. Once the work is
        # done, whatever has been set with do_after will be executed
        # (in this case self.leave_foo(1,2,3,bar=baz) ).
        results = yield(self.queue_work('My worker','foo', 5,6,7,x='x'))

        #self.toplevel.set_sensitive(True)
        self.logger.debug('leaving foo')
    
    # Here's what's NOT to do: forgetting to decorate a callback with @define_state
    # when it's not something that can safely be done asynchronously
    # to the state machine:
    def fatal(self):
        # This bug could be hard to track because nothing will happen
        # when you click the button -- only once you do some other,
        # correcly decorated callback will it become apparant that
        # something is wrong. So don't make this mistake!
        self.queue_work('My worker','foo', 5,6,7,x='x')
        
    @define_state(STATE_MANUAL,True)  
    def bar(self):
        self.logger.debug('entered bar')
        results = yield(self.queue_work('My worker','bar', 5,6,7,x=5))
      
        self.logger.debug('leaving bar')
        
    @define_state(STATE_MANUAL,True)  
    def baz(self, button=None):
        print threading.current_thread().name
        self.logger.debug('entered baz')
        results = yield(self.queue_work('My worker','baz', 5,6,7,x='x',return_queue=self.checkbutton.isChecked()))
        print results
        print threading.current_thread().name
        results = yield(self.queue_work('My worker','baz', 4,6,7,x='x',return_queue=self.checkbutton.isChecked()))
        print results
        print threading.current_thread().name
        self.logger.debug('leaving baz')
        
    # This event shows what happens if you try to send a unpickleable
    # event through a queue to the subprocess:
    @define_state(STATE_MANUAL,True)  
    def baz_unpickleable(self):
        self.logger.debug('entered baz_unpickleable')
        results = yield(self.queue_work('My worker','baz', 5,6,7,x=Lock()))
        self.logger.debug('leaving baz_unpickleable')
    
    # You don't need to decorate with @define_state if all you're
    # doing is adding a timeout -- adding a timeout can safely be done
    # asynchronously. But you can still decorate if you want, and you
    # should if you're doing other work in the same function call which
    # can't be done asynchronously.
    def add_baz_timeout(self):
        self.statemachine_timeout_add(2000,self.baz)
    
    # Similarly, no @define_state is required here -- same applies as above.    
    def remove_baz_timeout(self):
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
        
    def baz(self,zzz,*args,**kwargs):
        self.logger.debug('working on baz: time is %s'%repr(time.time()))
        time.sleep(0.5)
        if kwargs['return_queue']:
            return Queue()
        return 'results%d!!!'%zzz

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
    #excepthook.set_logger(logger)
    logger.info('\n\n===============starting===============\n')

if __name__ == '__main__':
    from qtutils.widgets.dragdroptab import DragDropTabWidget
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout(window)
    notebook = DragDropTabWidget()
    layout.addWidget(notebook)
    
    tab1 = MyTab(notebook,settings = {'device_name': 'Example'})
    tab2 = MyTab(notebook,settings = {'device_name': 'Example2'})
    
    window.show()
    #notebook.show()
    def run():
        app.exec_()
        tab1.close_tab()
        tab2.close_tab()
    sys.exit(run())

    # Run the demo!:
    # gtk.gdk.threads_init() 
    # window = gtk.Window() 
    # notebook = gtk.Notebook()
    # window.connect('destroy',lambda widget: gtk.main_quit())  
    # window.add(notebook)
    # notebook.show()
    # window.show()  
    # window.resize(800,600)
    # with gtk.gdk.lock:
        # gtk.main()
