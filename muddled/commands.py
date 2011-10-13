"""
Muddle commands - these get run more or less directly by 
the main muddle command and are abstracted out here in
case your programs want to run them themselves
"""

# The use of Command subclass docstrings as "help" texts relies on the
# non-PEP8-standard layout of the docstrings, with the opening triple
# quote on a line by itself, and the text starting on the next line.
#
#    (This is "house style" in the muddled package anyway.)
#
# XXX It also means that a firm decision needs to be made about those
# XXX same docstrings. For "help" purposes, as unadorned (by markup)
# XXX as possible is good, whilst for sphinx/reStructuredText purposes,
# XXX somewhat more markup would make the generated documentation better
# XXX (and more consistent with other muddled modules).

from db import Database
from depend import Label, label_list_to_string
import depend
import env_store
import instr
import mechanics
import pkg
import test
import time
import utils
import version_control

import difflib
import os
import xml.dom.minidom
import subst
import subprocess
import sys
import urllib
import textwrap
import pydoc
from db import InstructionFile
from urlparse import urlparse
from utils import VersionStamp, GiveUp, Unsupported

# Following Richard's naming conventions...
# A dictionary of <command name> : <command class>
# If a command has aliases, then they will also be entered as keys
# in the dictionary, with the same <command instance> as their value.
# If a command has subcommands, then it will be entered in this dictionary,
# but its <command instance> will be None.
g_command_dict = {}
# A list of all of the known commands, by their "main" name
# (so one name per command, only)
g_command_names = []
# A dictionary of <category name> : [<command name>]
g_command_categories = {}
# A dictionary of <command alias> : <command name>
# (of course, the keys are then the list of things that *are* aliases)
g_command_aliases = {}

# The categories, and an order for them
CAT_INIT='init'
CAT_CHECKOUT='checkout'
CAT_PACKAGE='package'
CAT_DEPLOYMENT='deployment'
CAT_QUERY='query'
CAT_STAMP='stamp'
CAT_MISC='misc'
CAT_OTHER='other'
g_command_categories_in_order = [CAT_INIT, CAT_CHECKOUT, CAT_PACKAGE,
        CAT_DEPLOYMENT, CAT_QUERY, CAT_STAMP, CAT_MISC, CAT_OTHER]

def in_category(command_name, category, for_subcommand=False):
    if category not in g_command_categories_in_order:
        raise GiveUp("Command %s cannot be added to unexpected"
                     " category %s"%(command_name, category))

    if for_subcommand:
        if category not in g_command_categories:
            g_command_categories[category] = [command_name]
    else:
        if category in g_command_categories:
            g_command_categories[category].append(command_name)
        else:
            g_command_categories[category] = [command_name]

def command(command_name, category, aliases=None):
    """A simple decorator to remmember a class by its command name.

    'category' indicates which type of command this is
    """
    if command_name in g_command_dict:
        raise GiveUp("Command '%s' is already defined"%command_name)
    def rememberer(klass):
        g_command_dict[command_name] = klass
        if aliases:
            for alias in aliases:
                g_command_aliases[alias] = command_name
                g_command_dict[alias] = klass
        klass.cmd_name = command_name
        return klass

    g_command_names.append(command_name)
    in_category(command_name, category)

    return rememberer

# A dictionary of the form <command_name> : <sub_command_dict>,
# where each <sub_command_dict> is a dictionary of
# <sub_command_name : <subcommand class>
g_subcommand_dict = {}
# A dictionary of subcommand aliases, arranged as
# <command_name> : <sub_command_dict> where each <sub_command_dict>
# is a dictionary of <alias> : <subcommand>.
g_subcommand_aliases = {}
# A list of all of the known commands, by their "main" name
# (so one name per command, only) each as a tuple of (<cmd>, <subcmd>)
g_subcommand_names = []

def subcommand(main_command, sub_command, category, aliases=None):
    """Remember the class for <main_command> <subcommand>.
    """
    if main_command not in g_command_dict:
        g_command_dict[main_command] = None
        sub_dict = {}
        g_subcommand_dict[main_command] = sub_dict
    else:
        sub_dict = g_subcommand_dict[main_command]
        if sub_command in sub_dict:
            raise GiveUp("Command '%s %s' is already defined"%(main_command,sub_command))
    g_subcommand_names.append((main_command, sub_command))
    in_category(main_command, category, True)
    def rememberer(klass):
        sub_dict[sub_command] = klass
        klass.cmd_name = '%s %s'%(main_command, sub_command)
        if aliases:
            if main_command not in g_subcommand_aliases:
                g_subcommand_aliases[main_command] = {}
            alias_dict = g_subcommand_aliases[main_command]
            for alias in aliases:
                alias_dict[alias] = sub_command
                sub_dict[alias] = klass
        return klass
    return rememberer

