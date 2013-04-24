"""
Muddle utilities.
"""

import hashlib
import imp
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import errno
import xml.dom
import xml.dom.minidom
from collections import MutableMapping, Mapping, namedtuple
from ConfigParser import RawConfigParser
from StringIO import StringIO

try:
    import curses
except:
    curses = None

class GiveUp(Exception):
    """
    Use this to indicate that something has gone wrong and we are giving up.

    This is not an error in muddle itself, however, so there is no need for
    a traceback.

    By default, a return code of 1 is indicated by the 'retcode' value - this
    can be set by the caller to another value, which __main__.py should then
    use as its return code if the exception reaches it.
    """

    # We provide a single attribute, which is used to specify the exit code
    # to use when a command line handler gets back a GiveUp exception.
    retcode = 1

    def __init__(self, message=None, retcode=1):
        self.message = message
        self.retcode = retcode

    def __str__(self):
        if self.message is None:
            return ''
        else:
            return self.message

    def __repr__(self):
        parts = []
        if self.message is not None:
            parts.append(repr(self.message))
        if self.retcode != 1:
            parts.append('%d'%self.retcode)
        return 'GiveUp(%s)'%(', '.join(parts))


class MuddleBug(GiveUp):
    """
    Use this to indicate that something has gone wrong with muddle itself.

    We thus expect that a traceback will be produced.
    """
    pass


class Unsupported(GiveUp):
    """
    Use this to indicate that an action is unsupported.

    This is used, for instance, when git reports that it will not pull to a
    shallow clone, which is not an error, but the user will want to know.

    This is deliberately a subclass of GiveUp, because it *is* telling muddle
    to give up an operation.
    """
    pass

# Keep the old exception names for the moment, as well
Failure = GiveUp
Error = MuddleBug

# Start with the known label tags. Keys are the "in program" representation,
# values are the tag as used in labels themselves.

checkout_tags = {
                'CheckedOut' : "checked_out",
                'Pulled' : "pulled",
                'Merged' : "merged",
                'ChangesCommitted' : "changes_committed",
                'ChangesPushed' : "changes_pushed",
                }

package_tags = {
                'PreConfig' : "preconfig",
                'Configured' : "configured",
                'Built' : "built",
                'Installed' : "installed",
                'PostInstalled' : "postinstalled",

                'Clean' : "clean",
                'DistClean' : "distclean",
                }

deployment_tags = {
                # For deployments. These must be independent of each other and
                # transient or deployment will get awfully confused.
                # instructionsapplied is used to separate deployment and
                # instruction application - they need to run in different
                # address spaces so that application can be privileged.
                'Deployed' : "deployed",
                'InstructionsApplied' : "instructionsapplied",
                  }

__label_tags = {
                # Special tag for Distribute packages or checkouts
                'Distributed' : 'distributed',

                # Special tag used to dynamically load extensions
                # (e.g. the build description)
                'Loaded' : "loaded",

                # Used to denote a temporary label that should never
                # be stored beyond the scope of the current function call
                'Temporary' : "temporary",

                # Used by the initscripts package to store runtime environments.
                'RuntimeEnv' : "runtime_env",
                }

__label_tags.update(checkout_tags)
__label_tags.update(package_tags)
__label_tags.update(deployment_tags)

# We shall produce a named tuple type using the "in program" names
__label_tag_type = namedtuple('LabelTag',
                              ' '.join(__label_tags.keys()))

# And populate it from the dictionary. This means that we can do things
# like::
#
#    a = LabelTag.CheckedOut
#
# (which we could do if we defined a LabelTag class, with appropriate values),
# but we can also do things like::
#
#    if a in LabelTag:
#       print True
#
LabelTag = __label_tag_type(**__label_tags)

# And, on the same principle, the standard label types
__label_types = {'Checkout' : "checkout",
                 'Package' : "package",
                 'Deployment' : "deployment",

                 # Synthetic labels used purely to trick the dependency
                 # mechanism into doing what I want.
                 'Synthetic' : "synth",
                 }

__label_type_type = namedtuple('LabelType',
                               ' '.join(__label_types.keys()))

LabelType = __label_type_type(**__label_types)

# Sometimes, we want to map a label type to a default tag
# - these are the tags that we want to reach in our rules for each type
label_type_to_tag = {
        LabelType.Checkout   : LabelTag.CheckedOut,
        LabelType.Package    : LabelTag.PostInstalled,
        LabelType.Deployment : LabelTag.Deployed,
        }

# And directory types - i.e., what is the purpose of a particular directory?
# We use a description of the purpose of the directory type as its value,
# and trust to Python to be kind to us
DirTypeDict = {'Checkout'  : 'Checkout directory',
               'Object'    : 'Package object directory',
               'Deployed'  : 'Deployment directory',
               'Install'   : 'Install directory',
               'Root'      : 'Root of the build tree',
               'DomainRoot': 'Root of subdomain',
               'MuddleDir' : '.muddle directory',
               'Versions'  : 'Versions directory',
               'Unexpected': 'An unexpected place',
               }

__directory_type_type = namedtuple('DirType', ' '.join(DirTypeDict.keys()))

# Sometimes the reverse is useful
ReverseDirTypeDict = {}
for key, value in DirTypeDict.items():
    ReverseDirTypeDict[value] = key

DirType = __directory_type_type(**DirTypeDict)

def string_cmp(a,b):
    """
    Return -1 if a < b, 0 if a == b,  +1 if a > b.
    """
    if (a is None) and (b is None):
        return 0
    if (a is None):
        return -1
    if (b is None):
        return 1

    if (a < b):
        return -1
    elif (a==b):
        return 0
    else:
        return 1

