Plugins
=======

BLACS supports custom user code that is not part of a device implementation in the form
of plugins. Plugins can add menu items, notifications, preferences that are edited in the
preferences dialog, and custom tabs alongside the device tabs. Plugins have access to
internal BLACS objects, such as the shot queue, and can register callback functions to be
run when certain events happen (such as a shot completing).

The API reference of the plugins that are included with BLACS is
:doc:`here<api/_autosummary/blacs.plugins>`.

The connection table plugin
---------------------------

This plugin is included in the default install of BLACS, and provides a clean interface to
manage the lab connection table that BLACS uses to automatically generate the device
tabs and their graphical interfaces. The plugin inserts a menu item that provides shortcuts
for:

#. editing the connection table Python file,
#. initiating the recompilation of the connection table, and
#. editing the preferences that control the behaviour of the plugin.

The preferences panel allows you to configure a list of hdf5 files containing runmanager
globals to use during the compilation of the connection table (commonly used as unit
conversion parameters), as well as a list of unit conversion Python files, to watch for any
changes. At startup, the plugin launches a background thread that monitors changes to
these files, as well as the connection table Python file and compiled connection table hdf5
file. If any modifications are detected, a notification is shown at the top of BLACS informing
that the lab connection table should be recompiled. If recompilation is chosen by the user,
the plugin manages the recompilation of the connection table using the runmanager API
and output from this process is displayed in a window. Once recompilation is successful,
the restart button of that window restarts BLACS so that the new connection table is
loaded. BLACS then has the same connection table as shots that runmanager compiles with
the same globals files.