class Command:
    """
    Abstract base class for muddle commands

    Each subclass is a ``muddle`` command, and its docstring is the "help"
    text for that command.
    """

    cmd_name = '<Undefined>'

    def __init__(self):
        self.options = { }

    def help(self):
        return self.__doc__

    def requires_build_tree(self):
        """
        Returns True iff this command requires an initialised
        build tree, False otherwise.
        """
        return True

    def set_options(self, opt_dict):
        """
        Set command options - usually from the options passed to mudddle.
        """
        self.options = opt_dict

    def set_old_env(self, old_env):
        """
        Take a copy of the environment before muddle sets its own
        variables - used by commands like subst to substitute the
        variables in place when muddle was called rather than those
        that would apply when the susbt command was executed.
        """
        self.old_env = old_env

    def no_op(self):
        """
        Is this is a no-op (just print) operation?
        """
        return ("no_operation" in self.options)


    def with_build_tree(self, builder, current_dir, args):
        """
        Run this command with a build tree.
        """
        raise GiveUp("Can't run %s with a build tree."%self.cmd_name)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Run this command without a build tree.
        """
        raise GiveUp("Can't run %s without a build tree."%self.cmd_name)

@command('help', CAT_QUERY)
class Help(Command):
    """
    To get help on commands, use:

      muddle help [<switch>] [<command>]

    specifically:

      muddle help <cmd>          for help on a command
      muddle help <cmd> <subcmd> for help on a subcommand
      muddle help _all           for help on all commands
      muddle help <cmd> _all     for help on all <cmd> subcommands
      muddle help categories     shows command names sorted by category
      muddle help aliases        says which commands have more than one name

    <switch> may be:

        -p[ager] <pager>    to specify a pager through which the help will be piped.
                            The default is $PAGER (if set) or else 'more'.
        -nop[ager]          don't use a pager, just print the help out.
    """

    command_line_help = """\
    Usage:

      muddle [<options>] <command> [<arg> ...]

    Available <options> are:

      --help, -h, -?      This help text
      --tree <dir>        Use the muddle build tree at <dir>
      --just-print, -n    Just print what muddle would have done. For commands
                          that 'do something', just print out the labels for
                          which that action would be performed. For commands
                          that "enquire" (or "find out") something, this switch
                          is ignored.

    If you don't give --tree, muddle will traverse directories up to the root to
    try and find a .muddle directory, which signifies the top of the build tree.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.print_help(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.print_help(args)

    def print_help(self, args):
        pager = os.environ.get('PAGER', 'more')
        if args:
            if args[0] in ('-p', '-pager'):
                pager = args[1]
                args = args[2:]
            elif args[0] in ('-nop', '-nopager'):
                pager = None
                args = args[1:]

        help_text = self.get_help(args)
        utils.page_text(pager, help_text)

    def get_help(self, args):
        """Return help for args, or a summary of all commands.
        """
        if not args:
            return self.help_list()

        if args[0] == "_all":
            return self.help_all()   # and ignore the rest of the command line

        if args[0] == "aliases":
            return self.help_aliases()

        if args[0] == "categories":
            return self.help_categories()

        if len(args) == 1:
            cmd = args[0]
            try:
                v = g_command_dict[cmd]
                if v is None:
                    keys = g_subcommand_dict[cmd].keys()
                    keys.sort()
                    keys_text = ", ".join(keys)
                    return utils.wrap("Subcommands of '%s' are: %s"%(cmd,keys_text),
                                      # I'd like to do this, but it's not in Python 2.6.5
                                      #break_on_hyphens=False,
                                      subsequent_indent='              ')
                else:
                    return "%s\n%s"%(cmd, v().help())
            except KeyError:
                return "There is no muddle command '%s'"%cmd
        elif len(args) == 2:
            cmd = args[0]
            subcmd = args[1]
            try:
                sub_dict = g_subcommand_dict[cmd]
            except KeyError:
                if cmd in g_command_dict:
                    return "Muddle command '%s' does not take a subcommand"%cmd
                else:
                    return "There is no muddle command '%s %s'"%(cmd, subcmd)

            if subcmd == "_all":
                return self.help_subcmd_all(cmd, sub_dict)

            try:
                v = sub_dict[subcmd]
                return "%s %s\n%s"%(cmd, subcmd, v().help())
            except KeyError:
                return "There is no muddle command '%s %s'"%(cmd, subcmd)
        else:
            return "There is no muddle command '%s'"%' '.join(args)
        result_array = []
        for cmd in args:
            try:
                v = g_command_dict[cmd]
                result_array.append("%s\n%s"%(cmd, v().help()))
            except KeyError:
                result_array.append("There is no muddle command '%s'\n"%cmd)

        return "\n".join(result_array)

    def help_list(self):
        """
        Return a list of all commands
        """
        result_array = []
        result_array.append(textwrap.dedent(Help.command_line_help))
        result_array.append(textwrap.dedent(Help.__doc__))
        result_array.append("\n")

        # Use the entire set of command names, including any aliases
        keys = g_command_dict.keys()
        keys.sort()
        keys_text = ", ".join(keys)

        result_array.append(utils.wrap('Commands are: %s'%keys_text,
                                       # I'd like to do this, but it's not in Python 2.6.5
                                       #break_on_hyphens=False,
                                       subsequent_indent='              '))

        # XXX Temporarily
        result_array.append("\n\n"+utils.wrap("Please note that 'muddle pull' is "
            "preferred to 'muddle fetch' and muddle update', which are deprecated."))
        # XXX Temporarily

        return "".join(result_array)

    def help_categories(self):
        result_array = []
        result_array.append("Commands by category:\n")

        categories_dict = g_command_categories
        categories_list = g_command_categories_in_order

        maxlen = len(max(categories_list, key=len)) +1  # +1 for a colon
        indent = ' '*(maxlen+3)

        for name in categories_list:
            cmd_list = categories_dict[name]
            cmd_list.sort()
            line = "  %-*s %s"%(maxlen, '%s:'%name, ' '.join(cmd_list))
            result_array.append(utils.wrap(line, subsequent_indent=indent))

        return "\n".join(result_array)

    def help_all(self):
        """
        Return help for all commands
        """
        result_array = []
        result_array.append("Commands:\n")

        cmd_list = []

        # First, all the main command names (without any aliases)
        for name in g_command_names:
            v = g_command_dict[name]
            cmd_list.append((name, v()))

        # Then, all the subcommands (ditto)
        for main, sub in g_subcommand_names:
            v = g_subcommand_dict[main][sub]
            cmd_list.append(('%s %s'%(main, sub), v()))

        cmd_list.sort()

        for name, obj in cmd_list:
            result_array.append("%s\n%s"%(name, v().help()))

        return "\n".join(result_array)

    def help_subcmd_all(self, cmd_name):
        """
        Return help for all commands in this dictionary
        """
        result_array = []
        result_array.append("Subcommands for '%s' are:\n"%cmd_name)

        keys = g_command_dict.keys()
        keys.sort()

        for name in keys:
            v = g_command_dict[name]
            result_array.append('%s\n%s'%(name, v().help()))

        return "\n".join(result_array)

    def help_aliases(self):
        """
        Return a list of all commands with aliases
        """
        result_array = []
        result_array.append("Commands aliases are:\n")

        aliases = g_command_aliases

        keys = aliases.keys()
        keys.sort()

        for alias in keys:
            result_array.append("  %-10s  %s"%(alias, aliases[alias]))

        aliases = g_subcommand_aliases
        if aliases:
            result_array.append("\nSubcommand aliases are:\n")

            main_keys = aliases.keys()
            main_keys.sort()
            for cmd in main_keys:
                sub_keys = aliases[cmd].keys()
                sub_keys.sort()
                for alias in sub_keys:
                    result_array.append("  %-20s %s"%("%s %s"%(cmd, alias),
                                                            "%s %s"%(cmd, aliases[cmd][alias])))

        return "\n".join(result_array)

@command('root', CAT_QUERY)
class Root(Command):
    """
    :Syntax: root

    Display the root directory we reckon you're in.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        print "%s"%(builder.invocation.db.root_path)
        
    def without_build_tree(self, muddle_binary, root_path, args):
        print "<uninitialized> %s"%(root_path)


@command('init', CAT_INIT)
class Init(Command):
    """
    :Syntax: init <repository> <build_description>

    Initialise a new build tree with a given repository and build description.
    We check out the build description but don't actually build.

    For instance::

      $ cd /somewhere/convenient
      $ muddle init  file+file:///somewhere/else/examples/d  builds/01.py

    This initialises a muddle build tree with::

      file+file:///somewhere/else/examples/d

    as its repository and a build description of "builds/01.py". The build tree
    is set up in the current directory. Traditionally, that should have been
    empty before doing ``muddle init``.

    The astute will notice that you haven't told muddle which actual repository
    the build description is in - you've only told it where the repository root
    is and where the build description file is.

    Muddle assumes that builds/01.py means repository
    "file+file:///somewhere/else/examples/d/builds" and file "01.py" therein.

    Note: if you find yourself trying to ``muddle init`` a subdomain, don't.
    Instead, add the subdomain to the current build description, and check it
    out that way.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        raise GiveUp("Can't initialise a build tree " 
                    "when one already exists (%s)"%builder.invocation.db.root_path)
    
    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Initialise a build tree.
        """
        if len(args) != 2:
            raise GiveUp(self.__doc__)

        repo = args[0]
        build = args[1]

        print "Initialising build tree in %s "%root_path
        print "Repository: %s"%repo
        print "Build description: %s"%build

        if self.no_op():
            return

        db = Database(root_path)
        db.setup(repo, build)

        print
        print "Checking out build description .. \n"
        mechanics.load_builder(root_path, muddle_binary)

        print "Done.\n"


@command('bootstrap', CAT_INIT)
class Bootstrap(Command):
    """
    :Syntax: bootstrap [-subdomain] <repo> <build_name>

    Create a new build tree, from scratch, in the current directory.

    * <repo> should be the root URL for the repository which you will be using
      as the default remote location. It is assumed that it will contain a
      'builds' and a 'versions' repository/subdirectory/whatever (this depends
      a bit on version control system being used).

      <repo> should be the same value that you would give to the 'init'
      command, if that was being used instead.

    * <build_name> is the name for the build. This should be a simple string,
      usable as a filename. It is strongly recommended that it contain only
      alphanumerics, underline, hyphen and dot (or period). Ideally it should
      be a meaningful (but not too long) description of the build.

    For instance::

      $ cd /somewhere/convenient
      $ muddle bootstrap git+http://example.com/fred/ build-27

    You will end up with a build tree of the form::

      .muddle/
          RootRepository      -- containing "git+http://example/com/fred/"
          Description         -- containing "builds/01.py"
          VersionsRepository  -- containing "git+http://example/com/fred/versions/"
      src/
          builds/
              .git/           -- assuming "http://example/com/fred/builds/"
              01.py           -- wth a bare minimum of content
      versions/
              .git/           -- assuming "http://example/com/fred/versions/"

    Note that 'src/builds/01.py' will have been *added* to the VCS (locally),
    but will not have been committed (this may change in a future release).

    Also, muddle cannot currently set up the VCS support for Subversion in the
    subdirectories.

    If you try to do this in a directory that is itself within an existing
    build tree (i.e., in some parent directory there is a ``.muddle``
    directory), then it will normally fail because you are trying to create a
    build within an existing build. If you are actually doing this because you
    are bootstrapping a subdomain, then specify the ``-subdomain`` switch.

    Note that this command will never bootstrap a new build tree in the same
    directory as an existing ``.muddle`` directory.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        if args[0] != '-subdomain':
            raise GiveUp("Can't bootstrap a build tree when one already"
                               " exists (%s)\nTry using '-bootstrap' if you"
                               " want to bootstrap a subdomain"%builder.invocation.db.root_path)
        args = args[1:]

        if os.path.exists('.muddle'):
            raise GiveUp("Even with '-subdomain', can't bootstrap a build"
                               " tree in the same directory as an existing"
                               " tree (found .muddle)")

        self.bootstrap(current_dir, args)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Bootstrap a build tree.
        """

        if args[0] == '-subdomain':
            print 'You are not currently within a build tree. "-subdomain" ignored'
            args = args[1:]

        self.bootstrap(root_path, args)

    def bootstrap(self, root_path, args):
        if len(args) != 2:
            raise GiveUp(self.__doc__)

        repo = args[0]
        build_name = args[1]

        build_desc_filename = "01.py"
        build_desc = "builds/%s"%build_desc_filename
        build_dir = os.path.join("src","builds")

        print "Bootstrapping build tree in %s "%root_path
        print "Repository: %s"%repo
        print "Build description: %s"%build_desc

        if self.no_op():
            return

        print
        print "Setting up database"
        db = Database(root_path)
        db.setup(repo, build_desc, versions_repo=os.path.join(repo,"versions"))

        print "Setting up build description"
        build_desc_text = '''\
                             #! /usr/bin/env python
                             """Muddle build description for {name}
                             """

                             def describe_to(builder):
                                 builder.build_name = '{name}'
                             '''.format(name=build_name)
        with utils.NewDirectory(build_dir):
            with open(build_desc_filename, "w") as fd:
                fd.write(textwrap.dedent(build_desc_text))

            # TODO: (a) do this properly and (b) do it for other VCS as necessary
            vcs_name, just_url = version_control.split_vcs_url(repo)
            if vcs_name == 'git':
                print 'Hack for git: ignore .pyc files in src/builds'
                with open('.gitignore', "w") as fd:
                    fd.write('*.pyc\n')

            if vcs_name != 'svn':
                print 'Adding build description to VCS'
                version_control.vcs_init_directory(vcs_name, ["01.py"])
                if vcs_name == 'git':
                    version_control.vcs_init_directory(vcs_name, [".gitignore"])

        print 'Telling muddle the build description is checked out'
        db.set_tag(Label.from_string('checkout:builds/checked_out'))

        print 'Setting up versions directory'
        with utils.NewDirectory("versions"):
            # We shan't try to do anything more (than create the directory) for
            # subversion, firstly because the versions repository is not (yet)
            # defined (because we're using SVN), and secondly because it may
            # mean doing an import, or somesuch, which we don't have a
            # "general" mechanism for.
            if vcs_name != 'svn':
                print 'Adding versions directory to VCS'
                version_control.vcs_init_directory(vcs_name)

        print "Done.\n"

@command('vcs', CAT_QUERY)
class ListVCS(Command):
    """
    :Syntax: vcs

    List the version control systems supported by this version of muddle,
    together with their VCS specifiers.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_command()

    def without_build_tree(self, muddle_binary, root_path, args):
        self.do_command()

    def do_command(self):
        str_list = [ ]
        str_list.append("Available version control systems:\n\n")
        str_list.append(version_control.list_registered())

        str = "".join(str_list)
        print str
        return 0

@command('dependencies', CAT_QUERY, ['depend', 'depends'])
class Depend(Command):
    """
    :Syntax: depend <what>
    :or:     depend <what> <label>

    Print the current dependency sets. Not specifying a label is the same as
    specifying "_all".

    In order to show all dependency sets, even those where a given label does
    not actually depend on anything, <what> can be:

    * system       - Print synthetic dependencies produced by the system
    * user         - Print dependencies entered by the build description
    * all          - Print all dependencies

    To show only those dependencies where there *is* a dependency, add '-short'
    (or '_short') to <what>, i.e.:

    * system-short - Print synthetic dependencies produced by the system
    * user-short   - Print dependencies entered by the build description
    * all-short    - Print all dependencies
    """

    def requires_build_tree(self):
        return True
    
    def without_build_tree(self, muddle_binary, root_path, args):
        raise GiveUp("Cannot run without a build tree")

    def with_build_tree(self, builder, current_dir, args):
        if len(args) != 1 and len(args) != 2:
            print "Syntax: dependencies [system|user|all][-short] <label to match>"
            print self.__doc__
            return
        
        type = args[0]
        if len(args) == 2:
            label = Label.from_string(args[1])
        else:
            label = None

        show_sys = False
        show_user = False

        if type.endswith("-short") or type.endswith("_short"):
            # Show only those rules with a dependency
            ignore_empty = True
            type = type[:-len("-short")]
        else:
            # Show *all* rules, even those which don't depend on anything
            ignore_empty = False

        if type == "system":
            show_sys = True
        elif type == "user":
            show_user = True
        elif type == "all":
            show_sys = True
            show_user = True
        else:
            raise GiveUp("Bad dependency type: %s"%(type))

        
        print builder.invocation.ruleset.to_string(matchLabel = label, 
                                                   showSystem = show_sys, showUser = show_user,
                                                   ignore_empty = ignore_empty)

class QueryCommand(Command):
    """
    The base class for 'query' commands
    """

    def requires_build_tree(self):
        return True

    def get_label(self, builder, args):
        if len(args) != 1:
            raise GiveUp("Command '%s' needs a label"%(self.cmd_name))

        try:
            label = Label.from_string(args[0])
        except GiveUp as exc:
            raise GiveUp("%s\nIt should contain at least <type>:<name>/<tag>"%exc)

        if label.domain is None:
            default_domain = builder.get_default_domain()
            if default_domain:
                label = label.copy_with_domain(default_domain)

        return builder.invocation.apply_unifications(label)

    def get_switches(self, args, allowed_switches):
        """BEWARE: removes any switches found from 'args'
        """
        switches = []
        for arg in args:
            if arg in allowed_switches:
                switches.append(arg)
                args.remove(arg)
        return switches


@subcommand('query', 'checkouts', CAT_QUERY)
class QueryCheckouts(QueryCommand):
    """
    :Syntax: query checkouts [-j]

    Print a list of known checkouts.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        cos = builder.invocation.all_checkout_labels()
        a_list = list(cos)
        a_list.sort()
        out_list = []
        for lbl in a_list:
            if lbl.domain:
                out_list.append('(%s)%s'%(lbl.domain,lbl.name))
            else:
                out_list.append(lbl.name)
        if joined:
            print '%s'%" ".join(out_list)
        else:
            print '%s'%"\n".join(out_list)

@subcommand('query', 'checkout-dirs', CAT_QUERY)
class QueryCheckoutDirs(QueryCommand):
    """
    :Syntax: query checkout_dirs

    Print a list of the known checkouts and their checkout paths (relative
    to ``src/``)
    """

    def with_build_tree(self, builder, current_dir, args):
        builder.invocation.db.dump_checkout_paths()

@subcommand('query', 'domains', CAT_QUERY)
class QueryDomains(QueryCommand):
    """
    :Syntax: query domains [-j]

    Print a list of known domains.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        domains = builder.invocation.all_domains()
        a_list = list(domains)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'packages', CAT_QUERY)
class QueryPackages(QueryCommand):
    """
    :Syntax: query packages [-j]

    Print a list of known packages.

    Note that if there is a rule for "package:*{}/*" (for instance), then '*'
    will be included in the names returned.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        packages = builder.invocation.all_packages()
        a_list = list(packages)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'package-roles', CAT_QUERY)
class QueryPackageRoles(QueryCommand):
    """
    :Syntax: query packageroles [-j]

    Print a list of known packages (and their roles).

    Note that if there is a rule for "package:*{}/*" (for instance), then '*'
    will be included in the names returned.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        packages = builder.invocation.all_packages_with_roles()
        a_list = list(packages)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'deployments', CAT_QUERY)
class QueryDeployments(QueryCommand):
    """
    :Syntax: query deployments [-j]

    Print a list of known deployments.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        roles = builder.invocation.all_deployments()
        a_list = list(roles)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'roles', CAT_QUERY)
class QueryRoles(QueryCommand):
    """
    :Syntax: query roles [-j]

    Print a list of known roles.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False
        roles = builder.invocation.all_roles()
        a_list = list(roles)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'default-roles', CAT_QUERY)
class QueryDefaultRoles(QueryCommand):
    """
    :Syntax: query default-roles [-j]

    Print the list of default roles to be built.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False

        default_roles = builder.invocation.default_roles
        default_roles.sort()
        if joined:
            print '%s'%" ".join(default_roles)
        else:
            print '%s'%"\n".join(default_roles)

@subcommand('query', 'default-labels', CAT_QUERY)
class QueryDefaultLabels(QueryCommand):
    """
    :Syntax: query default-labels [-j]

    Print the list of default labels to be built. This should actually
    be a list of default deployments.

    With '-j', print them all on one line, separated by spaces.
    """

    def with_build_tree(self, builder, current_dir, args):
        switches = self.get_switches(args, ['-j'])
        if switches:
            joined = True
        else:
            joined = False

        default_labels = builder.invocation.default_labels
        default_labels.sort()
        l = []
        for label in default_labels:
            l.append(str(label))
        if joined:
            print '%s'%" ".join(l)
        else:
            print '%s'%"\n".join(l)

@subcommand('query', 'root', CAT_QUERY)
class QueryRoot(QueryCommand):
    """
    :Syntax: query root

    Print the root path and default domain
    """

    def with_build_tree(self, builder, current_dir, args):
        print "Root: %s"%builder.invocation.db.root_path
        print "Default domain: %s"%builder.get_default_domain()

@subcommand('query', 'name', CAT_QUERY)
class QueryName(QueryCommand):
    """
    :Syntax: query name

    Print the build name, as specified in the build description.  This
    prints just the name, so that one can use it in the shell - for
    instance in bash::

        export PROJECT_NAME=$(muddle query name)
    """

    def with_build_tree(self, builder, current_dir, args):
        print builder.build_name

@subcommand('query', 'needed-by', CAT_QUERY, ['deps'])     # it used to be 'deps'
class QueryDeps(QueryCommand):
    """
    :Syntax: query needed-by <label>

    Print what we need to build to build this label.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        to_build = depend.needed_to_build(builder.invocation.ruleset, label, useMatch = True)
        if to_build:
            print "Build order for %s .. "%label
            for rule in to_build:
                print rule.target
        else:
            print "Nothing else needs building to build %s"%label