# Total ordering class decorator.
# From http://code.activestate.com/recipes/576685/
# By Raymond Hettinger
# This is provided in functools in Python 2.7 and 3.2
def total_ordering(cls):
    'Class decorator that fills-in missing ordering methods'
    convert = {
        '__lt__': [('__gt__', lambda self, other: other < self),
                   ('__le__', lambda self, other: not other < self),
                   ('__ge__', lambda self, other: not self < other)],
        '__le__': [('__ge__', lambda self, other: other <= self),
                   ('__lt__', lambda self, other: not other <= self),
                   ('__gt__', lambda self, other: not self <= other)],
        '__gt__': [('__lt__', lambda self, other: other > self),
                   ('__ge__', lambda self, other: not other > self),
                   ('__le__', lambda self, other: not self > other)],
        '__ge__': [('__le__', lambda self, other: other >= self),
                   ('__gt__', lambda self, other: not other >= self),
                   ('__lt__', lambda self, other: not self >= other)]
    }
    if hasattr(object, '__lt__'):
        roots = [op for op in convert if getattr(cls, op) is not getattr(object, op)]
    else:
        roots = set(dir(cls)) & set(convert)
    assert roots, 'must define at least one ordering operation: < > <= >='
    root = max(roots)       # prefer __lt __ to __le__ to __gt__ to __ge__
    for opname, opfunc in convert[root]:
        if opname not in roots:
            opfunc.__name__ = opname
            opfunc.__doc__ = getattr(int, opname).__doc__
            setattr(cls, opname, opfunc)
    return cls


def mark_as_domain(dir, domain_name):
    """
    Mark the build in 'dir' as a (sub)domain

    This is done by creating a file ``.muddle/am_subdomain``

    'dir' should be the path to the directory contining the sub-build's
    ``.muddle`` directory (the "top" of the sub-build).

    'dir' should thus be of the form "<somewhere>/domains/<domain_name>",
    but we do not check this.

    The given 'domain_name' is written to the file, but this should
    not be particularly trusted - refer to the containing directory
    structure for the canonical domain name.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    with open(file_name, "w") as f:
        f.write(domain_name)
        f.write("\n")

def is_subdomain(dir):
    """
    Check if the given 'dir' is a (sub)domain.

    'dir' should be the path to the directory contining the build's
    ``.muddle`` directory (the "top" of the build).

    The build is assumed to be a (sub)domain if there is a file called
    ``.muddle/am_subdomain``.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    return os.path.exists(file_name)

def get_domain_name_from(dir):
    """
    Given a directory 'dir', extract the domain name.

    'dir' should not end with a trailing slash.

    It is assumed that 'dir' is of the form "<something>/domains/<domain_name>",
    and we want to return <domain_name>.
    """
    head, domain_name = os.path.split(dir)
    head, should_be_domains = os.path.split(head)
    if should_be_domains == 'domains':
        return domain_name
    else:
        raise MuddleBug("Cannot find domain name for '%s' because it is not"
                    " '<something>/domains/<domain_name>' (unexpected '%s')"%(dir,should_be_domains))


def find_domain(root_dir, dir):
    """
    Find the domain of 'dir'.

    'root_dir' is the root of the (entire) muddle build tree.

    This function basically works backwards through the path of 'dir', until it
    reaches 'root_dir'. As it goes, it assembles the full domain name for the
    domain enclosing 'dir'.

    Returns the domain name, or None if 'dir' is not within a subdomain, and
    the directory of the root of the domain. That is:

        (domain_name, domain_dir)  or  (None, None)
    """

    # Normalise so path.split() doesn't produce confusing junk.
    dir = os.path.normcase(os.path.normpath(dir))

    if not dir.startswith(root_dir):
        raise GiveUp("Directory '%s' is not within muddle build tree '%s'"%(
            dir, root_dir))

    domain_name = None
    domain_dir = None

    # Note that we assume a proper layout of the tree structure
    while dir != root_dir:
        # Might this be a subdomain root?
        if os.path.exists(os.path.join(dir, ".muddle")):
            if is_subdomain(dir):
                new_domain = get_domain_name_from(dir)
                if (domain_name is None):
                    domain_name = new_domain
                else:
                    domain_name = "%s(%s)"%(new_domain,domain_name)

                if domain_dir is None:
                    domain_dir = dir
            else:
                raise GiveUp("Directory '%s' contains a '.muddle' directory,\n"
                        "and is within the build tree at '%s'\n"
                        "but is marked as a subdomain"%(dir, root_dir))
        dir, tail = os.path.split(dir)

    return (domain_name, domain_dir)

def well_formed_dot_muddle_dir(dir):
    """Return True if this seems to be a well-formed .muddle directory

    We're not trying to be absolutely rigorous, but do want to detect
    (for instance) an erroneous file with that name, or an empty directory
    """
    return (os.path.exists(os.path.join(dir, 'Description')) and
            os.path.exists(os.path.join(dir, 'RootRepository')))


def find_root_and_domain(dir):
    """
    Find the build tree root containing 'dir', and find the domain of 'dir'.

    This function basically works backwards through the path of 'dir', until it
    finds a directory containing a '.muddle/' directory, that is not within a
    subdomain. As it goes, it assembles the full domain name for the domain
    enclosing 'dir'.

    Returns a pair (root_dir, current_domain).

    If 'dir' is not within a subdomain, then 'current_domain' will be None.

    If 'dir' is not within a muddle build tree, then 'root_dir' will also
    be None.
    """

    # Normalise so path.split() doesn't produce confusing junk.
    dir = os.path.normcase(os.path.normpath(dir))
    current_domain = None

    while True:
        # Might this be a tree root?
        potential = os.path.join(dir, ".muddle")
        if os.path.exists(potential):
            if not well_formed_dot_muddle_dir(potential):
                raise GiveUp("Found '%s',\nwhich does not appear to be a proper"
                             " .muddle directory. Giving up in confusion."%potential)
            if is_subdomain(dir):
                new_domain = get_domain_name_from(dir)

                if (current_domain is None):
                    current_domain = new_domain
                else:
                    current_domain = "%s(%s)"%(new_domain,current_domain)
            else:
                return (dir, current_domain)

        up1, basename = os.path.split(dir)
        if up1 == dir or dir == '/':    # We're done
            break

        dir = up1

    # Didn't find a directory.
    return (None, None)

