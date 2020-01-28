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