@subcommand('query', 'dir', CAT_QUERY)
class QueryDir(QueryCommand):
    """
    :Syntax: query dir <label>

    Print a directory:
        
    * for checkout labels, the checkout directory
    * for package labels, the install directory
    * for deployment labels, the deployment directory
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)

        dir = None
        if label.type == utils.LabelType.Checkout:
            dir = builder.invocation.db.get_checkout_path(label)
        elif label.type == utils.LabelType.Package:
            dir = builder.invocation.package_install_path(label)
        elif label.type == utils.LabelType.Deployment:
            dir = builder.invocation.deploy_path(label.name,
                    domain=label.domain)

        if dir is not None:
            print dir
        else:
            print None

@subcommand('query', 'env', CAT_QUERY)
class QueryEnv(QueryCommand):
    """
    :Syntax: query env <label>

    Print the environment in which this label will be run.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        the_env = builder.invocation.effective_environment_for(label)
        print "Effective environment for %s .. "%label
        print the_env.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

@subcommand('query', 'all-env', CAT_QUERY, ['envs'])       # It used to be 'env'
class QueryEnvs(QueryCommand):
    """
    :Syntax: query all-env <label>

    Print a list of the environments that will be merged to create the
    resulting environment for this label.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        a_list = builder.invocation.list_environments_for(label)

        for (lvl, label, env) in a_list:
            script = env.get_setvars_script
            print "-- %s [ %d ] --\n%s\n"%(label, lvl,
                                           script(builder, label,
                                                  env_store.EnvLanguage.Sh))
        print "---"

@subcommand('query', 'inst-details', CAT_QUERY)
class QueryInstDetails(QueryCommand):
    """
    :Syntax: query inst-details <label>

    Print the list of actual instructions for this labe, in the order in which
    they will be applied.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        loaded = builder.load_instructions(label)
        for (l, f, i) in loaded:
            print " --- Label %s , filename %s --- "%(l, f)
            print i.get_xml()
        print "-- Done --"

@subcommand('query', 'inst-files', CAT_QUERY, ['instructions'])    # It used to be 'instructions'
class QueryInstructions(QueryCommand):
    """
    :Syntax: query inst-files <label>

    Print the list of currently registered instruction files, in the order
    in which they will be applied.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        result = builder.invocation.db.scan_instructions(label)
        for (l, f) in result:
            print "Label: %s  Filename: %s"%(l,f)

@subcommand('query', 'match', CAT_QUERY)
class QueryMatch(QueryCommand):
    """
    :Syntax: query match <label>

    Print out any labels that match the label given. If the label is not
    wildcarded, this just reports if the label is known.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        wildcard_label = Label("*", "*", "*", "*", domain="*")
        all_rules = builder.invocation.ruleset.rules_for_target(wildcard_label)
        all_labels = set()
        for r in all_rules:
            all_labels.add(r.target)
        if label.is_definite():
            print list(all_labels)[0], '..', list(all_labels)[-1]
            if label in all_labels:
                print 'Label %s exists'%label
            else:
                print 'Label %s does not exist'%label
        else:
            found = False
            for item in all_labels:
                if label.match(item):
                    print 'Label %s matches %s'%(label, item)
                    found = True
            if not found:
                print 'Label %s does not match any labels'%label

@subcommand('query', 'make-env', CAT_QUERY, ['makeenv'])   # It used to be 'makeenv'
class QueryMakeEnv(QueryCommand):
    """
    :Syntax: query make-env <label>

    Print the environment in which "make" will be called for this label.
    Specifically, print what muddle adds to the environment (so it leaves
    out anything that was already in the environment when muddle was
    called).  Note that various things (lists of directories) only get set
    up when the directories actually exists - so, for instance,
    MUDDLE_INCLUDE_DIRS will only include directories for the packages
    depended on *that have already been built*. This means that this
    command shows the environment actually as would be used if one did
    ``muddle buildlabel``, but not necessarily as it would be for ``muddle
    build``, when the dependencies themselves would be built first. (It
    would be difficult to do otherwise, as the environment built is always
    as small as possible, and it is not until a package has been built that
    muddle can tell which directories will be present.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        rule_set = builder.invocation.ruleset.rules_for_target(label,
                                                               useTags=True,
                                                               useMatch=True)
        if len(rule_set) == 0:
            print 'No idea how to build %s'%label
            return
        elif len(rule_set) > 1:
            print 'Multiple rules for building %s'%label
            return

        # Amend the environment as if we were about to build
        old_env = os.environ
        try:
            os.environ = {}
            rule = list(rule_set)[0]
            builder._build_label_env(label, env_store)
            build_obj = rule.obj
            tmp = Label(utils.LabelType.Checkout, build_obj.co, domain=label.domain)
            co_path = builder.invocation.checkout_path(tmp)
            try:
                build_obj._amend_env(co_path)
            except AttributeError:
		# The kernel builder, for instance, does not have _amend_env
		# Of course, it also doesn't use any of the make.py classes...
                pass
            keys = os.environ.keys()
            keys.sort()
            for key in keys:
                print '%s=%s'%(key,os.environ[key])
        finally:
            os.environ = old_env

@subcommand('query', 'objdir', CAT_QUERY)
class QueryObjdir(QueryCommand):
    """
    :Syntax: query objdir <label>

    Print the object directory for a label. This is typically used to determine
    object directories for configure options in build Makefiles.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        print builder.invocation.package_obj_path(label)

@subcommand('query', 'precise-env', CAT_QUERY, ['preciseenv']) # It used to be 'preciseenv'
class QueryPreciseEnv(QueryCommand):
    """
    :Syntax: query precise-env <label>

    Print the environment pertaining to exactly this label (no fuzzy matches)
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        the_env = builder.invocation.get_environment_for(label)

        local_store = env_store.Store()
        builder.set_default_variables(label, local_store)
        local_store.merge(the_env)

        print "Environment for %s .. "%label
        print local_store.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

@subcommand('query', 'needs', CAT_QUERY, ['results'])      # It used to be 'results'
class QueryResults(QueryCommand):
    """
    :Syntax: query needs <label>

    Print what this label is required to build.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        result = depend.required_by(builder.invocation.ruleset, label)
        print "Labels which require %s to build .. "%label
        for lbl in result:
            print lbl

@subcommand('query', 'rules', CAT_QUERY, ['rule'])        # It used to be 'rule'
class QueryRules(QueryCommand):
    """
    :Syntax: query rules <label>

    Print the rules covering building this label.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        local_rule = builder.invocation.ruleset.rule_for_target(label)
        if (local_rule is None):
            print "No ruleset for %s"%label
        else:
            print "Rule set for %s .. "%label
            print local_rule

@subcommand('query', 'targets', CAT_QUERY)
class QueryTargets(QueryCommand):
    """
    :Syntax: query targets <label>

    Print the targets that would be built by an attempt to build this label.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        local_rules = builder.invocation.ruleset.targets_match(label, useMatch = True)
        print "Targets that match %s .. "%(label)
        for i in local_rules:
            print "%s"%i

@subcommand('query', 'unused', CAT_QUERY)
class QueryUnused(QueryCommand):
    """
    :Syntax: query unused [<label> [...]]

    Report on labels that are defined in the build description, but are not
    "used" by the targets. With no arguments, the targets are the default
    deployables. The argument "_all" means all available deployables (not
    just the defaults).  Otherwise, arguments are labels.
    """

    def with_build_tree(self, builder, current_dir, args):
        def all_deployables(builder):
            search_label = Label(utils.LabelType.Deployment,
                                 "*", "*",
                                 utils.LabelTag.Deployed,
                                 domain="*")
            all_rules = builder.invocation.ruleset.rules_for_target(search_label)
            deployables = set()
            for r in all_rules:
                deployables.add(r.target)
            return deployables

        targets = set()
        if args:
            for thing in args:
                if thing == '_all':
                    targets = targets.union(all_deployables(builder))
                else:
                    targets.add(Label.from_string(thing))
            print 'Finding labels unused by:'
        else:
            print 'Finding labels unused by the default deployables:'
            targets = set(builder.invocation.default_labels[:])

        targets = list(targets)
        targets.sort()
        for label in targets:
            print '    %s'%label

        all_needed_labels = set()
        for label in targets:
            print '>>> Processing %s'%label
            needed = depend.needed_to_build(builder.invocation.ruleset, label)
            for r in needed:
                all_needed_labels.add(r.target)

        print 'Number of "needed" labels is %d.'%len(all_needed_labels)

        search_label = Label("*", "*", "*", "*", domain="*")
        all_rules = builder.invocation.ruleset.rules_for_target(search_label)
        all_labels = set()
        for r in all_rules:
            all_labels.add(r.target)

        if len(all_labels) == 1:
            print 'There is just 1 label in total'
        else:
            print 'There are %d labels in total'%len(all_labels)

        all_not_needed = all_labels.difference(all_needed_labels)
        if len(all_not_needed) == 1:
            print 'There is thus 1 label that is not "needed"'
        else:
            print 'There are thus %d labels that are not "needed"'%len(all_not_needed)

        wildcarded = set()
        fetched     = set()
        merged     = set()
        missing    = set()
        num_transient = 0
        for l in all_not_needed:
            if l.transient:
                num_transient += 1
            elif not l.is_definite():
                wildcarded.add(l)
            elif l.tag == utils.LabelTag.Fetched:
                fetched.add(l)
            elif l.tag == utils.LabelTag.Merged:
                merged.add(l)
            else:
                missing.add(l)

        print '    Transient  %d'%num_transient
        print '    Wildcarded %d'%len(wildcarded)
        print '    /fetched   %d'%len(fetched)
        print '    /merged    %d'%len(merged)
        print '    Missing    %d'%len(missing)
        print 'Transient labels are (internally) generated by muddle, and can be ignored.'
        print 'We ignore wildcarded labels - this should be OK.'
        print 'We ignore /fetched and /merged checkout labels.'

        erk = all_needed_labels.difference(all_labels)
        if len(erk):
            print 'Number of "needed" labels that are not in "all" is %d'%len(erk)
            print 'This is worrying. The labels concerned are:'
            for l in erk:
                print '    %s'%l

        if len(missing) == 0:
            print '>>> Otherwise, there are no "unused" labels'
            return

        checkouts = {}
        packages = {}
        deployments = {}
        other = {}

        def label_key(l):
            key_parts = ['%s:'%l.type]
            if l.domain:
                key_parts.append('(%s)'%l.domain)
            key_parts.append(l.name)
            if l.role:
                key_parts.append('{%s}'%l.role)
            return ''.join(key_parts)

        def add_label(d, l):
            key = label_key(l)
            if key in d:
                d[key].append(l.tag)
            else:
                d[key] = [l.tag]

        for l in missing:
            if l.type == utils.LabelType.Checkout:
                add_label(checkouts,l)
            elif l.type == utils.LabelType.Package:
                add_label(packages,l)
            elif l.type == utils.LabelType.Deployment:
                add_label(deployments,l)
            else:
                add_label(other,l)

        def print_labels(d):
            keys = d.keys()
            keys.sort()
            for k in keys:
                tags = d[k]
                tags.sort()
                tags = ', '.join(tags)
                print '    %s/%s'%(k, tags)

        print '>>> Unused (missing) labels are thus:'
        print_labels(checkouts)
        print_labels(packages)
        print_labels(deployments)
        print_labels(other)

@subcommand('query', 'kernelver', CAT_QUERY)
class QueryKernelver(QueryCommand):
    """
    :Syntax: query kernelver <label>

    Determine the Linux kernel version.

    <label> should be the package label for the kernel version. This command
    looks in <obj>/obj/include/linux/version.h (where <obj> is the directory
    returned by "muddle query objdir <label>") for the LINUX_VERSION_CODE
    definition, and attempts to decode that.

    It prints out the Linux version, e.g.::

      muddle query kernelver package:linux_kernel{boot}/built
      2.6.29
    """

    def kernel_version(self, builder, kernel_pkg):
        """Given the label for the kernel, determine its version.
        """
        kernel_root = builder.invocation.package_obj_path(kernel_pkg)
        include_file = os.path.join(kernel_root, 'obj', 'include', 'linux', 'version.h')
        with open(include_file) as fd:
            line1 = fd.readline()
        parts = line1.split()
        if parts[0] != '#define' or parts[1] != 'LINUX_VERSION_CODE':
            raise GiveUp('Unable to determine kernel version: first line of %s is %s'%(include_file,
                         line1.strip()))
        version = int(parts[2])
        a = (version & 0xFF0000) >> 16
        b = (version & 0x00FF00) >> 8
        c = (version & 0x0000FF)
        return '%d.%d.%d'%(a,b,c)

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label(builder, args)
        print self.kernel_version(builder, label)


