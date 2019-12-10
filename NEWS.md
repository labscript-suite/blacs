## [2.8.0] - 2019-12-10

This release includes two bugfixes, one enhancement, one update for compatibility with a
new Python version, and one change to simplify writing device tabs for BLACS.

- Do not use hard-coded paths for temporary files, resolving permission errors in some
  circumstances. Contributed by Chris Billington.
  ([PR #74](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/74))

- Add Python 3.8 compatibility by using `html.escape` instead of the removed
  `cgi.escape` function. Contributed by Chris Billington.
  ([PR #76](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/76))

- Properly shutdown the `OutputBox` in each tab when a tab is restarted, resolving a
  memory leak. Contributed by Chris Billington.
  ([PR #77](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/77))

- Use new file-hashing functionality of `labscript_utils.filewatcher` to detect when
  modified files are restored to their previous state, and hide the "connection table
  has changed" notification. Contributed by Russell Anderson and Chris Billington.
  ([PR #61](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/61))

- Automatically add all connection table properties as instance attributes of `Worker`
  objects. This obviates the need to manually pass all these attriutes at startup,
  simplifying device tab code. Contributed by Chris Billington.
  ([PR #78](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/78))




- `labscript_utils.versions` Python 3.8 compatibility. Fixes an exception raised on
  Python 3.8 due the the `importlib_metadata` package becoming part of the standard
  library. Contributed by Chris Billington. 
  ([PR #94](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/94))

- `labscript_utils.filewatcher.FileWatcher` can now detect whether files have changed on
  disk by checking a hash of their contents, and not just their modified times. This
  means that a file reverting to its previous state can be detected, such that the
  "connection table needs to be recompiled" message in the next release of BLACS will be
  hidden if the connection table is restored to its previous state. Contributed by
  Russell Anderson.
  ([PR #61](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/61))

- The `labscript_utils.setup_logging` module now creates log files for applications in
  `<labscript_suite_profile>/logs` instead of the installation directory of the
  application itself. Contributed by Chris Billington.
  ([PR #95](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/95))

- `labscript_utils.labscript_suite_install_dir` has been renamed to
  `labscript_suite_profile`, with the former name kept as an alias. This reflects the
  fact that in the future, labscript suite applications may be installed as regular
  Python packages, and not in the directory containing logs, configuration and user
  libraries, which will now be referred to at the "labscript suite profile" directory
  instead of the "installation" directory. Also to help with that change, the
  `labscript_utils.winshell` module now uses the import path of each application instead
  of assuming it is in the profile directory for the purposes of creating windows
  shortcuts. Applications shortcuts now start applications with the `userlib` directory
  as the working directory instead of the application's installation directory.
  Contributed by Chris Billington.
  ([PR #96](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/96))

- Bugfix for using automatic metric prefixes with nonlinear unit conversion functions,
  these previously did the unit conversion incorrectly. Contributed by Peter Elgee and
  Chris Billington.
  ([PR #87](https://bitbucket.org/labscript_suite/labscript_utils/pull-requests/96))