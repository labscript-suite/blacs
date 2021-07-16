Usage
=====

BLACS is the primary interface between experiment shot files created by runmanager, and
the hardware devices that control the apparatus. BLACS provides a graphical interface for
users to manage the execution of shots, and manually control the output state of hardware
devices. In order to support heterogenous hardware, the functionality of BLACS can be
extended by developers (who implement support for custom devices) through the provided
BLACS API. BLACS thus broadly consists of a set of device code that interfaces with
the hardware and provides programmatic and manual control of that hardware, which is
discussed in :doc:`device-tabs`, and a shot management routine that receives shot files from runmanager
and schedules their execution on the apparatus, which is discussed in :doc:`shot-management`.

BLACS is also readily extensible using a plugin system, discussed in :doc:`plugins`.

.. toctree::
    :maxdepth: 2

    device-tabs
    shot-management
    plugins

.. rubric:: Footnotes

.. [1] Documentation taken from Phillip T. Starkey *A software framework for control and automation of precisely timed experiments*
    Thesis, Monash University (2019) https://doi.org/10.26180/5d1db8ffe29ef