@command('runin', CAT_MISC)
class RunIn(Command):
    """
    :Syntax: runin <label> <command> [ ... ]

    Run the command "<command> [ ...]" in the directory corresponding to every
    label matching <label>.

    * Checkout labels are run in the directory corresponding to their checkout.
    * Package labels are run in the directory corresponding to their object files.
    * Deployment labels are run in the directory corresponding to their deployments.

    We only ever run the command in any directory once.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) < 2):
            print "Syntax: runin <label> <command> [ ... ]"
            print self.__doc__
            return

        labels = decode_labels(builder, args[0:1] )
        command = " ".join(args[1:])
        dirs_done = set()

        if self.no_op():
            print 'Run "%s" for: %s'%(command, label_list_to_string(labels))
            return

        for l in labels:
            matching = builder.invocation.ruleset.rules_for_target(l)

            for m in matching:
                lbl = m.target

                dir = None
                if (lbl.name == "*"):
                    # If it's a wildcard, don't bother.
                    continue

                if (lbl.type == utils.LabelType.Checkout):
                    dir = builder.invocation.checkout_path(lbl)
                elif (lbl.type == utils.LabelType.Package):
                    if (lbl.role == "*"): 
                        continue
                    dir = builder.invocation.package_obj_path(lbl)
                elif (lbl.type == utils.LabelType.Deployment):
                    dir = builder.invocation.deploy_path(lbl.name)
                    
                if (dir in dirs_done):
                    continue

                dirs_done.add(dir)
                if (os.path.exists(dir)):
                    # We want to run the command with our muddle environment
                    # Start with a copy of the "normal" environment
                    env = os.environ.copy()
                    # Add the default environment variables for building this label
                    local_store = env_store.Store()
                    builder.set_default_variables(lbl, local_store)
                    local_store.apply(env)
                    # Add anything the rest of the system has put in.
                    builder.invocation.setup_environment(lbl, env)

                    with utils.Directory(dir):
                        subprocess.call(command, shell=True, env=env,
                                        stdout=sys.stdout, stderr=subprocess.STDOUT)
                else:
                    print "! %s does not exist."%dir

@command('buildlabel', CAT_OTHER)
class BuildLabel(Command):
    """
    :Syntax: buildlabel <label> [ <label> ... ]

    Builds a set of specified labels, without all the defaulting and trying to
    guess what you mean that Build does.
    
    Mainly used internally to build defaults and the privileged half of
    instruction executions.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_labels(builder, args)

        if self.no_op():
            print 'Build:', label_list_to_string(labels)
            return

        build_labels(builder, labels)

@command('redeploy', CAT_DEPLOYMENT)
class Redeploy(Command):
    """
    :Syntax: redeploy <deployment> [<deployment> ... ]

    Remove all tags for the given deployments, erase their built directories
    and redeploy them.

    You can use cleandeploy to just clean the relevant deployments.

    If no deployments are given, we redeploy the default deployment list.
    If _all is given, we redeploy all deployments.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_deployment_arguments(builder, args, current_dir,
                                             utils.LabelTag.Deployed)

        if self.no_op():
            print 'Redeploy:', label_list_to_string(labels)
            return

        build_a_kill_b(builder, labels, utils.LabelTag.Clean,
                       utils.LabelTag.Deployed)
        build_labels(builder, labels)

@command('cleandeploy', CAT_DEPLOYMENT)
class Cleandeploy(Command):
    """
    :Syntax: cleandeploy <deployment> [<deployment> ... ]

    Remove all tags for the given deployments and erase their built
    directories.

    You can use cleandeploy to just clean the relevant deployments.

    If no deployments are given, we redeploy the default deployment list.
    If _all is given, we redeploy all deployments.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_deployment_arguments(builder, args, current_dir,
                                             utils.LabelTag.Clean)
        if (labels is None):
            raise GiveUp("No deployments specified or implied (this may well be a bug).")

        if self.no_op():
            print 'Cleandeploy:', label_list_to_string(labels)
            return

        build_a_kill_b(builder, labels, utils.LabelTag.Clean, utils.LabelTag.Deployed)

@command('deploy', CAT_DEPLOYMENT)
class Deploy(Command):
    """
    :Syntax: deploy <deployment> [<deployment> ... ]

    Build appropriate tags for deploying the given deployments.

    If no deployments are given we will use the default deployment list.
    If _all is given, we'll use all deployments.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_deployment_arguments(builder, args, current_dir,
                                             utils.LabelTag.Deployed)
        if self.no_op():
            print "Deploy: %s"%(label_list_to_string(labels))
            return

        build_labels(builder, labels)

@command('configure', CAT_PACKAGE)
class Configure(Command):
    """
    :Syntax: configure [ <package>{<role>} ... ]

    Configure a package. If the package name isn't given, we'll use the
    list of local packages derived from your current directory.

    If you're in a checkout directory, we'll configure every package
    which uses that checkout.

    _all is a special package meaning configure everything.

    You can specify all packages that depend on a particular checkout
    with "checkout:name".
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.Configured)
        build_labels(builder, labels)

@command('reconfigure', CAT_PACKAGE)
class Reconfigure(Command):
    """
    :Syntax: reconfigure [ <package>{<role>} ... ]

    Just like configure except that we clear any configured/built tags first
    (and their dependencies).
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.Configured)

        if self.no_op():
            print "Reconfigure: %s"%(label_list_to_string(labels))
            return

        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels,
                                          utils.LabelTag.Configured)
        kill_labels(builder, to_kill)
        build_labels(builder, labels)

@command('build', CAT_PACKAGE)
class Build(Command):
    """
    :Syntax: build [ <package>{<role>} ... ]
    
    Build a package. If the package name isn't given, we'll use the
    list of local packages derived from your current directory.

    Unqualified or inferred package names are built in every default
    role (there's a list in the build description).

    If you're in a checkout directory, we'll build every package
    which uses that checkout.

    _all is a special package meaning build everything.

    You can specify all packages that depend on a particular checkout
    with "checkout:name".
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.PostInstalled)

        if self.no_op():
            print "Build: %s"%(label_list_to_string(labels))
            return

        build_labels(builder, labels)

@command('rebuild', CAT_PACKAGE)
class Rebuild(Command):
    """
    :Syntax: rebuild [ <package>{<role>} ... ]

    Just like build except that we clear any built tags first 
    (and their dependencies).
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.PostInstalled)

        if self.no_op():
            print "Rebuild: %s"%(label_list_to_string(labels))
            return

        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, 
                                          utils.LabelTag.Built)
        kill_labels(builder, to_kill)
        build_labels(builder, labels)

@command('reinstall', CAT_PACKAGE)
class Reinstall(Command):
    """
    :Syntax: reinstall [ <package>{<role>} ... ]

    Reinstall the given packages (but don't rebuild them).
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.PostInstalled)

        if self.no_op():
            print "Reinstall: %s"%(label_list_to_string(labels))
            return

        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, 
                                          utils.LabelTag.Installed)
        kill_labels(builder, to_kill)
        build_labels(builder, labels)

@command('distrebuild', CAT_PACKAGE)
class Distrebuild(Command):
    """
    :Syntax: distrebuild [ <package>{<role>} ... ]

    A rebuild that does a distclean before attempting the rebuild.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.PostInstalled)

        if self.no_op():
            print "Distrebuild: %s"%(label_list_to_string(labels))
            return

        build_a_kill_b(builder, labels, utils.LabelTag.DistClean,
                       utils.LabelTag.PreConfig)
        build_labels(builder, labels)

@command('clean', CAT_PACKAGE)
class Clean(Command):
    """
    :Syntax: clean [ <package>{<role>} ... ]
    
    Just like build except that we clean packages rather than 
    building them. Subsequently, packages are regarded as having
    been configured but not build.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.Built)

        if self.no_op():
            print "Clean: %s"%(label_list_to_string(labels))
            return

        build_a_kill_b(builder, labels, utils.LabelTag.Clean, utils.LabelTag.Built)

@command('distclean', CAT_PACKAGE)
class DistClean(Command):
    """
    :Syntax: distclean [ <package>{<role>} ... ]

    Just like clean except that we reduce packages to non-preconfigured
    and invoke 'make distclean'.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.Built)

        if self.no_op():
            print "Distclean: %s"%(label_list_to_string(labels))
            return

        build_a_kill_b(builder, labels, utils.LabelTag.DistClean, utils.LabelTag.PreConfig)

@command('instruct', CAT_PACKAGE)
class Instruct(Command):
    """
    :Syntax: instruct <package>{<role>} <instruction-file>
    :or:     instruct (<domain>)<package>{<role>} <instruction-file>

    Sets the instruction file for the given package name and role to 
    the file specified in instruction-file. The role must be explicitly
    given as it's considered more likely that bugs will be introduced by
    the assumption of default roles than they are likely to prove useful.
    
    This command is typically issued by 'make install' for a package, as::

       $(MUDDLE_INSTRUCT) <instruction-file>
    
    If you don't specify an instruction file, we will unregister instructions
    for this package and role.

    If you want to clear all instructions, you'll have to edit the muddle
    database directly - this leaves the database in an inconsistent state -
    there's no guarantee that the instruction files will ever be rebuilt
    correctly - so it is not a command.

    You can list instruction files and their ordering with the query command.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) != 2 and len(args) != 1):
            print "Syntax: instruct [pkg{role}] <[instruction-file]>"
            print self.__doc__
            return

        arg = args[0]
        filename = None
        ifile = None

        # Validate this first
        label = decode_single_package_label(builder, arg, utils.LabelTag.PreConfig)

        if label.role is None or label.role == '*':
            raise GiveUp("instruct takes precisely one package{role} pair "
                                "and the role must be explicit")


        if (len(args) == 2):
            filename = args[1]

            if (not os.path.exists(filename)):
                raise GiveUp("Attempt to register instructions in " 
                                    "%s: file does not exist"%filename)

            # Try loading it.
            ifile = InstructionFile(filename, instr.factory)
            ifile.get()

            # If we got here, it's obviously OK

        if self.no_op():
            if filename:
                print "Register instructions for %s from %s"%(str(label), filename)
            else:
                print "Unregister instructions for %s"%label
            return

        # Last, but not least, do the instruction ..
        builder.instruct(label.name, label.role, ifile, domain=label.domain)

@command('commit', CAT_PACKAGE)
class Commit(Command):
    """
    :Syntax: commit <checkout> [ <checkout> ... ]

    Commit the specified checkouts to their local repositories.

    For a centralised VCS (e.g., Subversion) where the repository is remote,
    this will not do anything. See the update command.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/changes_committed" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.ChangesCommitted)

        name_selected_checkouts("Commit", checkouts);

        if self.no_op():
            return

        # Forcibly retract all the updated tags.
        for co in checkouts:
            builder.kill_label(co)
            builder.build_label(co)

@command('push', CAT_CHECKOUT)
class Push(Command):
    """
    :Syntax: push [-s[top]] <checkout> [ <checkout> ... ]

    Push the specified checkouts to their remote repositories.

    This updates the content of the remote repositories to match the local
    checkout.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/changes_pushed" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.

    If '-s' or '-stop' is given, then we'll stop at the first problem,
    otherwise an attempt will be made to process all the checkouts, and any
    problems will be re-reported at the end.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if len(args) and args[0] in ('-s', '-stop'):
            stop_on_problem = True
        else:
            stop_on_problem = False

        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.ChangesPushed)

        name_selected_checkouts("Push", checkouts)

        if self.no_op():
            return


        problems = []

        for co in checkouts:
            try:
                builder.invocation.db.clear_tag(co)
                builder.build_label(co)
            except GiveUp as e:
                if stop_on_problem:
                    raise
                else:
                    print e
                    problems.append(e)

        if problems:
            print '\nThe following problems occurred:\n'
            for e in problems:
                print str(e).rstrip()
                print

@command('pull', CAT_CHECKOUT, ['fetch', 'update'])   # we want to settle on one command
class Pull(Command):
    """
    :Syntax: pull [-s[top]] <checkout> [ <checkout> ... ]

    Pull the specified checkouts from their remote repositories. Any problems
    will be (re)reported at the end.

    For each checkout named, retrieve changes from the corresponding remote
    repository (as described by the build description) and apply them (to
    the checkout), but *not* if a merge would be required.

        (For a VCS such as git, this actually means "not if a user-assisted
        merge would be required - i.e., fast-forwards will be done.)

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/fetched" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.

    Normally, 'muddle pull' will attempt to pull all the chosen checkouts,
    re-reporting any problems at the end. If '-s' or '-stop' is given, then
    it will instead stop at the first problem.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):

        if len(args) and args[0] in ('-s', '-stop'):
            stop_on_problem = True
        else:
            stop_on_problem = False

        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.Fetched)

        name_selected_checkouts("Fetch", checkouts)

        if self.no_op():
            return

        problems = []
        not_needed  = []

        for co in checkouts:
            try:
                # First clear the 'fetched' tag
                builder.invocation.db.clear_tag(co)
                # And then build it again
                builder.build_label(co)
            except Unsupported as e:
                print e
                not_needed.append(e)
            except GiveUp as e:
                if stop_on_problem:
                    raise
                else:
                    print e
                    problems.append(e)

        if not_needed:
            print '\nThe following pulls were not needed:\n'
            for e in problems:
                print str(e).rstrip()
                print

        if problems:
            print '\nThe following problems occurred:\n'
            for e in problems:
                print str(e).rstrip()
                print

@command('merge', CAT_CHECKOUT)
class Merge(Command):
    """
    :Syntax: merge [-s[top]] <checkout> [ <checkout> ... ]

    Merge the specified checkouts from their remote repositories.

    For each checkout named, retrieve changes from the corresponding remote
    repository (as described by the build description) and merge them (into
    the checkout). The merge process is handled in a VCS specific manner,
    as each checkout is dealt with.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/merged" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.

    If '-s' or '-stop' is given, then we'll stop at the first problem,
    otherwise an attempt will be made to process all the checkouts, and any
    problems will be re-reported at the end.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):

        if len(args) and args[0] in ('-s', '-stop'):
            stop_on_problem = True
        else:
            stop_on_problem = False

        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.Merged)

        name_selected_checkouts("Merge", checkouts)

        if (self.no_op()):
            return

        problems = []

        for co in checkouts:
            try:
                # First clear the 'merged' tag
                builder.invocation.db.clear_tag(co)
                # And then build it again
                builder.build_label(co)
            except GiveUp as e:
                if stop_on_problem:
                    raise
                else:
                    print e
                    problems.append(e)
        if problems:
            print '\nThe following problems occurred:\n'
            for e in problems:
                print str(e).rstrip()
                print

