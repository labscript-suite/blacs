Plugins
=======

To cater to the variety of lab environments, BLACS supports custom user code (that is not
covered by a device implementation) in the form of plugins. Plugins allow custom graphical
interfaces to be created through the addition of menu items, notifications, preferences editable
through a common preferences panel, and custom tabs that sit alongside device tabs.
Plugins are also provided access to a variety of internal BLACS objects, such as the shot
queue, and can register callback functions to be run when certain events happen (such as a
shot completing). This provides a powerful basis for customising the behaviour of BLACS
in a way that is both modular and maintainable, providing a way to include optional conflicting
features without needing to resolve the incompatibility. Plugins can be easily shared
between groups, allowing for a diverse variety of control system interfaces that are all built
on a common platform. We have developed several plugins at Monash, which are detailed
in the following sections, and demonstrate the broad applicability of the plugin system.

The API refrence for the standard plugins is :doc:`here<api/_autosummary/blacs.plugins>`

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
the plugin relaunches BLACS so that the new connection table is loaded. This ensures that
BLACS is using the same knowledge of the experiment apparatus as any future shots will
when they are created by runmanager (assuming they share the globals files used).

