#!/usr/bin/env python
# encoding: utf-8
#
# Copyright (c) 2017 Dean Jackson <deanishe@deanishe.net>
#
# MIT Licence. See http://opensource.org/licenses/MIT
#
# Created on 2017-12-17
#

"""A selection of helper functions useful for building workflows."""

from __future__ import print_function, absolute_import

import atexit
from collections import namedtuple
from contextlib import contextmanager
import errno
import fcntl
import functools
import os
import signal
import subprocess
import sys
from threading import Event
import time

# AppleScript to call an External Trigger in Alfred
AS_TRIGGER = """
tell application "Alfred"
run trigger "{name}" in workflow "{bundleid}" {arg}
end tell
"""

# AppleScript to save a variable in info.plist
AS_CONFIG_SET = """
tell application "Alfred"
set configuration "{name}" to value "{value}" in workflow "{bundleid}" {export}
end tell
"""

# AppleScript to remove a variable from info.plist
AS_CONFIG_UNSET = """
tell application "Alfred"
remove configuration "{name}" in workflow "{bundleid}"
end tell
"""


class AcquisitionError(Exception):
    """Raised if a lock cannot be acquired."""


AppInfo = namedtuple('AppInfo', ['name', 'path', 'bundleid'])
"""Information about an installed application.

Returned by :func:`appinfo`. All attributes are Unicode.

.. py:attribute:: name

    Name of the application, e.g. ``u'Safari'``.

.. py:attribute:: path

    Path to the application bundle, e.g. ``u'/Applications/Safari.app'``.

.. py:attribute:: bundleid

    Application's bundle ID, e.g. ``u'com.apple.Safari'``.

"""


def unicodify(s, encoding='utf-8', norm=None):
    """Ensure string is Unicode.

    .. versionadded:: 1.31

    Decode encoded strings using ``encoding`` and normalise Unicode
    to form ``norm`` if specified.

    Args:
        s (str): String to decode. May also be Unicode.
        encoding (str, optional): Encoding to use on bytestrings.
        norm (None, optional): Normalisation form to apply to Unicode string.

    Returns:
        unicode: Decoded, optionally normalised, Unicode string.

    """
    if not isinstance(s, unicode):
        s = unicode(s, encoding)

    if norm:
        from unicodedata import normalize
        s = normalize(norm, s)

    return s


def utf8ify(s):
    """Ensure string is a bytestring.

    .. versionadded:: 1.31

    Returns `str` objects unchanced, encodes `unicode` objects to
    UTF-8, and calls :func:`str` on anything else.

    Args:
        s (object): A Python object

    Returns:
        str: UTF-8 string or string representation of s.

    """
    if isinstance(s, str):
        return s

    if isinstance(s, unicode):
        return s.encode('utf-8')

    return str(s)


def applescriptify(s):
    """Escape string for insertion into an AppleScript string.

    .. versionadded:: 1.31

    Replaces ``"`` with `"& quote &"`. Use this function if you want

    to insert a string into an AppleScript script:
        >>> script = 'tell application "Alfred" to search "{}"'
        >>> query = 'g "python" test'
        >>> script.format(applescriptify(query))
        'tell application "Alfred" to search "g " & quote & "python" & quote & "test"'

    Args:
        s (unicode): Unicode string to escape.

    Returns:
        unicode: Escaped string

    """
    return s.replace(u'"', u'" & quote & "')


def run_command(cmd, **kwargs):
    """Run a command and return the output.

    .. versionadded:: 1.31

    A thin wrapper around :func:`subprocess.check_output` that ensures
    all arguments are encoded to UTF-8 first.

    Args:
        cmd (list): Command arguments to pass to ``check_output``.
        **kwargs: Keyword arguments to pass to ``check_output``.

    Returns:
        str: Output returned by ``check_output``.

    """
    cmd = [utf8ify(s) for s in cmd]
    return subprocess.check_output(cmd, **kwargs)


def run_applescript(script, *args, **kwargs):
    """Execute an AppleScript script and return its output.

    .. versionadded:: 1.31

    Run AppleScript either by filepath or code. If ``script`` is a valid
    filepath, that script will be run, otherwise ``script`` is treated
    as code.

    Args:
        script (str, optional): Filepath of script or code to run.
        *args: Optional command-line arguments to pass to the script.
        **kwargs: Pass ``lang`` to run a language other than AppleScript.

    Returns:
        str: Output of run command.

    """
    cmd = ['/usr/bin/osascript', '-l', kwargs.get('lang', 'AppleScript')]

    if os.path.exists(script):
        cmd += [script]
    else:
        cmd += ['-e', script]

    cmd.extend(args)

    return run_command(cmd)