def find_label_dir(builder, label):
    """Given a label, find the corresponding directory.

    * for checkout labels, the checkout directory
    * for package labels, the install directory
    * for deployment labels, the deployment directory

    This is the heart of "muddle query dir".
    """
    if label.type == LabelType.Checkout:
        dir = builder.db.get_checkout_path(label)
    elif label.type == LabelType.Package:
        dir = builder.package_install_path(label)
    elif label.type == LabelType.Deployment:
        dir = builder.deploy_path(label)
    else:
        dir = None
    return dir

def find_local_root(builder, label):
    """Given a label, find its "local" root directory.

    For a normal label, this will be the normal muddle root directory
    (where the top-level .muddle/ directory is).

    For a label in a subdomain, it will be the root directory of that
    subdomain - again, where its .muddle/ directory is.
    """
    label_dir = find_label_dir(builder, label)
    if label_dir is None:
        raise GiveUp('Cannot find local root, cannot determine location of label %s'%label)

    # Then we need to go up until we find we find a .muddle/ directory
    # (we assume that at worst we'll hit one at the top of the build tree)
    #
    # We know we're (somewhere) under either src/, install/ or deploy/
    # so we should have at least two levels to go up

    dir = label_dir
    while True:
        if os.path.exists(os.path.join(dir, '.muddle')):
            return dir

        up1, tail = os.path.split(dir)
        if up1 == dir or dir == '/':
            # We treat this as a bug because we assume we wouldn't BE here
            # unless we already knew (or rather, one of our callers did) that
            # we were "inside" a muddle build tree
            raise MuddleBug('Searching upwards for local root failed\n'
                            'Label was %s\n'
                            'Started at %s\n'
                            'Ended at %s, without finding a .muddle/ directory'%(
                                label, label_dir, up1))
        dir = up1

def find_local_relative_root(builder, label):
    """Given a label, find its "local" root directory, relative to toplevel.

    Calls find_local_root() and then calculates the location of that relative
    to the root of the entire muddle build tree.
    """
    local_root = find_local_root(builder, label)
    top_root = builder.db.root_path

    local_root = normalise_dir(local_root)
    top_root = normalise_dir(top_root)

    return os.path.relpath(local_root, top_root)

def is_release_build(dir):
    """
    Check if the given 'dir' is the top level of a release build.

    'dir' should be the path to the directory contining the build's
    ``.muddle`` directory (the "top" of the build).

    The build is assumed to be a release build if there is a file called
    ``.muddle/Release``.
    """
    file_name = os.path.join(dir, '.muddle', "Release")
    return os.path.exists(file_name)

def ensure_dir(dir, verbose=True):
    """
    Ensure that dir exists and is a directory, or throw an error.
    """
    if os.path.isdir(dir):
        return True
    elif os.path.exists(dir):
        raise MuddleBug("%s exists but is not a directory"%dir)
    else:
        if verbose:
            print "> Make directory %s"%dir
        os.makedirs(dir)

def pad_to(str, val, pad_with = " "):
    """
    Pad the given string to the given number of characters with the given string.
    """
    to_pad = (val - len(str)) / len(pad_with)
    arr =  [ str ]
    for i in range(0, to_pad):
        arr.append(pad_with)

    return "".join(arr)

def split_vcs_url(url):
    """
    Split a URL into a vcs and a repository URL. If there's no VCS
    specifier, return (None, None).
    """

    the_re = re.compile("^([A-Za-z]+)\+([A-Za-z+]+):(.*)$")

    m = the_re.match(url)
    if (m is None):
        return (None, None)

    return (m.group(1).lower(), "%s:%s"%(m.group(2),m.group(3)))


def unix_time():
    """
    Return the current UNIX time since the epoch.
    """
    return int(time.time())

def iso_time():
    """
    Retrieve the current time and date in ISO style ``YYYY-MM-DD HH:MM:SS``.
    """
    return time.strftime("%Y-%m-%d %H:%M:%S")

def current_user():
    """
    Return the identity of the current user, as an email address if possible,
    but otherwise as a UNIX uid
    """
    uid = os.getuid()
    a_pwd = pwd.getpwuid(uid)
    if (a_pwd is not None):
        return a_pwd.pw_name
    else:
        return None

def current_machine_name():
    """
    Return the identity of the current machine - possibly including the
    domain name, possibly not
    """
    return socket.gethostname()