@command('status', CAT_CHECKOUT)
class Status(Command):
    """
    :Syntax: status [-v] <checkout> [ <checkout> ... ]

    Report on the status of checkouts that need attention.

    If '-v' is given, report each checkout label as it is checked (allowing
    a sense of progress if there are many bazaar checkouts, for instance).

    Runs the equivalent of ``git status`` or ``bzr status`` on each repository,
    and tries to only report those which have significant status.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.

        Note: For subversion, the (remote) repository is queried,
        which may be slow.

    Be aware that "muddle status" will report on the currently checked out
    checkouts. "muddle status _all" will (attempt to) report on *all* the
    checkouts described by the build, even if they have not yet been checked
    out. This will fail on the first checkout directory it can't "cd" into
    (i.e., the first checkout that isn't there yet).
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):

        verbose = False
        if args and args[0] == '-v':
            args = args[1:]
            verbose = True

        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.Fetched)

        name_selected_checkouts("Status for", checkouts)

        if self.no_op():
            return

        something_needs_doing = False
        for co in checkouts:
            rule = builder.invocation.ruleset.rule_for_target(co)
            try:
                vcs = rule.obj.vcs
            except AttributeError:
                print "Rule for label '%s' has no VCS - cannot find its status"%co
                continue
            text = vcs.status(verbose)
            if text:
                print text
                something_needs_doing = True
        if not something_needs_doing:
            print 'All checkouts seemed clean'

@command('reparent', CAT_CHECKOUT)
class Reparent(Command):
    """
    :Syntax: reparent [-f[orce]] <checkout> [ <checkout> ... ]

    Re-associate the specified checkouts with their remote repositories.

    Some distributed VCSs (notably, Bazaar) can "forget" the remote repository
    for a checkout. In Bazaar, this typically means not remembering the
    "parent" repository, and thus not being able to pull. It appears to be
    possible to end up in this situation if network disconnection happens in an
    inopportune manner.

    This command attempts to reassociate each checkout to the remote repository
    as named in the muddle build description. If '-force' is given, then this
    will be done even if the remote repository is already known, otherwise it
    will only be done if it is necessary.

        For Bazaar: Reads and (maybe) edits .bzr/branch/branch.conf.

        * If "parent_branch" is unset, sets it.
        * With '-force', sets "parent_branch" regardless, and also unsets
          "push_branch".

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):

        if args and args[0] in ('-f', '-force'):
            args = args[1:]
            force = True
        else:
            force = False

        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.Fetched)

        name_selected_checkouts("Reparent", checkouts)

        if (self.no_op()):
            return

        for co in checkouts:
            rule = builder.invocation.ruleset.rule_for_target(co)
            try:
                vcs = rule.obj.vcs
            except AttributeError:
                print "Rule for label '%s' has no VCS - cannot reparent, ignored"%co
                continue
            vcs.reparent(force=force, verbose=True)

@command('removed', CAT_CHECKOUT)
class Removed(Command):
    """
    :Syntax: removed <checkout> [ <checkout> ... ]

    Signal to muddle that the given checkouts have been removed and will
    need to be checked out again before they can be used.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.CheckedOut)

        name_selected_checkouts("Remove", checkouts)

        if (self.no_op()):
            return

        for c in checkouts:
            builder.kill_label(c)

@command('unimport', CAT_CHECKOUT)
class Unimport(Command):
    """
    :Syntax: unimport <checkout> [ <checkout> ... ]

    Assert that the given checkouts haven't been checked out and must therefore
    be checked out.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.CheckedOut)

        name_selected_checkouts("Unimport", checkouts)

        if (self.no_op()):
            return

        for c in checkouts:
            builder.invocation.db.clear_tag(c)

@command('import', CAT_CHECKOUT)
class Import(Command):
    """
    :Syntax: import <checkout> [ <checkout> ... ]

    Assert that the given checkout (which may be the builds checkout) has
    been checked out. This is mainly used when you've just written a package
    you plan to commit to the central repository - muddle obviously can't check
    it out because the repository doesn't exist yet, but you probably want to
    add it to the build description for testing (and in fact you may want to
    commit it with muddle push). For convenience in the expected use case, it
    goes on to prime the relevant VCS module (by way of 'muddle reparent') so
    it can be pushed once ready; this should be at worst harmless in all cases.

    This command is really just an wrapper to 'muddle assert' with the right
    magic label names, and to 'muddle reparent'.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.CheckedOut)

        name_selected_checkouts("Import", checkouts)

        if (self.no_op()):
            return

        for c in checkouts:
            builder.invocation.db.set_tag(c)
        # issue 143: Call reparent so the VCS is locked and loaded.
        rep = g_command_dict['reparent']() # should be Reparent but go via the dict just in case
        rep.set_options(self.options)
        rep.set_old_env(self.old_env)
        rep.with_build_tree(builder, current_dir, args)

@command('assert', CAT_OTHER)
class Assert(Command):
    """
    :Syntax: assert <label> [ <label> ... ]

    Assert the given labels. Mostly for use by experts and scripts.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) < 1):
            print "Syntax: assert [label.. ]"
            print __doc__
            return

        labels = decode_labels(builder, args)

        if self.no_op():
            print "Assert: %s"%(label_list_to_string(labels))
            return

        for l in labels:
            builder.invocation.db.set_tag(l)

@command('retract', CAT_OTHER)
class Retract(Command):
    """
    :Syntax: retract <label> [ <label> ... ]

    Retract the given labels and their consequents. 
    Mostly for use by experts and scripts.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if len(args) < 1 :
            print "Syntax: retract [label ... ]"
            print __doc__
            return

        labels = decode_labels(builder, args)
        if (self.no_op()):
            print "Retract: %s"%(label_list_to_string(labels))
            return

        for l in labels:
            builder.kill_label(l)

@command('changed', CAT_PACKAGE)
class Changed(Command):
    """
    :Syntax: changed <package> [ <package> ... ]

    Mark packages as having been changed so that they will later
    be rebuilt by anything that needs to. The usual package name
    guessing logic is used to guess the names of your packages if
    you don't provide them.
    
    Note that we don't reconfigure (or indeed clean) packages - 
    we just clear the tags asserting that they've been built.

    You can specify all packages that depend on a particular checkout
    with "checkout:name".
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_package_arguments(builder, args, current_dir,
                                      utils.LabelTag.Built)
        if (self.no_op()):
            print "Mark changed: %s"%(label_list_to_string(labels))
            return

        for l in labels:
            builder.kill_label(l)

@command('env', CAT_OTHER)
class Env(Command):
    """
    :Syntax: env <language> <mode> <name> <label> [ <label> ... ]

    Produce a setenv script in the requested language listing all the
    runtime environment variables bound to <label> (or the cumulation
    of the varibales for several labels).

    * <language> may be 'sh', 'c', or 'py'/'python'
    * <mode> may be 'build' (build time variables) or 'run' (run-time variables)
    * <name> is used in various ways depending upon the target language.
      It should be a legal name/symbol in the aforesaid target language (for
      instance, in C it will be uppercased and used as part of a macro name).
    * <label> should be the name of a package, in the normal manner, with or
      without a role. '_all' means all packages, as usual.

    So, for instance::

        $ muddle env sh run 'encoder_settings' encoder > encoder_vars.sh

    might produce a file ``encoder_vars.sh`` with the following content::

        # setenv script for encoder_settings
        # 2010-10-19 16:24:05

        export BUILD_SDK=y
        export MUDDLE_TARGET_LOCATION=/opt/encoder/sdk
        export PKG_CONFIG_PATH=$MUDDLE_TARGET_LOCATION/lib/pkgconfig:$PKG_CONFIG_PATH
        export PATH=$MUDDLE_TARGET_LOCATION/bin:$PATH
        export LD_LIBRARY_PATH=$MUDDLE_TARGET_LOCATION/lib:$LD_LIBRARY_PATH

        # End file.

    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self,builder, current_dir, args):
        if (len(args) < 3):
            raise GiveUp("Syntax: env [language] [build|run] [name] [label ... ]")

        lang = args[0]
        mode = args[1]
        name = args[2]

        if (mode == "build"):
            tag = utils.LabelTag.Built
        elif (mode == "run"):
            tag = utils.LabelTag.RuntimeEnv
        else:
            raise GiveUp("Mode '%s' is not understood - use build or run."%mode)

        labels = decode_package_arguments(builder, args[3:], current_dir, tag)
        print "Environment for labels %s"%(label_list_to_string(labels))

        env = env_store.Store()

        for lbl in labels:
            x_env = builder.invocation.effective_environment_for(lbl)
            env.merge(x_env)

            if (mode == "run"):
                # If we have a MUDDLE_TARGET_LOCATION, use it.
                if (not env.empty("MUDDLE_TARGET_LOCATION")):
                    env_store.add_install_dir_env(env, "MUDDLE_TARGET_LOCATION")

        if (lang == "sh"):
            script = env.get_setvars_script(builder, name, env_store.EnvLanguage.Sh)
        elif (lang == "py" or lang == "python"):
            script = env.get_setvars_script(builder, name, env_store.EnvLanguage.Python)
        elif (lang == "c"):
            script = env.get_setvars_script(builder, name, env_store.EnvLanguage.C)
        else:
            raise GiveUp("Language must be sh, py, python or c, not %s"%lang)

        print script

@command('uncheckout', CAT_CHECKOUT)
class UnCheckout(Command):
    """
    :Syntax: uncheckout <checkout> [ <checkout> ... ]

    Tells muddle that the given checkouts no longer exist in the src directory
    and should be checked out/cloned from version control again.

    The special <checkout> name _all means all checkouts.

    If no <checkouts> are given, we'll use those implied by your current
    location.

    This does not actually delete the checkout directory. If you try to do::

        muddle unckeckout fred
        muddle checkout   fred

    then you will probably get an error, as the checkout still exists, and the
    VCS will detect this. As it says, this is to tell muddle that the checkout
    has already been removed.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.CheckedOut)

        name_selected_checkouts("Uncheckout", checkouts)

        if (self.no_op()):
            return

        for co in checkouts:
            builder.kill_label(co)