def run_jxa(script, *args):
    """Execute a JXA script and return its output.

    .. versionadded:: 1.31

    Wrapper around :func:`run_applescript` that passes ``lang=JavaScript``.

    Args:
        script (str): Filepath of script or code to run.
        *args: Optional command-line arguments to pass to script.

    Returns:
        str: Output of script.

    """
    return run_applescript(script, *args, lang='JavaScript')


def run_trigger(name, bundleid=None, arg=None):
    """Call an Alfred External Trigger.

    .. versionadded:: 1.31

    If ``bundleid`` is not specified, reads the bundle ID of the current
    workflow from Alfred's environment variables.

    Args:
        name (str): Name of External Trigger to call.
        bundleid (str, optional): Bundle ID of workflow trigger belongs to.
        arg (str, optional): Argument to pass to trigger.

    """
    if not bundleid:
        bundleid = os.getenv('alfred_workflow_bundleid')

    if arg:
        arg = 'with argument "{}"'.format(applescriptify(arg))
    else:
        arg = ''

    script = AS_TRIGGER.format(name=name, bundleid=bundleid,
                               arg=arg)

    run_applescript(script)


def set_config(name, value, bundleid=None, exportable=False):
    """Set a workflow variable in ``info.plist``.

    .. versionadded:: 1.33

    Args:
        name (str): Name of variable to set.
        value (str): Value to set variable to.
        bundleid (str, optional): Bundle ID of workflow variable belongs to.
        exportable (bool, optional): Whether variable should be marked
            as exportable (Don't Export checkbox).

    """
    if not bundleid:
        bundleid = os.getenv('alfred_workflow_bundleid')

    name = applescriptify(name)
    value = applescriptify(value)
    bundleid = applescriptify(bundleid)

    if exportable:
        export = 'exportable true'
    else:
        export = 'exportable false'

    script = AS_CONFIG_SET.format(name=name, bundleid=bundleid,
                                  value=value, export=export)

    run_applescript(script)


def unset_config(name, bundleid=None):
    """Delete a workflow variable from ``info.plist``.

    .. versionadded:: 1.33

    Args:
        name (str): Name of variable to delete.
        bundleid (str, optional): Bundle ID of workflow variable belongs to.

    """
    if not bundleid:
        bundleid = os.getenv('alfred_workflow_bundleid')

    name = applescriptify(name)
    bundleid = applescriptify(bundleid)

    script = AS_CONFIG_UNSET.format(name=name, bundleid=bundleid)

    run_applescript(script)


def appinfo(name):
    """Get information about an installed application.

    .. versionadded:: 1.31

    Args:
        name (str): Name of application to look up.

    Returns:
        AppInfo: :class:`AppInfo` tuple or ``None`` if app isn't found.

    """
    cmd = ['mdfind', '-onlyin', '/Applications',
           '-onlyin', os.path.expanduser('~/Applications'),
           '(kMDItemContentTypeTree == com.apple.application &&'
           '(kMDItemDisplayName == "{0}" || kMDItemFSName == "{0}.app"))'
           .format(name)]

    output = run_command(cmd).strip()
    if not output:
        return None

    path = output.split('\n')[0]

    cmd = ['mdls', '-raw', '-name', 'kMDItemCFBundleIdentifier', path]
    bid = run_command(cmd).strip()
    if not bid:  # pragma: no cover
        return None

    return AppInfo(unicodify(name), unicodify(path), unicodify(bid))


@contextmanager
def atomic_writer(fpath, mode):
    """Atomic file writer.

    .. versionadded:: 1.12

    Context manager that ensures the file is only written if the write
    succeeds. The data is first written to a temporary file.

    :param fpath: path of file to write to.
    :type fpath: ``unicode``
    :param mode: sames as for :func:`open`
    :type mode: string

    """
    suffix = '.{}.tmp'.format(os.getpid())
    temppath = fpath + suffix
    with open(temppath, mode) as fp:
        try:
            yield fp
            os.rename(temppath, fpath)
        finally:
            try:
                os.remove(temppath)
            except (OSError, IOError):
                pass