def page_text(progname, text):
    """
    Try paging 'text' by piping it through 'progname'.

    Looks for 'progname' on the PATH, and if os.environ['PATH'] doesn't exist,
    tries looking for it on os.defpath.

    If an executable version of 'progname' can't be found, just prints the
    text out.

    If 'progname' is None (or an empty string, or otherwise false), then
    just print 'text'.
    """
    if progname:
        path = os.environ.get('PATH', os.defpath)
        path = path.split(os.pathsep)
        for locn in path:
            locn = normalise_dir(locn)
            prog = os.path.join(locn, progname)
            if os.path.exists(prog):
                try:
                    proc = subprocess.Popen([prog],
                                            stdin=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
                    proc.communicate(text)
                    return
                except OSError:
                    # We're not allowed to run it, or some other problem,
                    # so look for another candidate
                    continue
    print text

def run_cmd_for_output(cmd_array, env = None, useShell = False, fold_stderr=False, verbose = True):
    """
    Run a command and return a tuple (return value, stdour output, stderr output).
    """
    a_process = subprocess.Popen(cmd_array, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT if fold_stderr
                                                          else subprocess.PIPE,
                                 shell = useShell)
    (out, err) = a_process.communicate()
    return (a_process.wait(), out, err)


def run_cmd(cmd, env=None, allowFailure=False, isSystem=False, verbose=True):
    """
    Run a command via the shell, raising an exception on failure,

    * env is the environment to use when running the command.  If this is None,
      then ``os.environ`` is used.
    * if allowFailure is true, then failure of the command will be ignored.
    * otherwise, isSystem is used to decide what to do if the command fails.
      If isSystem is true, then this is a command being run by the system and
      failure should be reported by raising utils.MuddleBug. otherwise, it's being
      run on behalf of the user and failure should be reported by raising
      utils.GiveUp.
    * if verbose is true, then print out the command before executing it

    The command's stdout and stderr are redirected through Python's sys.stdout
    and sys.stderr respectively.

    Return the exit code of this command.
    """
    if env is None: # so, for instance, an empty dictionary is allowed
        env = os.environ
    if verbose:
        print "> %s"%cmd
    rv = subprocess.call(cmd, shell=True, env=env, stdout=sys.stdout, stderr=subprocess.STDOUT)
    if allowFailure or rv == 0:
        return rv
    else:
        if isSystem:
            raise MuddleBug("Command '%s' execution failed - %d"%(cmd,rv))
        else:
            raise GiveUp("Command '%s' execution failed - %d"%(cmd,rv))

def run_cmd_list(cmdlist, env=None, allowFailure=False, isSystem=False, verbose=True):
    """
    Run a command via the shell, raising an exception on failure,

    * env is the environment to use when running the command.  If this is None,
      then ``os.environ`` is used.
    * if allowFailure is true, then failure of the command will be ignored.
    * otherwise, isSystem is used to decide what to do if the command fails.
      If isSystem is true, then this is a command being run by the system and
      failure should be reported by raising utils.MuddleBug. otherwise, it's being
      run on behalf of the user and failure should be reported by raising
      utils.GiveUp.
    * if verbose is true, then print out the command before executing it

    The command's stdout and stderr are redirected through Python's sys.stdout
    and sys.stderr respectively.

    Return the exit code of this command.
    """
    if env is None: # so, for instance, an empty dictionary is allowed
        env = os.environ
    if verbose:
        print "> %s"%(' '.join(cmdlist))    # a poor approximation without shell quoting
    rv = subprocess.call(cmdlist, env=env, stdout=sys.stdout, stderr=subprocess.STDOUT)
    if allowFailure or rv == 0:
        return rv
    else:
        if isSystem:
            raise MuddleBug("Command '%s' execution failed - %d"%(' '.join(cmdlist),rv))
        else:
            raise GiveUp("Command '%s' execution failed - %d"%(' '.join(cmdlist),rv))


def get_cmd_data(cmd, env=None, isSystem=False, fold_stderr=True,
                 verbose=False, fail_nonzero=True):
    """
    Run the given command, and return its (returncode, stdout, stderr).

    If 'fold_stderr', then "fold" stderr into stdout, and return
    (returncode, stdout_data, NONE).

    If 'fail_nonzero' then if the return code is non-0, raise an explanatory
    exception (MuddleBug is 'isSystem', otherwise GiveUp).

    And yes, that means the default use-case returns a tuple of the form
    (0, <string>, None), but otherwise it gets rather awkward handling all
    the options.
    """
    if env is None:
        env = os.environ
    if verbose:
        print "> %s"%cmd
    p = subprocess.Popen(cmd, shell=True, env=env,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if fold_stderr
                                                  else subprocess.PIPE)
    stdoutdata, stderrdata = p.communicate()
    returncode = p.returncode
    if fail_nonzero and returncode:
        if isSystem:
            raise MuddleBug("Command '%s' execution failed - %d"%(cmd,returncode))
        else:
            raise GiveUp("Command '%s' execution failed - %d"%(cmd,returncode))
    return returncode, stdoutdata, stderrdata


def indent(text, indent):
    """Return the text indented with the 'indent' string.

    (i.e., place 'indent' in front of each line of text).
    """
    lines = text.split('\n')
    stuff = []
    for line in lines:
        stuff.append('%s%s'%(indent,line))
    return '\n'.join(stuff)

def wrap(text, width=None, **kwargs):
    """A convenience wrapper around textwrap.wrap()

    (basically because muddled users will have imported utils already).
    """
    if not width:
        width = num_cols()

    return "\n".join(textwrap.wrap(text, width=width, **kwargs))

def num_cols():
    """How many columns on our terminal?

    If it can't tell (e.g., because it curses is not available), returns 70.
    """
    if curses:
        try:
            curses.setupterm()
            cols = curses.tigetnum('cols')
            if cols <= 0:
                return 70
            else:
                return cols
        except TypeError:
            # We get this if stdout not an int, or does not have a fileno()
            # method, for instance if it has been redirected to a StringIO
            # object.
            return 70
    else:
        return 70

def truncate(text, columns=None, less=0):
    """Truncate the given text to fit the terminal.

    More specifically:

    1. Split on newlines
    2. If the first line is too long, cut it and add '...' to the end.
    3. Return the first line

    If 'columns' is 0, then don't do the truncation of the first line.

    If 'columns' is None, then try to work out the current terminal width
    (using "curses"), and otherwise use 80.

    If 'less' is specified, then the actual width used will be the calculated
    or given width, minus 'less' (so if columns=80 and less=2, then the maximum
    line length would be 78). Clearly this is ignored if 'columns' is 0.
    """
    text = text.split('\n')[0]
    if columns == 0:
        return text

    if columns is None:
        columns = num_cols()
    max_width = columns - less
    if len(text) > max_width:
        text = text[:max_width-3]+'...'
    return text


def dynamic_load(filename):
    try:
        try:
            with open(filename, 'rb') as fin:
                contents = fin.read()
        except IOError as e:
            if e.errno == errno.ENOENT:
                raise GiveUp('No such file: %s'%filename)
            else:
                raise GiveUp('Cannot open file %s\n%s\n'%(filename, e))
        hasher = hashlib.md5()
        hasher.update(contents)
        md5_digest = hasher.hexdigest()
        return imp.load_source(md5_digest, filename)
    except GiveUp:
        raise
    except Exception:
        raise GiveUp("Cannot load build description %s:\n"
                       "%s"%(filename, traceback.format_exc()))


def do_shell_quote(str):
    return maybe_shell_quote(str, True)

def maybe_shell_quote(str, doQuote):
    """
    If doQuote is False, do nothing, else shell-quote ``str``.

    Annoyingly, shell quoting things correctly must use backslashes, since
    quotes can (and will) be misinterpreted. Bah.

    NB: Despite the name, this is actually "escaping", rather then "quoting".
    Specifically, any single quote, double quote or backslash characters in
    the original string will be converted to a backslash followed by the
    original character, in the final string.
    """
    if doQuote:
        result = []
        for i in str:
            if i=='"' or i=="\\" or i=="'" or i==" ":
                result.append("\\")
            result.append(i)
        return "".join(result)
    else:
        return str

def text_in_node(in_xml_node):
    """
    Return all the text in this node.
    """
    in_xml_node.normalize()
    return_list = [ ]
    for c in in_xml_node.childNodes:
        if (c.nodeType == xml.dom.Node.TEXT_NODE):
            return_list.append(c.data)

    return "".join(return_list)


def recursively_remove(a_dir):
    """
    Recursively demove a directory.
    """
    if (os.path.exists(a_dir)):
        # Again, the most efficient way to do this is to tell UNIX to do it
        # for us.
        run_cmd("rm -rf \"%s\""%(a_dir))


def copy_file_metadata(from_path, to_path):
    """
    Copy file metadata.

    If 'to_path' is a link, then it tries to copy whatever it can from
    'from_path', treated as a link.

    If 'to_path' is not a link, then it copies from 'from_path', or, if
    'from_path' is a link, whatever 'from_path' references.

    Metadata is: mode bits, atime, mtime, flags and (if the process has an
    effective UID of 0) the ownership (uid and gid).
    """

    if os.path.islink(to_path):
        st = os.lstat(from_path)

        if hasattr(os, 'lchmod'):
            mode = stat.S_IMODE(st.st_mode)
            os.lchmod(to_path, mode)

        if hasattr(os, 'lchflags'):
            os.lchflags(to_path, st.st_flags)

        if os.geteuid() == 0 and hasattr(os, 'lchown'):
            os.lchown(to_path, st.st_uid, st.st_gid)
    else:
        st = os.stat(from_path)
        mode = stat.S_IMODE(st.st_mode)
        os.chmod(to_path, mode)
        os.utime(to_path, (st.st_atime, st.st_mtime))
        if hasattr(os, 'chflags'):
            os.chflags(to_path, st.st_flags)
        if os.geteuid() == 0:
            os.chown(to_path, st.st_uid, st.st_gid)

def copy_file(from_path, to_path, object_exactly=False, preserve=False, force=False):
    """
    Copy a file (either a "proper" file, not a directory, or a symbolic link).

    Just like recursively_copy, only not recursive :-)

    If the target file already exists, it is overwritten.

       Caveat: if the target file is a directory, it will not be overwritten.
       If the source file is a link, being copied as a link, and the target
       file is not a link, it will not be overwritten.

    If 'object_exactly' is true, then if 'from_path' is a symbolic link, it
    will be copied as a link, otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.
    """

    if object_exactly and os.path.islink(from_path):
        linkto = os.readlink(from_path)
        if os.path.islink(to_path):
            os.remove(to_path)
        os.symlink(linkto, to_path)
    else:
        try:
            shutil.copyfile(from_path, to_path)
        except IOError as e:
            if force and e.errno == errno.EACCES:
                os.remove(to_path)
                shutil.copyfile(from_path, to_path)
            else:
                raise

    if preserve:
        copy_file_metadata(from_path, to_path)

def recursively_copy(from_dir, to_dir, object_exactly=False, preserve=True, force=False):
    """
    Take everything in from_dir and copy it to to_dir, overwriting
    anything that might already be there.

    Dot files are included in the copying.

    If object_exactly is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If preserve is true, then the file's mode, ownership and timestamp will be
    copied, if possible. This is only really useful when copying as a
    privileged user.

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.
    """

    copy_without(from_dir, to_dir, object_exactly=object_exactly,
                 preserve=preserve, force=force)


def split_path_left(in_path):
    """
    Given a path ``a/b/c ...``, return a pair
    ``(a, b/c..)`` - ie. like ``os.path.split()``, but leftward.

    What we actually do here is to split the path until we have
    nothing left, then take the head and rest of the resulting list.

    For instance:

        >>> split_path_left('a/b/c')
        ('a', 'b/c')
        >>> split_path_left('a/b')
        ('a', 'b')

    For a single element, behave in sympathy (but, of course, reversed) to
    ``os.path.split``:

        >>> import os
        >>> os.path.split('a')
        ('', 'a')
        >>> split_path_left('a')
        ('a', '')

    The empty string isn't really a sensible input, but we cope:

        >>> split_path_left('')
        ('', '')

    And we take some care with delimiters (hopefully the right sort of care):

        >>> split_path_left('/a///b/c')
        ('', 'a/b/c')
        >>> split_path_left('//a/b/c')
        ('', 'a/b/c')
        >>> split_path_left('///a/b/c')
        ('', 'a/b/c')

    """

    if not in_path:
        return ('', '')

    # Remove redundant sequences of '//'
    # This reduces paths like '///a//b/c' to '/a/b/c', but unfortunately
    # it leaves '//a/b/c' untouched
    in_path = os.path.normpath(in_path)

    remains = in_path
    lst = [ ]

    while remains and remains not in ("/", "//"):
        remains, end = os.path.split(remains)
        lst.append(end)

    if remains in ("/", "//"):
        lst.append("")

    # Our list is in reverse order, so ..
    lst.reverse()

    if False:
        rp = lst[1]
        for i in lst[2:]:
            rp = os.path.join(rp, i)
    else:
        if len(lst) > 1:
            rp = os.path.join(*lst[1:])
        else:
            rp = ""

    return (lst[0], rp)


def print_string_set(ss):
    """
    Given a string set, return a string representing it.
    """
    result = [ ]
    for s in ss:
        result.append(s)

    return " ".join(result)

def c_escape(v):
    """
    Escape sensitive characters in v.
    """

    return re.sub(r'([\r\n"\'\\])', r'\\\1', v)

def replace_root_name(base, replacement, filename):
    """
    Given a filename, a base and a replacement, replace base with replacement
    at the start of filename.
    """
    #print "replace_root_name %s, %s, %s"%(base,replacement, filename)
    base_len = len(base)
    if (filename.startswith(base)):
        left = replacement + filename[base_len:]
        if len(left) > 1 and left[:2] == '//':
            left = left[1:]
        return left
    else:
        return filename


def parse_mode(in_mode):
    """
    Parse a UNIX mode specification into a pair (clear_bits, set_bits).
    """

    # Annoyingly, people do write modes as '6755' etc..
    if (in_mode[0] >= '0' and in_mode[0] <= '9'):
        # It's octal.
        clear_bits = 07777
        set_bits = int(in_mode, 8)

        return (clear_bits, set_bits)
    else:
        # @todo Parse symbolic modes here.
        raise GiveUp("Unsupported UNIX modespec %s"%in_mode)

def parse_uid(builder, text_uid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming
               your uid is numeric
    """
    return int(text_uid)

def parse_gid(builder, text_gid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming
               your gid is numeric
    """
    return int(text_gid)


def xml_elem_with_child(doc, elem_name, child_text):
    """
    Return an element 'elem_name' containing the text child_text in doc.
    """
    el = doc.createElement(elem_name)
    el.appendChild(doc.createTextNode(child_text))
    return el


def _copy_without(src, dst, ignored_names, object_exactly, preserve, force):
    """
    The insides of copy_without. See that for more documentation.

    'ignored_names' must be a sequence of filenames to ignore (but may be empty).
    """

    # Inspired by the example for shutil.copytree in the Python 2.6 documentation

    names = os.listdir(src)

    if True:
        ensure_dir(dst, verbose=False)
    else:
        if not os.path.exists(dst):
            os.makedirs(dst)

    for name in names:
        if name in ignored_names:
            continue

        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if object_exactly and os.path.islink(srcname):
                copy_file(srcname, dstname, object_exactly=True, preserve=preserve)
            elif os.path.isdir(srcname):
                _copy_without(srcname, dstname, ignored_names=ignored_names,
                              object_exactly=object_exactly, preserve=preserve,
                              force=force)
            else:
                copy_file(srcname, dstname, object_exactly=object_exactly,
                          preserve=preserve, force=force)
        except (IOError, os.error), why:
            raise GiveUp('Unable to copy %s to %s: %s'%(srcname, dstname, why))

    try:
        copy_file_metadata(src, dst)
    except OSError, why:
        raise GiveUp('Unable to copy properties of %s to %s: %s'%(src, dst, why))

def copy_without(src, dst, without=None, object_exactly=True, preserve=False,
                 force=False, verbose=True):
    """
    Copy files from the 'src' directory to the 'dst' directory, without those in 'without'

    If given, 'without' should be a sequence of filenames - for instance,
    ['.bzr', '.svn'].

    If 'object_exactly' is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.

    If 'verbose' is true (the default), print out what we're copying.

    Creates directories in the destination, if necessary.

    Uses copy_file() to copy each file.
    """

    if without is not None:
        ignored_names = without
    else:
        ignored_names = set()

    if verbose:
        print 'Copying %s to %s'%(src, dst),
        if without:
            print 'ignoring %s'%without
        print

    _copy_without(src, dst, ignored_names, object_exactly, preserve, force)

def copy_name_list_with_dirs(file_list, old_root, new_root,
                             object_exactly = True, preserve = False):
    """

    Given file_list, create file_list[new_root/old_root], creating
    any directories you need on the way.

    file_list is a list of full path names.
    old_root is the old root directory
    new_root is where we want them copied
    """
    for f in file_list:
        tgt_name = replace_root_name(old_root, new_root, f)
        target_dir = os.path.dirname(tgt_name)
        ensure_dir(target_dir)
        copy_file(f, tgt_name, object_exactly, preserve)


def get_prefix_pair(prefix_one, value_one, prefix_two, value_two):
    """
    Returns a pair (prefix_onevalue_one, prefix_twovalue_two) - used
    by rrw.py as a utility function
    """
    return ("%s%s"%(prefix_one, value_one), "%s%s"%(prefix_two, value_two))

def rel_join(vroot, path):
    """
    Find what path would be called if it existed inside vroot. Differs from
    os.path.join() in that if path contains a leading '/', it is not
    assumed to override vroot.

    If vroot is none, we just return path.
    """

    if (vroot is None):
        return path

    if (len(path) == 0):
        return vroot

    if path[0] == '/':
        path = path[1:]

    return os.path.join(vroot, path)


def split_domain(domain_name):
    """
    Given a domain name, return a tuple of the hierarchy of sub-domains.

    For instance:

        >>> split_domain('a')
        ['a']
        >>> split_domain('a(b)')
        ['a', 'b']
        >>> split_domain('a(b(c))')
        ['a', 'b', 'c']
        >>> split_domain('a(b(c)')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)" has mis-matched parentheses

    We don't actually allow "sibling" sub-domains, so we try to complain
    helpfully:

        >>> split_domain('a(b(c)(d))')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)(d))" has 'sibling' sub-domains

    If we're given '' or None, we return [''], "normalising" the domain name.

        >>> split_domain('')
        ['']
        >>> split_domain(None)
        ['']
    """
    if domain_name is None:
        return ['']

    if '(' not in domain_name:
        return [domain_name]

    if ')(' in domain_name:
        raise GiveUp('Domain name "%s" has '
                      "'sibling' sub-domains"%domain_name)

    parts = domain_name.split('(')

    num_closing = len(parts) - 1
    if not parts[-1].endswith( num_closing * ')' ):
        raise GiveUp('Domain name "%s" has mis-matched parentheses'%domain_name)

    parts[-1] = parts[-1][:- num_closing]
    return parts

def join_domain(domain_parts):
    """Re-join a domain name we split with split_domain.
    """
    if len(domain_parts) == 1:
        return domain_parts[0]

    start = domain_parts[0]
    end = ''
    domain_parts = domain_parts[1:]
    while domain_parts:
        start += '(' + domain_parts[0]
        end += ')'
        domain_parts = domain_parts[1:]
    return start + end

def sort_domains(domains):
    """Given a sequence of domain names, return them sorted by depth.

    So, given some random domain names (and we forgot to forbid strange
    names starting with '+' or '-'):

    >>> a = ['a', '+1', '-2', 'a(b(c2))', 'a(b(c1))', '+1(+2(+4(+4)))',
    ...    'b(b)', 'b', 'b(a)', 'a(a)', '+1(+2)', '+1(+2(+4))', '+1(+3)']

    sorting "alphabetically" gives the wrong result:

    >>> sorted(a)
    ['+1', '+1(+2(+4(+4)))', '+1(+2(+4))', '+1(+2)', '+1(+3)', '-2', 'a', 'a(a)', 'a(b(c1))', 'a(b(c2))', 'b', 'b(a)', 'b(b)']

    so we needed this function:

    >>> sort_domains(a)
    ['+1', '+1(+2)', '+1(+2(+4))', '+1(+2(+4(+4)))', '+1(+3)', '-2', 'a', 'a(a)', 'a(b(c1))', 'a(b(c2))', 'b', 'b(a)', 'b(b)']

    If we're given a domain name that is None, we'll replace it with ''.
    """
    name_lists = []
    for domain in domains:
        # 'fred(jim)' becomes ['fred', 'jim']
        # '' and None become ['']
        name_lists.append(split_domain(domain))

    # ['fred', 'jim'] becomes 'fred~jim'
    domain_strings = map('~'.join, name_lists)
    # And sorting should now do what we want
    domain_strings.sort()

    result = []
    for thing in domain_strings:
        result.append(join_domain(thing.split('~')))

    return result

def domain_subpath(domain_name):
    """Calculate the sub-path for a given domain name.

    For instance:

        >>> domain_subpath('a')
        'domains/a'
        >>> domain_subpath('a(b)')
        'domains/a/domains/b'
        >>> domain_subpath('a(b(c))')
        'domains/a/domains/b/domains/c'
        >>> domain_subpath('a(b(c)')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)" has mis-matched parentheses

    """
    if domain_name is None:
        return ''

    parts = []
    for thing in split_domain(domain_name):
        parts.append('domains')
        parts.append(thing)

    return os.path.join(*parts)


gArchName = None

def arch_name():
    """
    Retrieve the name of the architecture on which we're running.
    Some builds require packages to be built on a particular (odd) architecture.
    """
    global gArchName

    if (gArchName is None):
        # This is what the docs say you should do. Ugh.
        x = subprocess.Popen(["uname", "-m"], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE).communicate()[0]
        gArchName = x.strip()

    return gArchName


def unescape_backslashes(str):
    """
    Replace every string '\\X' with X, as if you were a shell
    """

    wasBackslash = False
    result = [ ]
    for i in str:
        if (wasBackslash):
            result.append(i)
            wasBackslash = False
        else:
            if (i == '\\'):
                wasBackslash = True
            else:
                result.append(i)

    return "".join(result)



def quote_list(lst):
    """
    Given a list, quote each element of it and return them, space separated
    """
    return " ".join(map(do_shell_quote, lst))


def unquote_list(lst):
    """
    Given a list of objects, potentially enclosed in quotation marks or other
    shell weirdness, return a list of the actual objects.
    """

    # OK. First, dispose of any enclosing quotes.
    result = [ ]
    lst = lst.strip()
    if (lst[0] == '\'' or lst[0] == "\""):
        lst = lst[1:-1]

    initial = lst.split(' ')
    last = None

    for i in initial:
        if (last is not None):
            last = last + i
        else:
            last = i

        # If last ended in a backslash, round again
        if (len(last) > 0 and last[-1] == '\\'):
            last = last[:-1]
            continue

        # Otherwise, dump it, unescaping everything else
        # as we do so
        result.append(unescape_backslashes(last))
        last = None

    if (last is not None):
        result.append(unescape_backslashes(last))

    return result

def find_by_predicate(source_dir, accept_fn, links_are_symbolic = True):
    """
    Given a source directory and an acceptance function
     fn(source_base, file_name) -> result

    Obtain a list of [result] if result is not None.
    """

    result = [ ]

    r = accept_fn(source_dir)
    if (r is not None):
        result.append(r)


    if (links_are_symbolic and os.path.islink(source_dir)):
        # Bah
        return result

    if (os.path.isdir(source_dir)):
        # We may need to recurse...
        names = os.listdir(source_dir)

        for name in names:
            full_name = os.path.join(source_dir, name)
            r = accept_fn(full_name)
            if (r is not None):
                result.append(r)

            # os.listdir() doesn't return . and ..
            if (os.path.isdir(full_name)):
                result.extend(find_by_predicate(full_name, accept_fn, links_are_symbolic))

    return result

class MuddleSortedDict(MutableMapping):
    """
    A simple dictionary-like class that returns keys in sorted order.
    """
    def __init__(self):
        self._keys = set()
        self._dict = {}

    def __setitem__(self, key, value):
        self._dict[key] = value
        self._keys.add(key)

    def __getitem__(self, key):
        return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._keys.discard(key)

    def __len__(self):
        return len(self._keys)

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        keys = list(self._keys)
        keys.sort()
        return iter(keys)

class MuddleOrderedDict(MutableMapping):
    """
    A simple dictionary-like class that returns keys in order of (first)
    insertion.
    """
    def __init__(self):
        self._keys = []
        self._dict = {}

    def __setitem__(self, key, value):
        if key not in self._dict:
            self._keys.append(key)
        self._dict[key] = value

    def __getitem__(self, key):
        return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._keys.remove(key)

    def __len__(self):
        return len(self._keys)

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        return iter(self._keys)

def calc_file_hash(filename):
    """Calculate and return the SHA1 hash for the named file.
    """
    with HashFile(filename) as fd:
        for line in fd:
            pass
    return fd.hash()

class HashFile(object):
    """
    A very simple class for handling files and calculating their SHA1 hash.

    We support a subset of the normal file class, but as lines are read
    or written, we calculate a SHA1 hash for the file.

    Optionally, comment lines and/or blank lines can be ignored in calculating
    the hash, where comment lines are those starting with a '#', or whitespace
    and a '#', and blank lines are those which contain only whitespace
    (which includes empty lines).
    """

    def __init__(self, name, mode='r', ignore_comments=False, ignore_blank_lines=False):
        """
        Open the file, for read or write.

        * 'name' is the name (path) of the file to open
        * 'mode' is either 'r' (for read) or 'w' (for write). If 'w' is
          specified, then if the file doesn't exist, it will be created,
          otherwise it will be truncated.
        * if 'ignore_comments' is true, then lines starting with a '#' (or
          whitespace and a '#') will not be used in calculating the hash.
        * if 'ignore_blank_lines' is true, then lines that are empty (zero
          length), or contain only whitespace, will not be used in calculating
          the hash.

        Note that this "ignore" doesn't mean "don't write to the file", it
        just means "ignore when calculating the hash".
        """
        if mode not in ('r', 'w'):
            raise ValueError("HashFile 'mode' must be one of 'r' or 'w', not '%s'"%mode)
        self.name = name
        self.mode = mode
        self.ignore_comments = ignore_comments
        self.ignore_blank_lines = ignore_blank_lines
        self.fd = open(name, mode)
        self.sha = hashlib.sha1()

    def _add_to_hash(self, text):
        """Should we add this line of text to our hash calculation?
        """
        if self.ignore_comments and text.lstrip().startswith('#'):
            return False

        if self.ignore_blank_lines and text.strip() == '':
            return False

        return True

    def write(self, text):
        r"""
        Write the give text to the file, and add it to the SHA1 hash as well.

        (Unless we are ignoring comment lines and it is a comment line, or
        we are ignoring blank lines and it is a blank line, in which case it
        will be written to the file but not added  to the hash.)

        As is normal for file writes, the '\n' at the end of a line must be
        specified.
        """
        if self.mode != 'w':
            raise MuddleBug("Cannot write to HashFile '%s', opened for read"%self.name)
        self.fd.write(text)

        if self._add_to_hash(text):
            self.sha.update(text)

    def readline(self):
        """
        Read the next line from the file, and add it to the SHA1 hash as well.

        Returns '' if there is no next line (i.e., EOF is reached).
        """
        if self.mode != 'r':
            raise MuddleBug("Cannot read from HashFile '%s', opened for write"%self.name)
        text = self.fd.readline()

        if text == '':
            return ''

        if self._add_to_hash(text):
            self.sha.update(text)
        return text

    def hash(self):
        """
        Return the SHA1 hash, calculated from the lines so far, as a hex string.
        """
        return self.sha.hexdigest()

    def close(self):
        """
        Close the file.
        """
        self.fd.close()

    # Support for "with"
    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close()
        else:
            # An exception occurred, so do any tidying up necessary
            # - well, there isn't anything special to do, really
            self.close()
            # And allow the exception to be re-raised
            return False

    # Support for iteration (over lines)
    def __iter__(self):
        if self.mode != 'r':
            raise MuddleBug("Cannot iterate over HashFile '%s', opened for write"%self.name)
        return self

    def next(self):
        text = self.readline()
        if text == '':
            raise StopIteration
        else:
            return text

class VersionNumber(object):
    """Simple support for two part "semantic version" numbers.

    Such version numbers are of the form <major>.<minor>
    """

    def __init__(self, major=0, minor=0):
        if not isinstance(major, int) or not isinstance(minor, int):
            raise GiveUp('VersionNumber arguments must be integers,'
                         ' not %s, %s'%(repr(major), repr(minor)))

        if major < 0 or minor < 0:
            raise GiveUp('VersionNumber arguments may not be negative,'
                         ' as in %s, %s'%(major, minor))

        self.major = major
        self.minor = minor

    def __str__(self):
        if self.major < 0:
            return '<unset>'
        else:
            return '%d.%d'%(self.major, self.minor)

    def __repr__(self):
        if self.major < 0:
            return 'VersionNumber.unset()'
        else:
            return 'VersionNumber(%d, %d)'%(self.major, self.minor)

    def __eq__(self, other):
        return (self.major == other.major and
                self.minor == other.minor)

    def __lt__(self, other):
        if self.major < other.major:
            return True
        if self.minor < other.minor:
            return True
        return False

    __gt__ = lambda self, other: not (self < other or self == other)
    __le__ = lambda self, other: self < other or self == other
    __ge__ = lambda self, other: not self < other

    def next(self):
        """Return the next (minor) version number.
        """
        if self.major < 0:
            return VersionNumber(0, 0)
        else:
            return VersionNumber(self.major, self.minor+1)

    @staticmethod
    def unset():
        """Return an unset version number.

        Unset version numbers compare less than proper ones.
        """
        v = VersionNumber()
        v.major = -1
        v.minor = -1
        return v

    @staticmethod
    def from_string(s):
        parts = s.split('.')
        num_parts = len(parts)
        try:
            if num_parts == 0:
                raise GiveUp('VersionNumber must be <major>[.<minor>], not "%s"'%s)
            elif num_parts == 1:
                return VersionNumber(int(parts[0], 10))
            elif num_parts == 2:
                return VersionNumber(int(parts[0], 10), int(parts[1], 10))
            else:
                raise GiveUp('VersionNumber must be at most 2 parts, <major>.<minor>, not "%s"'%s)
        except ValueError as e:
            raise GiveUp('VersionNumber parts must be integers, not %s:\n%s'%(s, e))


def normalise_dir(dir):
    dir = os.path.expanduser(dir)
    dir = os.path.abspath(dir)
    dir = os.path.normpath(dir)     # remove double slashes, etc.
    return dir

# It should really be called normalise_path - allow me to use that without
# yet having replaced all occurrences...
normalise_path = normalise_dir

# End file.