@command('checkout', CAT_CHECKOUT)
class Checkout(Command):
    """
    :Syntax: checkout <checkout> [ <checkout> ... ]

    Checks out the given series of checkouts.

    That is, copies (clones/branches) the content of each checkout from its
    remote repository.

    'checkout _all' means checkout all checkouts.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        checkouts = decode_checkout_arguments(builder, args, current_dir,
                                              utils.LabelTag.CheckedOut)

        name_selected_checkouts("Checkout", checkouts)

        if (self.no_op()):
            return

        for co in checkouts:
            builder.build_label(co)

@command('copywithout', CAT_MISC)
class CopyWithout(Command):
    """
    :Syntax: copywithout [-f[orce]] <src-dir> <dst-dir> [ <without> ... ]

    Many VCSs use '.XXX' directories to hold metadata. When installing
    files in a makefile, it's often useful to have an operation which
    copies a hierarchy from one place to another without these dotfiles.

    This is that operation. We copy everything from the source directory,
    <src-dir>, into the target directory,  <dst-dir>, without copying anything
    which is in [ <without> ... ].  If you omit without, we just copy - this is
    a useful, working, version of 'cp -a'

    If you specify -f (or -force), then if a destination file cannot be
    overwritten because of its permissions, and attempt will be made to remove
    it, and then copy again. This is what 'cp' does for its '-f' flag.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_copy(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.do_copy(args)

    def do_copy(self, args):

        if args and args[0] in ('-f', '-force'):
            force = True
            args = args[1:]
        else:
            force = False

        if (len(args) < 2):
            raise GiveUp("Bad syntax for copywithout command")

        src_dir = args[0]
        dst_dir = args[1]
        without = args[2:]

        if (self.no_op()):
            print "Copy from: %s"%(src_dir)
            print "Copy to  : %s"%(dst_dir)
            print "Excluding: %s"%(" ".join(without))
            return

        utils.copy_without(src_dir, dst_dir, without, object_exactly=True,
                preserve=True, force=force)

@command('retry', CAT_OTHER)
class Retry(Command):
    """
    :Syntax: retry <label> [ <label> ... ]

    Removes just the labels in question and then tries to build them.
    Useful when you're messing about with package rebuild rules.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        labels = decode_labels(builder, args)
        if (self.no_op()):
            print "Retry: %s"%(label_list_to_string(labels))
            return

        print "Clear: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.invocation.db.clear_tag(l)

        print "Build: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.build_label(l)

@command('subst', CAT_MISC)
class Subst(Command):
    """
    :Syntax: subst <src_file> <xml_file> <dst_file>

    Substitute (with "${.. }") <src file> into <dst file> using data from
    the environment or from the given xml file.

    XML queries look a bit like XPath queries - "/elem/elem/elem..."
    An implicit "::text()" is appended so you get all the text in the specified
    element.

    You can escape a "${ .. }" by passing "$${ .. }"

    You can insert literals with "${" .. " }"

    Or call functions with "${fn: .. }". Available functions include:

    * "${val:(something)}" - Value of something as a query (env var or XPath)
    * "${ifeq:(a,b,c)}" - If eval(a)==eval(b), expand to eval(c)
    * "${ifneq:(a,b,c)}" - If eval(a)!=eval(b), expand to eval(c)
    * "${echo:(..)}" -  Evaluate all your parameters in turn.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_subst(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.do_subst(args)

    def do_subst(self, args):
        if len(args) != 3:
            raise GiveUp("Syntax: subst [src] [xml] [dst]")

        src = args[0]
        xml_file = args[1]
        dst = args[2]

        if self.no_op():
            print 'Substitute source file %s'%src
            print '       using data from %s'%xml_file
            print '            to produce %s'%dst
            return

        f = open(xml_file, "r")
        xml_doc = xml.dom.minidom.parse(f)
        f.close()

        subst.subst_file(src, dst, xml_doc, self.old_env)
        return 0

@subcommand('stamp', 'save', CAT_STAMP)
class StampSave(Command):
    """
    :Syntax: stamp save [-f[orce]|-h[ead]] [<filename>]

    Go through each checkout, and save its remote repository and current
    revision id/number to a file.

    This is intended to be enough information to allow reconstruction of the
    entire build tree, as-is.

    If a <filename> is specified, then output will be written to a file called
    either <filename>.stamp or <filename>.partial. If <filename> already ended
    in '.stamp' or '.partial', then the old extension will be removed before
    deciding on whether to use '.stamp' or '.partial'.

    If a <filename> is not specified, then a file called <sha1-hash>.stamp or
    <sha1-hash>.partial will be used, where <sha1-hash> is a hexstring
    representation of the hash of the content of the file.

    The '.partial' extension will be used if it was not possible to write a
    full stamp file (revisions could not be determined for all checkouts, and
    neither '-force' nor '-head' was specified). An attempt will be made to
    give useful information about what the problems are.

    If a file already exists with the name ultimately chosen, that file will
    be overwritten.

    If '-f' or '-force' is specified, then attempt to "force" a revision id,
    even if it is not necessarily correct. For instance, if a local working
    directory contains uncommitted changes, then ignore this and use the
    revision id of the committed data. If it is actually impossible to
    determine a sensible revision id, then use the revision specified by the
    build description (which defaults to HEAD). For really serious problems,
    this may refuse to guess a revision id, in which case the 'stamp save'
    process should stop with the relevant checkout.

      (Typical use of '-f' is expected to be when a 'stamp save' reports
      problems in particular checkouts, but inspection shows that these
      are artefacts that may be ignored, such as an executable built in
      the source directory.)

    If '-h' or '-head' is specified, then HEAD will be used for all checkouts.
    In this case, the repository specified in the build description is used,
    and the revision id and status of each checkout is not checked.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        force = False
        just_use_head = False
        filename = None

        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
                just_use_head = False
            elif word in ('-h', '-head'):
                just_use_head = True
                force = False
            elif word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'stamp save'"%word)
            elif filename is None:
                filename = word
            else:
                raise GiveUp("Unexpected argument '%s' for 'stamp save'"%word)

        if just_use_head:
            print 'Using HEAD for all checkouts'
        elif force:
            print 'Forcing original revision ids when necessary'

        if self.no_op():
            return

        stamp, problems = VersionStamp.from_builder(builder, force, just_use_head)

        working_filename = 'working.stamp'
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        final_name = self.decide_stamp_filename(hash, filename, problems)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

    def decide_stamp_filename(self, hash, basename=None, partial=False):
        """
        Return filename, given a SHA1 hash hexstring, and maybe a basename.

        If 'partial', then the returned filename will have extension '.partial',
        otherwise '.stamp'.

        If the basename is not given, then the main part of the filename will
        be <hash>.

        If the basename is given, then if it ends with '.stamp' or '.partial'
        then that will be removed before it is used.
        """
        if partial:
            extension = '.partial'
        else:
            extension = '.stamp'
        if not basename:
            return '%s%s'%(hash, extension)
        else:
            head, ext = os.path.splitext(basename)
            if ext in ('.stamp', '.partial'):
                return '%s%s'%(head, extension)
            else:
                return '%s%s'%(basename, extension)

@subcommand('stamp', 'version', CAT_STAMP)
class StampVersion(Command):
    """
    :Syntax: stamp version [-f[orce]]

    This is similar to "stamp save", but using a pre-determined stamp filename.

    Specifically, the stamp file written will be called:

        versions/<build_name>.stamp

    The "versions/" directory is at the build root (i.e., it is a sibling of
    the ".muddle/" and "src/" directories). If it does not exist, it will be
    created.

      If the VersionsRepository is set (in the .muddle/ directory), and it is
      a distributed VCS (e.g., git or bzr) then ``git init`` (or ``bzr init``,
      or the equivalent) will be done in the directory if necessary, and then
      the file will be added to the local working set in that directory.
      For subversion, the file adding will be done, but no attempt will be
      made to initialise the directory.

    <build_name> is the name of this build, as specified by the build
    description (by setting ``builder.build_name``). If the build description
    does not set the build name, then the name will be taken from the build
    description file name. You can use "muddle query name" to find the build
    name for a particular build.

    If a full stamp file cannot be written (i.e., if the result would have
    extension ".partial"), then the version stamp file will not be written.

    Note that '-f' is supported (although perhaps not recommended), but '-h' is
    not.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        force = False
        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
            elif word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'stamp version'"%word)
            else:
                raise GiveUp("Unexpected argument '%s' for 'stamp version'"%word)

        if force:
            print 'Forcing original revision ids when necessary'

        if self.no_op():
            return

        stamp, problems = VersionStamp.from_builder(builder, force,
                                                    just_use_head=False)

        if problems:
            print problems
            raise GiveUp('Problems prevent writing version stamp file')

        version_dir = os.path.join(builder.invocation.db.root_path, 'versions')
        if not os.path.exists(version_dir):
            print 'Creating directory %s'%version_dir
            os.mkdir(version_dir)

        working_filename = os.path.join(version_dir, '_temporary.stamp')
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        version_filename = "%s.stamp"%builder.build_name
        final_name = os.path.join(version_dir, version_filename)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

        db = builder.invocation.db
        versions_url = db.versions_repo.from_disc()
        if versions_url:
            with utils.Directory(version_dir):
                vcs_name, just_url = version_control.split_vcs_url(versions_url)
                if vcs_name:
                    print 'Adding version stamp file to VCS'
                    version_control.vcs_init_directory(vcs_name, [version_filename])

@subcommand('stamp', 'diff', CAT_STAMP)
class StampDiff(Command):
    """
    :Syntax: stamp diff [-u[nified]|-c[ontext]|-n|-h[tml]] <file1> <file2> [<output_file>]

    Compare two stamp files.

    The two (existing) stamp files named are compared. If <output_file> is
    given, then the output is written to it (overwriting any previous file of
    that name), otherwise output is to standard output.

    If '-u' is specified, then the output is a unified difference. This is the
    default.

    If '-c' is specified, then the output is a context difference. This uses a
    "before/after" style of presentation.

    If '-n' is specified, then the output is from "ndiff" - this is normally
    a more human-friendly set of differences, but outputs the parts of the files
    that match as well as those that do not.

    If '-h' is specified, then the output is an HTML page, displaying
    differences in two columns (with colours).
    """

    def requires_build_tree(self):
        return False

    def print_syntax(self):
        print ':Syntax: stamp diff [-u[nified]|-n|-h[tml]] <file1> <file2> [<output_file>]'

    def without_build_tree(self, muddle_binary, root_path, args):
        if not args:
            raise GiveUp("'stamp diff' needs two stamp files to compare")
        self.compare_stamp_files(args)

    def with_build_tree(self, builder, current_dir, args):
        if not args:
            raise GiveUp("'stamp diff' needs two stamp files to compare")
        self.compare_stamp_files(args)

    def compare_stamp_files(self, args):
        diff_style = 'unified'
        file1 = file2 = output_file = None
        while args:
            word = args[0]
            args = args[1:]
            if word in ('-u', '-unified'):
                diff_style = 'unified'
            elif word == '-n':
                diff_style = 'ndiff'
            elif word in ('-c', '-context'):
                diff_style = 'context'
            elif word in ('-h', '-html'):
                diff_style = 'html'
            elif word.startswith('-'):
                print "Unexpected switch '%s'"%word
                self.print_syntax()
                return 2
            else:
                if file1 is None:
                    file1 = word
                elif file2 is None:
                    file2 = word
                elif output_file is None:
                    output_file = word
                else:
                    print "Unexpected '%s'"%word
                    self.print_syntax()
                    return 2

        if self.no_op():
            print 'Comparing stamp files %s and %s'%(file1, file2)
            return

        self.diff(file1, file2, diff_style, output_file)

    def diff(self, file1, file2, diff_style='unified', output_file=None):
        """
        Output a comparison of file1 and file2 to html_file.
        """
        with open(file1) as fd1:
            file1_lines = fd1.readlines()
        with open(file2) as fd2:
            file2_lines = fd2.readlines()

        if diff_style == 'html':
            diff = difflib.HtmlDiff().make_file(file1_lines, file2_lines,
                                                file1, file2)
        elif diff_style == 'ndiff':
            diff = difflib.ndiff(file1_lines, file2_lines)
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            help = ["#First character indicates provenance:\n"
                    "# '-' only in %s of %s\n"%(file1, file1_date),
                    "# '+' only in %s of %s\n"%(file2, file2_date),
                    "# ' ' in both\n",
                    "# '?' pointers to intra-line differences\n"
                    "#---------------------------------------\n"]
            diff = help + list(diff)
        elif diff_style == 'context':
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.context_diff(file1_lines, file2_lines,
                                        file1, file2,
                                        file1_date, file2_date)
        else:
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.unified_diff(file1_lines, file2_lines,
                                        file1, file2,
                                        file1_date, file2_date)

        if output_file:
            with open(output_file,'w') as fd:
                fd.writelines(diff)
        else:
            sys.stdout.writelines(diff)

@subcommand('stamp', 'push', CAT_STAMP)
class StampPush(Command):
    """
    :Syntax: stamp push [<repository_url>]

    This performs a VCS "push" operation for the "versions/" directory. This
    assumes that the versions repository is defined in
    ``.muddle/VersionsRepository``.

    If a <repository_url> is given, then that is used as the remote repository
    for the push, and also saved as the "current" remote repository in
    ``.muddle/VersionsRepository``.

    (If the VCS being used is Subversion, then <repository> is ignored
    by the actual "push", but will still be used to update the
    VersionsRepository file. So be careful.)

    If a <repository_url> is not given, then the repository URL named
    in ``.muddle/VersionsRepository`` is used. If there is no repository
    specified there, then the operation will fail.

    'stamp push' does not (re)create a stamp file in the "versions/`"
    directory - use 'stamp version' to do that separately.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp push'"%' '.join(args))

        db = builder.invocation.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.versions_repo.from_disc()

        if not versions_url:
            raise GiveUp("Cannot push 'versions/' directory, as there is no repository specified\n"
                                "Check the contents of '.muddle/VersionsRepository',\n"
                                "or give a repository on the command line")

        versions_dir = os.path.join(db.root_path, "versions")
        if not os.path.exists(versions_dir):
            raise GiveUp("Cannot push 'versions/' directory, as it does not exist.\n"
                                "Have you done 'muddle stamp version'?")

        if self.no_op():
            print 'Push versions directory to', versions_url
            return

        with utils.Directory('versions'):
            version_control.vcs_push_directory(versions_url)

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.versions_repo.set(versions_url)
            db.versions_repo.commit()

@subcommand('stamp', 'pull', CAT_STAMP)
class StampPull(Command):
    """
    :Syntax: stamp pull [<repository_url>]

    This performs a VCS "pull" operation for the "versions/" directory. This
    assumes that the versions repository is defined in
    ``.muddle/VersionsRepository``.

    If a <repository_url> is given, then that is used as the remote repository
    for the pull, and also saved as the "current" remote repository in
    ``.muddle/VersionsRepository``.

    (If the VCS being used is Subversion, then <repository> is ignored by the
    actual "pull", but will still be used to update the VersionsRepository
    file. So be careful.)

    If a <repository_url> is not given, then the repository URL named
    in ``.muddle/VersionsRepository`` is used. If there is no repository
    specified there, then the operation will fail.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp pull'"%' '.join(args))

        db = builder.invocation.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.versions_repo.from_disc()

        if not versions_url:
            raise GiveUp("Cannot pull 'versions/' directory, as there is no repository specified\n"
                                "Check the contents of '.muddle/VersionsRepository',\n"
                                "or give a repository on the command line")

        versions_dir = os.path.join(db.root_path, "versions")

        if self.no_op():
            if os.path.exists(versions_dir):
                print 'Pull versions directory from', versions_url
            else:
                print 'Clone versions directory from', versions_url
            return

        if os.path.exists(versions_dir):
            with utils.Directory(versions_dir):
                version_control.vcs_fetch_directory(versions_url)
        else:
            print "'versions/' directory does not exist - cloning instead"
            with utils.Directory(db.root_path):
                # Make sure we always clone to a directory of the right name...
                version_control.vcs_get_directory(versions_url, "versions")

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.versions_repo.set(versions_url)
            db.versions_repo.commit()

@command('unstamp', CAT_STAMP)
class UnStamp(Command):
    """
    :Syntax: unstamp <file>
    :or:     unstamp <url>
    :or:     unstamp <vcs>+<url>
    :or:     unstamp <vcs>+<repo_url> <version_desc>

    The "unstamp" command reads the contents of a "stamp" file, as produced by
    the "muddle stamp" command, and:

    1. Retrieves each checkout mentioned
    2. Reconstructs the corresponding muddle directory structure
    3. Confirms that the muddle build description is compatible with
       the checkouts.


    The file may be specified as:

    * The local path to a stamp file.

      For instance::

          muddle stamp  thing.stamp
          mkdir /tmp/thing
          cp thing.stamp /tmp/thing
          cd /tmp/thing
          muddle unstamp  thing.stamp

    * The URL for a stamp file. In this case, the file will first be copied to
      the current directory.

      For instance::

          muddle unstamp  http://some.url/some/path/thing.stamp

      which would first copy "thing.stamp" to the current directory, and then
      use it. If the file already exists, it will be overwritten.

    * The "revision control specific" URL for a stamp file. This names the
      VCS to use as part of the URL - for instance::

          muddle unstamp  bzr+ssh://kynesim.co.uk/repo/thing.stamp

      This also copies the stamp file to the current directory before using it.
      Note that not all VCS mechanisms support this (at time of writing, muddle's
      git support does not). If the file already exists, it will be overwritten.

    * The "revision control specific" URL for a repository, and the path to
      the version stamp file therein.

      For instance::

          muddle unstamp  bzr+ssh://kynesim.co.uk/repo  versions/ProjectThing.stamp

      This is intended to act somewhat similarly to "muddle init", in that
      it will checkout::

          bzr+ssh://kynesim.co.uk/repo/versions

      and then unstamp the ProjectThing.stamp file therein.

    """

    def print_syntax(self):
        print """
    :Syntax: unstamp <file>
    :or:     unstamp <url>
    :or:     unstamp <vcs>+<url>
    :or:     unstamp <vcs>+<repo_url> <version_desc>

Try 'muddle help unstamp' for more information."""

    def requires_build_tree(self):
        return False

    def without_build_tree(self, muddle_binary, root_path, args):
        # Strongly assume the user wants us to work in the current directory
        current_dir = os.getcwd()

        # In an ideal world, we'd only be called if there really was no muddle
        # build tree. However, in practice, the top-level script may call us
        # because it can't find an *intact* build tree. So it's up to us to
        # know that we want to be a bit more careful...
        dir, domain = utils.find_root_and_domain(current_dir)
        if dir:
            print
            print 'Found a .muddle directory in %s'%dir
            if dir == current_dir:
                print '(which is the current directory)'
            else:
                print 'The current directory is     %s'%current_dir
            print
            got_src = os.path.exists(os.path.join(dir,'src'))
            got_dom = os.path.exists(os.path.join(dir,'domains'))
            if got_src or got_dom:
                extra = ', and also the '
                if got_src: extra += '"src/"'
                if got_src and got_dom: extra += ' and '
                if got_dom: extra += '"domains/"'
                if got_src and got_dom:
                    extra += ' directories '
                else:
                    extra += ' directory '
                extra += 'alongside it'
            else:
                extra = ''
            print utils.wrap('This presumably means that the current directory is'
                             ' inside a broken or partial build. Please fix this'
                             ' (e.g., by deleting the ".muddle/" directory%s)'
                             ' before retrying the "unstamp" command.'%extra)
            return 4

        if len(args) == 1:
            self.unstamp_from_file(muddle_binary, root_path, current_dir, args[0])
        elif len(args) == 2:
            self.unstamp_from_repo(muddle_binary, root_path, current_dir, args[0], args[1])
        else:
            self.print_syntax()
            return 2


    def unstamp_from_file(self, muddle_binary, root_path, current_dir, thing):
        """
        Unstamp from a file (local, over the network, or from a repository)
        """

        data = None

        # So what is our "thing"?
        vcs_name, just_url = version_control.split_vcs_url(thing)

        if vcs_name:
            print 'Retrieving %s'%thing
            data = version_control.vcs_get_file_data(thing)
            # We could do various things here, but it actually seems like
            # quite a good idea to store the data *as a file*, so the user
            # can do stuff with it, if necessary (and as an audit trail of
            # sorts)
            parts = urlparse(thing)
            path, filename = os.path.split(parts.path)
            print 'Saving data as %s'%filename
            with open(filename,'w') as fd:
                fd.write(data)
        elif os.path.exists(thing):
            filename = thing
        else:
            # Hmm - maybe a plain old URL
            parts = urlparse(thing)
            path, filename = os.path.split(parts.path)
            print 'Retrieving %s'%filename
            data = urllib.urlretrieve(thing, filename)

        if self.no_op():
            return

        stamp = VersionStamp.from_file(filename)

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               stamp.repository,
                                               stamp.description)

        self.restore_stamp(builder, root_path, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, stamp.checkouts, builder,
                                muddle_binary)

    def unstamp_from_repo(self, muddle_binary, root_path, current_dir, repo,
                          version_path):
        """
        Unstamp from a repository and version path.
        """

        version_dir, version_file = os.path.split(version_path)

        if not version_file:
            raise GiveUp("'unstamp <vcs+url> %s' does not end with"
                    " a filename"%version_path)

        # XXX I'm not entirely sure about this check - is it overkill?
        if os.path.splitext(version_file)[1] != '.stamp':
            raise GiveUp("Stamp file specified (%s) does not end"
                    " .stamp"%version_file)

        actual_url = '%s/%s'%(repo, version_dir)
        print 'Retrieving %s'%actual_url

        if self.no_op():
            return

        # Restore to the "versions" directory, regardless of the URL
        version_control.vcs_get_directory(actual_url, "versions")

        stamp = VersionStamp.from_file(os.path.join("versions", version_file))

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               stamp.repository,
                                               stamp.description,
                                               versions_repo=actual_url)

        self.restore_stamp(builder, root_path, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, stamp.checkouts, builder,
                                muddle_binary)

    def restore_stamp(self, builder, root_path, domains, checkouts):
        """
        Given the information from our stamp file, restore things.
        """
        for domain_name, domain_repo, domain_desc in domains:
            print "Adding domain %s"%domain_name

            domain_root_path = os.path.join(root_path, 'domains', domain_name)
            os.makedirs(domain_root_path)

            domain_builder = mechanics.minimal_build_tree(builder.muddle_binary,
                                                          domain_root_path,
                                                          domain_repo, domain_desc)

            # Tell the domain's builder that it *is* a domain
            domain_builder.invocation.mark_domain(domain_name)

        checkouts.sort()
        for name, repo, rev, rel, dir, domain, co_leaf, branch in checkouts:
            if domain:
                print "Unstamping checkout (%s)%s"%(domain,name)
            else:
                print "Unstamping checkout %s"%name
            # So try registering this as a normal build, in our nascent
            # build system
            label = Label(utils.LabelType.Checkout, name, domain=domain)
            if dir:
                builder.invocation.db.set_checkout_path(label, os.path.join(dir, co_leaf))
            else:
                builder.invocation.db.set_checkout_path(label, co_leaf)
            vcs_handler = version_control.vcs_handler_for(builder, label, co_leaf,  repo,
                                                          rev, rel, dir, branch)
            vcs = pkg.VcsCheckoutBuilder(name, vcs_handler)
            pkg.add_checkout_rules(builder.invocation.ruleset, label, vcs)

            # Then need to mimic "muddle checkout" for it
            label = Label(utils.LabelType.Checkout,
                          name, None, utils.LabelTag.CheckedOut,
                          domain=domain)
            builder.build_label(label, silent=False)

    def check_build(self, current_dir, checkouts, builder, muddle_binary):
        """
        Check that the build tree we now have on disk looks a bit like what we want...
        """
        # So reload as a "new" builder
        print
        print 'Checking that the build is restored correctly...'
        print
        (build_root, build_domain) = utils.find_root_and_domain(current_dir)

        b = mechanics.load_builder(build_root, muddle_binary, default_domain=build_domain)

        qr = QueryRoot()
        qr.with_build_tree(b, current_dir, None)

        qc = QueryCheckouts()
        qc.with_build_tree(b, current_dir, ["checkout:*/*"])

        # Check our checkout names match
        s_checkouts = set([name for name, repo, rev, rel, dir,
                           domain, co_leaf, branch in checkouts])
        # TODO: really should be using checkout labels, not names
        b_checkouts = b.invocation.all_checkouts()
        s_difference = s_checkouts.difference(b_checkouts)
        b_difference = b_checkouts.difference(s_checkouts)
        if s_difference or b_difference:
            print 'There is a mismatch between the checkouts in the stamp' \
                  ' file and those in the build'
            if s_difference:
                print 'Checkouts only in the stamp file:'
                for name in s_difference:
                    print '    %s'%name
            if b_difference:
                print 'Checkouts only in the build:'
                for name in b_difference:
                    print '    %s'%name
            return 4
        else:
            print
            print '...the checkouts present match those in the stamp file.'
            print 'The build looks as if it restored correctly.'