class LockFile(object):
    """Context manager to protect filepaths with lockfiles.

    .. versionadded:: 1.13

    Creates a lockfile alongside ``protected_path``. Other ``LockFile``
    instances will refuse to lock the same path.

    >>> path = '/path/to/file'
    >>> with LockFile(path):
    >>>     with open(path, 'wb') as fp:
    >>>         fp.write(data)

    Args:
        protected_path (unicode): File to protect with a lockfile
        timeout (float, optional): Raises an :class:`AcquisitionError`
            if lock cannot be acquired within this number of seconds.
            If ``timeout`` is 0 (the default), wait forever.
        delay (float, optional): How often to check (in seconds) if
            lock has been released.

    Attributes:
        delay (float): How often to check (in seconds) whether the lock
            can be acquired.
        lockfile (unicode): Path of the lockfile.
        timeout (float): How long to wait to acquire the lock.

    """

    def __init__(self, protected_path, timeout=0.0, delay=0.05):
        """Create new :class:`LockFile` object."""
        self.lockfile = protected_path + '.lock'
        self._lockfile = None
        self.timeout = timeout
        self.delay = delay
        self._lock = Event()
        atexit.register(self.release)

    @property
    def locked(self):
        """``True`` if file is locked by this instance."""
        return self._lock.is_set()

    def acquire(self, blocking=True):
        """Acquire the lock if possible.

        If the lock is in use and ``blocking`` is ``False``, return
        ``False``.

        Otherwise, check every :attr:`delay` seconds until it acquires
        lock or exceeds attr:`timeout` and raises an :class:`AcquisitionError`.

        """
        if self.locked and not blocking:
            return False

        start = time.time()
        while True:

            # Raise error if we've been waiting too long to acquire the lock
            if self.timeout and (time.time() - start) >= self.timeout:
                    raise AcquisitionError('lock acquisition timed out')

            # If already locked, wait then try again
            if self.locked:
                time.sleep(self.delay)
                continue

            # Create in append mode so we don't lose any contents
            if self._lockfile is None:
                self._lockfile = open(self.lockfile, 'a')

            # Try to acquire the lock
            try:
                fcntl.lockf(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock.set()
                break
            except IOError as err:  # pragma: no cover
                if err.errno not in (errno.EACCES, errno.EAGAIN):
                    raise

                # Don't try again
                if not blocking:  # pragma: no cover
                    return False

                # Wait, then try again
                time.sleep(self.delay)

        return True

    def release(self):
        """Release the lock by deleting `self.lockfile`."""
        if not self._lock.is_set():
            return False

        try:
            fcntl.lockf(self._lockfile, fcntl.LOCK_UN)
        except IOError:  # pragma: no cover
            pass
        finally:
            self._lock.clear()
            self._lockfile = None
            try:
                os.unlink(self.lockfile)
            except (IOError, OSError):  # pragma: no cover
                pass

            return True

    def __enter__(self):
        """Acquire lock."""
        self.acquire()
        return self

    def __exit__(self, typ, value, traceback):
        """Release lock."""
        self.release()

    def __del__(self):
        """Clear up `self.lockfile`."""
        self.release()  # pragma: no cover


class uninterruptible(object):
    """Decorator that postpones SIGTERM until wrapped function returns.

    .. versionadded:: 1.12

    .. important:: This decorator is NOT thread-safe.

    As of version 2.7, Alfred allows Script Filters to be killed. If
    your workflow is killed in the middle of critical code (e.g.
    writing data to disk), this may corrupt your workflow's data.

    Use this decorator to wrap critical functions that *must* complete.
    If the script is killed while a wrapped function is executing,
    the SIGTERM will be caught and handled after your function has
    finished executing.

    Alfred-Workflow uses this internally to ensure its settings, data
    and cache writes complete.

    """

    def __init__(self, func, class_name=''):
        """Decorate `func`."""
        self.func = func
        functools.update_wrapper(self, func)
        self._caught_signal = None

    def signal_handler(self, signum, frame):
        """Called when process receives SIGTERM."""
        self._caught_signal = (signum, frame)

    def __call__(self, *args, **kwargs):
        """Trap ``SIGTERM`` and call wrapped function."""
        self._caught_signal = None
        # Register handler for SIGTERM, then call `self.func`
        self.old_signal_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.func(*args, **kwargs)

        # Restore old signal handler
        signal.signal(signal.SIGTERM, self.old_signal_handler)

        # Handle any signal caught during execution
        if self._caught_signal is not None:
            signum, frame = self._caught_signal
            if callable(self.old_signal_handler):
                self.old_signal_handler(signum, frame)
            elif self.old_signal_handler == signal.SIG_DFL:
                sys.exit(0)

    def __get__(self, obj=None, klass=None):
        """Decorator API."""
        return self.__class__(self.func.__get__(obj, klass),
                              klass.__name__)