@command('whereami', CAT_QUERY, ['where'])
class Whereami(Command):
    """
    :Syntax: whereami [-detail]
    :or:     where [-detail]

    Looks at the current directory and tries to identify where it is
    in terms of the enclosing muddle build tree (if any). The result
    is output in the form::

        <type>: <name>[{<role>}]

    For instance::

        checkout directory: frobozz
        package object directory: kernel{type1}

    or even::

        You are here. Here is not in a muddle build tree.

    unless the '-detail' switch is given, in which case output suitable
    for parsing is output, of the form:

        <what> <label> <domain>

    i.e., a space-separated triple of items that don't contain whitespace.
    For instance::

        $ muddle where
        Checkout directory for checkout:screen-4.0.3/*
        $ muddle where -detail
        (Checkout, checkout:screen-4.0.3/*, None)
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):

        detail = False
        if args:
            if len(args) == 1 and args[0] == '-detail':
                detail = True
            else:
                print 'Syntax: whereami [-detail]'
                print '    or: where [-detail]'
                return

        r = builder.find_location_in_tree(current_dir)
        if r is None:
            raise utils.MuddleBug('Unable to determine location in the muddle build tree:\n'
                                  'Build tree is at  %s\n'
                                  'Current directory %s'%(builder.invocation.db.root_path,
                                                          current_dir))
        (what, label, domain) = r

        if detail:
            print '%s %s %s'%(utils.ReverseDirType[what], label, domain)
            return

        if what is None:
            raise utils.MuddleBug('Unable to determine location in the muddle build tree:\n'
                                  "'Directory type' returned as None")

        if what == utils.DirType.DomainRoot:
            print 'root of subdomain %s'%domain
        else:
            rv = "%s"%what
            if label:
                rv = '%s for %s'%(rv, label)
            elif domain:
                rv = '%s in subdomain %s'%(rv, domain)
            print rv

    def without_build_tree(self, muddle_binary, root_path, args):
        print "You are here. Here is not in a muddle build tree."

@command('doc', CAT_QUERY)
class Doc(Command):
    """
    :Syntax: doc [-d] <name>

    Looks up the documentation string for ``muddled.<name>`` and presents
    it, using the pydoc Python help mechanisms. Doesn't put "muddled." on
    the start of <name> if it is already there.

    For instance:

        muddle doc depend.Label

    With -d, just presents the symbols in <name>, omitting anything that starts
    with an underscore.

    NB: "muddle doc" uses the pydoc module, which will automatically page
    its output. This does not apply for "doc -d".
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.doc_for(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.doc_for(args)

    def doc_for(self, args):
        just_dir = False
        if len(args) == 1:
            what = args[0]
        elif len(args) == 2 and args[0] == '-d':
            what = args[1]
            just_dir = True
        else:
            print 'Syntax: doc [-d] <name>'
            return
        environment = {}

        # Allow 'muddle doc muddled' explicitly
        if what != 'muddled' and not what.startswith('muddled.'):
            what = 'muddled.%s'%what

        # We need a bit of trickery to cope with the fact that,
        # for instance, we cannot "import muddled" and then access
        # "muddled.deployments.cpio", but we can "import
        # muddled.deployments.cpio" directly.
        words = what.split('.')
        count = len(words)
        for idx in range(0, count):
            a = words[:idx+1]
            try:
                exec 'import %s; thing=%s'%('.'.join(a), what) in environment
                if just_dir:
                    d = dir(environment['thing'])
                    for item in d:
                        if item[0] != '_':
                            print '  %s'%item
                else:
                    pydoc.doc(environment['thing'])
                return
            except AttributeError:
                pass
            except ImportError as e:
                print 'ImportError: %s'%e
                break

        # Arguably, we should also try looking in muddled.XXX.<what>,
        # where XXX is one of ('checkouts', 'deployments', 'pkgs', 'vcs')
        # If we're going to do that sort of thing, then perhaps we should
        # precalculate all the things we're going to try, and then run
        # through them...
        # Pragmatically, also, if <what> starts with (for instance) "make.",
        # then we might assume that it should actually start with
        # "muddled.pkgs.make." - there must be other common examples of this...

        print 'Cannot find %s'%what

@command('test', CAT_OTHER)
class Test(Command):
    """
    :Syntax: test <label-fragment>

    This is a transient, temporary command. Do not expect it to stay.

    For testing label fragment parsing, and whether labels exist
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        for word in args:
            print 'As package:'
            label = Label.from_fragment(word,
                    default_type=utils.LabelType.Package,
                    default_role='*',
                    default_domain=builder.get_default_domain())
            print '  ', label
            print '  target  exists?', builder.invocation.target_label_exists(label)
            print
            print 'As checkout:'
            label = Label.from_fragment(word,
                    default_type=utils.LabelType.Checkout,
                    default_role=None,
                    default_domain=builder.get_default_domain())
            print '  ', label
            print '  checkout exists?', builder.invocation.checkout_label_exists(label)
            print '  target   exists?', builder.invocation.target_label_exists(label)

        print
        print 'As package args:'
        print label_list_to_string(decode_package_arguments(builder, args, current_dir, 'built'))

        print
        print 'As checkout args:'
        print label_list_to_string(decode_checkout_arguments(builder, args, current_dir, 'FRED'))

# -----------------------------------------------------------------------------
# Actions
# -----------------------------------------------------------------------------

def build_a_kill_b(builder, labels, build_this, kill_this):
    """
    For every label in labels, build the label formed by replacing
    tag in label with build_this and then kill the tag in label with
    kill_this.

    We have to interleave these operations so an error doesn't
    lead to too much or too little of a kill.
    """
    for lbl in labels:
        try:
            l_a = lbl.copy_with_tag(build_this)
            print "Building: %s .. "%(l_a)
            builder.build_label(l_a)
        except GiveUp, e:
            raise GiveUp("Can't build %s - %s"%(l_a, e))

        try:
            l_b = lbl.copy_with_tag(kill_this)
            print "Killing: %s .. "%(l_b)
            builder.kill_label(l_b)
        except GiveUp, e:
            raise GiveUp("Can't kill %s - %s"%(l_b, e))

def kill_labels(builder, to_kill):
    print "Killing %s "%(" ".join(map(str, to_kill)))

    try:
        for lbl in to_kill:
            builder.kill_label(lbl)
    except GiveUp, e:
        raise GiveUp("Can't kill %s - %s"%(str(lbl), e))

def build_labels(builder, to_build):
    print "Building %s "%(" ".join(map(str, to_build)))

    try:
        for lbl in to_build:
            builder.build_label(lbl)
    except GiveUp,e:
        raise GiveUp("Can't build %s - %s"%(str(lbl), e))

# -----------------------------------------------------------------------------
# Decode label or partial label arguments for particular purposes
# -----------------------------------------------------------------------------

def decode_checkout_arguments(builder, arglist, current_dir, required_tag=None):
    """
    TBD
    """
    result_list = []

    default_domain = builder.get_default_domain()

    if arglist:
        # Excellent!
        result_set = set()
        # Build up an initial list from the arguments given
        # Make sure we have a one-for-one correspondence between the input
        # list and the result
        initial_list = []
        for word in arglist:
            if word == '_all':
                all_checkouts = builder.invocation.all_checkout_labels()
                initial_list.extend(all_checkouts)
            else:
                label = Label.from_fragment(word,
                                            default_type=utils.LabelType.Checkout,
                                            default_role=None,
                                            default_domain=default_domain)
                initial_list.append(label)

        #print 'Initial list:', label_list_to_string(initial_list)

        intermediate_set = set()
        for index, label in enumerate(initial_list):
            if label.type == utils.LabelType.Checkout:
                intermediate_set.update(expand_checkout_label(builder, label, required_tag))
            elif label.type == utils.LabelType.Package:
                intermediate_set.update(expand_checkout_package_label(builder, label, required_tag))
            else:
                raise GiveUp("Cannot cope with label '%s', from input arg '%s'"%(label, arglist[index]))

        #print 'Intermediate set', label_list_to_string(intermediate_set)

        result_set = set()
        for label in intermediate_set:
            if label.is_definite():
                result_set.add(label)
            else:
                result_set.update(expand_wildcards(builder, label, required_tag))

        #print 'Result set', label_list_to_string(result_set)
        result_list = list(result_set)

    else:
        # Where are we? If in a checkout, that's what we should do - else
        # all checkouts.
        what, label, domain = builder.find_location_in_tree(current_dir)

        if what == utils.DirType.Checkout and label:
            # We're actually inside a checkout - job done
            result_list.append(label.copy_with_tag(required_tag))
        elif what in (utils.DirType.Checkout,
                      utils.DirType.Root,
                      utils.DirType.DomainRoot):
            # We're somewhere that we expect to have checkouts below
            cos_below = builder.get_all_checkout_labels_below(current_dir)
            for c in cos_below:
                result_list.append(c.copy_with_tag(required_tag))
        else:
            # Hmm - choose not to grumble, just to have an empty list
            pass

    # We promised a sorted list
    result_list.sort()
    return result_list

def decode_single_package_label(builder, arg, tag):
    """
    Convert a 'package' or 'package{role}' or '(domain)package{role} argument to a label.

    If role or domain is not specified, use the default (which may be None).
    """
    default_domain = builder.get_default_domain()
    label = Label.from_fragment(arg,
                                default_type=utils.LabelType.Package,
                                default_role=None,
                                default_domain=default_domain)
    if label.tag != tag:
        label = label.copy_with_tag(tag)
    if label.type != utils.LabelType.Package:
        raise GiveUp("Label '%s', from argument '%s', is not a valid"
                " package label"%(label, arg))
    return label

def decode_package_arguments(builder, arglist, current_dir, required_tag=None):
    """
    TBD
    """

    if not arglist:
        rv = builder.find_local_package_labels(current_dir,
                                               utils.LabelTag.PostInstalled)
        if rv:
            rv.sort()
            return rv
        else:
            raise GiveUp("No packages specified")

    result_set = set()
    default_domain = builder.get_default_domain()

    # Build up an initial list from the arguments given
    # Make sure we have a one-for-one correspondence between the input
    # list and the result
    initial_list = []
    for word in arglist:
        if word == '_all':
            initial_list.extend(builder.invocation.all_package_labels())
        else:
            label = Label.from_fragment(word,
                                        default_type=utils.LabelType.Package,
                                        default_role=None,
                                        default_domain=default_domain)
            initial_list.append(label)

    #print 'Initial list:', label_list_to_string(initial_list)

    intermediate_set = set()
    for index, label in enumerate(initial_list):
        if label.type == utils.LabelType.Package:
            intermediate_set.update(expand_package_label(builder, label, required_tag))
        elif label.type == utils.LabelType.Checkout:
            intermediate_set.update(expand_package_checkout_label(builder, label, required_tag))
        else:
            raise GiveUp("Cannot cope with label '%s', from input arg '%s'"%(label, arglist[index]))

    #print 'Intermediate set', label_list_to_string(intermediate_set)

    result_set = set()
    for label in intermediate_set:
        if label.is_definite():
            result_set.add(label)
        else:
            result_set.update(expand_wildcards(builder, label, required_tag))

    #print 'Result set', label_list_to_string(result_set)

    result_list = list(result_set)
    result_list.sort()
    return result_list

def decode_deployment_arguments(builder, args, current_dir, required_tag):
    """
    TBD
    """
    return_list = [ ]

    default_domain = builder.get_default_domain()

    if args:
        for dep in args:
            if (dep == "_all"):
                # Everything .. 
                return_list = all_deployment_labels(builder, required_tag)
                return_list.sort()
                return return_list
            else:
                lbl = Label.from_fragment(dep,
                                          default_type=utils.LabelType.Deployment,
                                          default_role="*",
                                          default_domain=default_domain)
                if lbl.type != utils.LabelType.Deployment:
                    raise GiveUp("Label '%s', from argument '%s' not allowed"
                            " as a deployment label"%(lbl, dep))
                if lbl.tag != required_tag:
                    lbl = lbl.copy_with_tag(required_tag)
                return_list.append(lbl)
    else:
        # Can we guess what to do from where we are?
        what, label, domain = builder.find_location_in_tree(current_dir)
        if what == utils.DirType.Deployment:
            # We're actually inside a deployment - job done
            result_list.append(label.copy_with_tag(required_tag))
        else:
            # The best we can do is to use the default deployments
            return_list = default_deployment_labels(builder, required_tag)

    result_set = set()
    for label in return_list:
        if label.is_definite():
            result_set.add(label)
        else:
            result_set.update(expand_wildcards(builder, label, required_tag))

    return_list = list(result_set)
    return_list.sort()
    return return_list

# -----------------------------------------------------------------------------
# Support for the above
# -----------------------------------------------------------------------------

def expand_checkout_label(builder, label, required_tag):
    """Given an intermediate checkout label, expand it to a set of labels.

    TODO: decide what wildcards we accept, and expand them(?)
    """
    intermediate_set = set()
    result_set = set()

    intermediate_set.add(label)

    if required_tag is not None:
        for label in intermediate_set:
            if label.tag != required_tag:
                label = label.copy_with_tag(required_tag)
            result_set.add(label)
    else:
        result_set = intermediate_set

    return result_set

def expand_checkout_package_label(builder, label, required_tag):
    """Given an intermediate package label, expand it to a set of checkout labels.
    """
    result_set = set()

    these_labels = builder.invocation.checkouts_for_package(label)

    if required_tag:
        for lbl in these_labels:
            result_set.add(lbl.copy_with_tag(required_tag))
    else:
        result_set = set(these_labels)

    return result_set

def name_selected_checkouts(verb, checkout_labels):
    if checkout_labels:
        print '%s checkouts: %s'%(verb,
                label_list_to_string(checkout_labels))
    else:
        print 'No checkouts selected'


def decode_labels(builder, in_args):
    """
    Each argument is a label - convert each to a proper label
    object and then return the resulting list
    """
    rv = [ ]
    for arg in in_args:
        lbl = Label.from_string(arg)
        rv.append(lbl)

    return rv


def all_deployment_labels(builder, tag):
    """
    Return all the deployment labels registered with the ruleset.
    """

    # Important not to set tag here - if there's a deployment
    #  which doesn't have the right tag, we want an error, 
    #  not to silently ignore it.
    match_lbl = Label(utils.LabelType.Deployment,
                      "*", "*", "*", domain = builder.get_default_domain())
    matching = builder.invocation.ruleset.rules_for_target(match_lbl)

    return_set = set()
    for m in matching:
        return_set.add(m.target.name)

    return_list = [ ]
    for r in return_set:
        lbl = Label(utils.LabelType.Deployment,
                    r,
                    "*",
                    tag)
        return_list.append(lbl)

    return return_list

def default_deployment_labels(builder, tag):
    """
    Return labels tagged with tag for all the default deployments.
    """

    default_labels = builder.invocation.default_labels
    return_list = [ ]
    for d in default_labels:
        if (d.type == utils.LabelType.Deployment):
            return_list.append(Label(utils.LabelType.Deployment,
                               d.name,
                               d.role,
                               tag))

    return return_list


def expand_package_label(builder, label, required_tag):
    """Given an intermediate package label, expand it to a set of labels.
    """
    result_set = set()
    default_roles = builder.invocation.default_roles

    if required_tag is not None and label.tag != required_tag:
        label = label.copy_with_tag(required_tag)

    if label.role:
        result_set.add(label)
    elif default_roles:
        # Add the default roles
        for r in default_roles:
            lbl = label.copy_with_role(r)
            result_set.add(lbl)
    else:
        # Just wildcard for any role
        lbl = label.copy_with_role('*')
        result_set.add(lbl)

    return result_set

def expand_package_checkout_label(builder, label, required_tag):
    """Given an intermediate checkout label, expand it to a set of package labels.
    """

    intermediate_set = set()
    intermediate_set.update(builder.invocation.packages_using_checkout(label))

    if required_tag is not None:
        result_set = set()
        for lbl in intermediate_set:
            if lbl.tag != required_tag:
                lbl = lbl.copy_with_tag(required_tag)
            result_set.add(lbl)
    else:
        result_set = intermediate_set

    return result_set

def expand_wildcards(builder, label, required_tag=None):
    """
    Given a label which may contain wildcards, return a set of labels that match.

    As per the normal definition of labels, the <type>, <name>, <role> and
    <tag> parts of the label may be wildcarded.

    If required_tag is given, then any labels found that have a '*' for
    their tag will have it replaced by this value.
    """

    if label.is_definite():
        # There are no wildcards - it matches itself
        # (should we check if it exists?)
        return set(label)

    # This is perhaps not the most efficient way to do this, but it is simple
    possible_labels = []
    if label.type == utils.LabelType.Checkout:
        possible_labels = builder.invocation.all_checkout_labels()
    elif label.type == utils.LabelType.Package:
        possible_labels = builder.invocation.all_package_labels()
    elif label.type == utils.LabelType.Deployment:
        possible_labels = builder.invocation.all_deployment_labels()
    else:
        raise GiveUp("Cannot expand wildcards in label '%s', which"
                " has an unrecognised type"%label)

    actual_labels = set()
    for possible in possible_labels:
        wildcardiness = label.match(possible)
        if wildcardiness is None:                   # They didn't match
            continue
        if required_tag is not None and possible.tag == '*':
            possible = possible.copy_with_tag(required_tag)
        actual_labels.add(possible)

    return actual_labels

# End file.
