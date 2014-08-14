#! /usr/bin/env python
"""Test "muddle distribute" support

    $ ./test_distribute.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

Our test build structure is::

        <top>
                subdomain1
                        subdomain3
                subdomain2
"""

import os
import shutil
import string
import subprocess
import sys
import traceback

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag, DirTypeDict, label_part_join
from muddled.withdir import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string
from muddled.version_stamp import VersionStamp

MUDDLE_MAKEFILE = """\
# Trivial muddle makefile
all:
\t@echo Make all for '$(MUDDLE_LABEL)'
\t$(CC) $(MUDDLE_SRC)/{progname}.c -o $(MUDDLE_OBJ)/{progname}

config:
\t@echo Make configure for '$(MUDDLE_LABEL)'

install:
\t@echo Make install for '$(MUDDLE_LABEL)'
\tcp $(MUDDLE_OBJ)/{progname} $(MUDDLE_INSTALL)

clean:
\t@echo Make clean for '$(MUDDLE_LABEL)'

distclean:
\t@echo Make distclean for '$(MUDDLE_LABEL)'

.PHONY: all config install clean distclean
"""

TOPLEVEL_BUILD_DESC = """ \
# A build description that includes two subdomains

import os

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label
from muddled.utils import LabelType, LabelTag
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

from muddled.distribute import name_distribution, \
        distribute_checkout, distribute_package

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")

    # So we can test stamping a Repository using a direct URL
    co_label = Label(LabelType.Checkout, 'second_co')
    repo = Repository.from_url('git', 'file://{repo}/main/second_co')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, "second_pkg", role, "second_co")

    # A package in a different role (which we never actually build)
    muddled.pkgs.make.simple(builder, "main_pkg", 'arm', "main_co")

    include_domain(builder,
                   domain_name = "subdomain1",
                   domain_repo = "git+file://{repo}/subdomain1",
                   domain_desc = "builds/01.py")

    include_domain(builder,
                   domain_name = "subdomain2",
                   domain_repo = "git+file://{repo}/subdomain2",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    # And collect stuff from our subdomains
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub1',
                                 domain='subdomain1')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub2',
                                 domain='subdomain2')

    # The 'arm' role is *not* a default role
    builder.add_default_role(role)
    builder.by_default_deploy(deployment)

    # Let's add some distribution specifics
    label = Label.from_string
    # We're describing a distribution called "mixed", which contains both
    # source and obj (but not install)
    name_distribution(builder, 'mixed')
    distribute_checkout(builder, 'mixed', label('checkout:first_co/*'))
    distribute_package(builder, 'mixed', label('package:second_pkg{{x86}}/*'),
                       obj=True, install=False)

    # We have another distribution which corresponds to role x86, source
    # and all binary
    name_distribution(builder, 'role-x86')
    distribute_package(builder, 'role-x86', label('package:*{{x86}}/*'),
                       obj=True, install=True)
    distribute_checkout(builder, 'role-x86', label('package:*{{x86}}/*'))

    # And another distribution which is a vertical slice down the domains
    # (so see the subdomain build descriptions as well)
    # Also, note that technically our subdomain inclusion will have named this
    # distribution before we do - but we're allowed to name it again
    name_distribution(builder, 'vertical')
    distribute_package(builder, 'vertical', label('package:second_pkg{{x86}}/*'),
                       obj=True, install=True)
    distribute_checkout(builder, 'vertical', label('package:second_pkg{{x86}}/*'))
"""

SUBDOMAIN1_BUILD_DESC = """ \
# A build description that includes a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label
from muddled.distribute import name_distribution, \
        distribute_package, distribute_checkout

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # If we name our distribution here, before including the subdomain,
    # which also uses it, then we shouldn't need to name it in the subdomain
    # itself...
    name_distribution(builder, 'vertical')

    include_domain(builder,
                   domain_name = "subdomain3",
                   domain_repo = "git+file://{repo}/subdomain3",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # also the same
                                 rel='',
                                 dest='sub3',
                                 domain='subdomain3')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)

    # Our vertical distribution continues
    label = Label.from_string
    distribute_package(builder, 'vertical', label('package:second_pkg{{x86}}/*'),
                       obj=True, install=True)
    distribute_checkout(builder, 'vertical', label('package:second_pkg{{x86}}/*'))
"""

SUBDOMAIN2_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
"""

SUBDOMAIN3_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label
from muddled.distribute import distribute_package, distribute_checkout

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")

    # Our vertical distribution continues
    # (Remember, our parent domain named it for us - normally it would be
    # bad form to rely on that, since subdomains are meant to stand alone
    # as builds, but this is useful to do for testing...)
    label = Label.from_string
    distribute_package(builder, 'vertical', label('package:second_pkg{x86}/*'),
                       obj=True, install=True)
    distribute_checkout(builder, 'vertical', label('package:second_pkg{x86}/*'))
"""

GITIGNORE = """\
*~
*.pyc
"""

MAIN_C_SRC = """\
// Simple example C source code
#include <stdio.h>
int main(int argc, char **argv)
{{
    printf("Program {progname}\\n");
    return 0;
}}
"""

INSTRUCTIONS = """
<?xml version="1.0"?>
<instructions priority=100>
  <!-- Nothing to do here. Move along... -->
</instructions>
"""

def make_build_desc(co_dir, file_content):
    """Take some of the repetition out of making build descriptions.
    """
    git('init')
    touch('01.py', file_content)
    git('add 01.py')
    git('commit -m "Commit build desc"')
    touch('.gitignore', GITIGNORE)
    git('add .gitignore')
    git('commit -m "Commit .gitignore"')

def make_standard_checkout(co_dir, progname, desc):
    """Take some of the repetition out of making checkouts.
    """
    git('init')
    touch('{progname}.c'.format(progname=progname),
            MAIN_C_SRC.format(progname=progname))
    touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
    git('add {progname}.c Makefile.muddle'.format(progname=progname))
    git('commit -a -m "Commit {desc} checkout {progname}"'.format(desc=desc,
        progname=progname))

def make_repos_with_subdomain(root_dir):
    """Create git repositories for our subdomain tests.
    """
    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'main0', 'main')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN1_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain1', 'subdomain1')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN2_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain2', 'subdomain2')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN3_BUILD_DESC)
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain3', 'subdomain3')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')

def checkout_build_descriptions(root_dir, d):

    repo = os.path.join(root_dir, 'repo')
    muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])

    check_files([d.join('src', 'builds', '01.py'),
                 d.join('domains', 'subdomain1', 'src', 'builds', '01.py'),
                 d.join('domains', 'subdomain1', 'domains', 'subdomain3', 'src', 'builds', '01.py'),
                 d.join('domains', 'subdomain2', 'src', 'builds', '01.py'),
                ])

def check_checkout_files(d):
    """Check we have all the files we should have after checkout

    'd' is the current Directory.
    """
    def check_dot_muddle(is_subdomain):
        with Directory('.muddle') as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository')])

            if is_subdomain:
                check_files([m.join('am_subdomain')])

        check_tags([label_part_join('checkout', 'builds', 'checked_out'),
                    label_part_join('checkout', 'first_co', 'checked_out'),
                    label_part_join('checkout', 'main_co', 'checked_out'),
                    label_part_join('checkout', 'second_co', 'checked_out')])

    def check_src_files(main_c_file='main0.c'):
        check_files([s.join('builds', '01.py'),
                     s.join('main_co', 'Makefile.muddle'),
                     s.join('main_co', main_c_file),
                     s.join('first_co', 'Makefile.muddle'),
                     s.join('first_co', 'first.c'),
                     s.join('second_co', 'Makefile.muddle'),
                     s.join('second_co', 'second.c')])

    check_dot_muddle(is_subdomain=False)
    with Directory('src') as s:
        check_src_files('main0.c')

    with Directory(d.join('domains', 'subdomain1', 'src')) as s:
        check_src_files('subdomain1.c')
    with Directory(d.join('domains', 'subdomain1')):
        check_dot_muddle(is_subdomain=True)

    with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3', 'src')) as s:
        check_src_files('subdomain3.c')
    with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3')):
        check_dot_muddle(is_subdomain=True)

    with Directory(d.join('domains', 'subdomain2', 'src')) as s:
        check_src_files('subdomain2.c')
    with Directory(d.join('domains', 'subdomain2')):
        check_dot_muddle(is_subdomain=True)

def add_some_instructions(d):
    """Add some instruction file by hand.

    We should do this properly, via Makefiles copying instructions with
    ``$(MUDDLE_INSTRUCT)``, but this is simpler.
    """
    with Directory('.muddle'):
        with NewDirectory('instructions'):
            with NewDirectory('first_pkg'):
                touch('_default.xml', INSTRUCTIONS)
            with NewDirectory('second_pkg'):
                touch('_default.xml', INSTRUCTIONS)
                touch('x86.xml', INSTRUCTIONS)
                touch('arm.xml', INSTRUCTIONS)
                touch('fred.xml', INSTRUCTIONS)     # How did that get here?

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:

        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT')
            checkout_build_descriptions(root_dir, d)
            muddle(['checkout', '_all'])
            check_checkout_files(d)
            banner('BUILD')
            muddle([])
            banner('STAMP VERSION')
            muddle(['stamp', 'version'])
            banner('ADD SOME INSTRUCTIONS')
            add_some_instructions(d)

            banner('TESTING DISTRIBUTE SOURCE RELEASE')
            target_dir = os.path.join(root_dir, 'source')
            muddle(['distribute', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                          ],)# TODO: properly assert which tags are expected

            # Issue 250
            banner('TESTING DISTRIBUTE SOURCE RELEASE when in a subdirectory')
            with Directory('src/builds'):
                target_dir = os.path.join(root_dir, 'source-2')
                muddle(['distribute', '_source_release', target_dir])
                dt = DirTree(d.where, fold_dirs=['.git'])
                dt.assert_same(target_dir, onedown=True,
                               unwanted_files=['.git*',
                                               'builds/01.pyc',
                                               'obj',
                                               'install',
                                               'deploy',
                                               'versions',
                                               '.muddle/instructions',
                                              ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE SOURCE RELEASE WITH VCS')
            target_dir = os.path.join(root_dir, 'source-with-vcs')
            muddle(['distribute', '-with-vcs', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=[
                                           'builds/01.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE SOURCE RELEASE WITH VERSIONS')
            target_dir = os.path.join(root_dir, 'source-with-versions')
            muddle(['distribute', '-with-versions', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           '.muddle/instructions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE SOURCE RELEASE WITH VCS AND VERSIONS')
            target_dir = os.path.join(root_dir, 'source-with-vcs-and-versions')
            muddle(['distribute', '-with-vcs', '-with-versions', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=[
                                           'builds/01.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           '.muddle/instructions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE SOURCE RELEASE WITH "-no-muddle-makefile"')
            # Hint: it shouldn't make any difference at all
            target_dir = os.path.join(root_dir, 'source-no-muddle-makefile')
            muddle(['distribute', '-no-muddle-makefile', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE BINARY RELEASE')
            target_dir = os.path.join(root_dir, 'binary')
            muddle(['distribute', '_binary_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           '*.c',
                                           'obj',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE BINARY RELEASE WITHOUT MUDDLE MAKEFILE')
            target_dir = os.path.join(root_dir, 'binary-no-muddle-makefile')
            muddle(['distribute', '-no-muddle-makefile', '_binary_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           'src/*co',  # no checkouts other than build
                                           'obj',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE BINARY RELEASE WITH VERSIONS')
            target_dir = os.path.join(root_dir, 'binary-with-versions')
            muddle(['distribute', '-with-versions', '_binary_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           '*.c',
                                           'obj',
                                           'deploy',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE BINARY RELEASE WITH VERSIONS AND VCS')
            target_dir = os.path.join(root_dir, 'binary-with-versions-and-vcs')
            muddle(['distribute', '-with-versions', '-with-vcs', '_binary_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=[
                                           'builds/01.pyc',
                                           '*.c',
                                           'src/*_co/.git*',
                                           'obj',
                                           'deploy',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE "mixed"')
            target_dir = os.path.join(root_dir, 'mixed')
            muddle(['distribute', 'mixed', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           # -- Checkouts
                                           'src/main_co',
                                           # We want src/first_co
                                           # We want the Makefile.muddle in second_co
                                           'src/second_co/*.c',
                                           # -- Domains
                                           'domains', # we don't want any subdomains
                                           # -- Packages: obj
                                           'obj/main_pkg',
                                           'obj/first_pkg',
                                           # We want obj/second_pkg
                                           # -- Not install/
                                           'install',
                                           # -- Deployments
                                           'deploy',
                                           # -- Tags
                                           # Tags are handled crudely currently
                                           # -- etc
                                           '.muddle/instructions/first_pkg',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                           'versions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE "mixed" WITH "-no-muddle-makefile"')
            # Again, shouldn't make any difference
            target_dir = os.path.join(root_dir, 'mixed')
            muddle(['distribute', 'mixed', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           # -- Checkouts
                                           'src/main_co',
                                           # We want src/first_co
                                           # We want the Makefile.muddle in second_co
                                           'src/second_co/*.c',
                                           # -- Domains
                                           'domains', # we don't want any subdomains
                                           # -- Packages: obj
                                           'obj/main_pkg',
                                           'obj/first_pkg',
                                           # We want obj/second_pkg
                                           # -- Not install/
                                           'install',
                                           # -- Deployments
                                           'deploy',
                                           # -- Tags
                                           # Tags are handled crudely currently
                                           # -- etc
                                           '.muddle/instructions/first_pkg',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                           'versions',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE "role-x86"')
            target_dir = os.path.join(root_dir, 'role-x86')
            muddle(['distribute', 'role-x86', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           'deploy',
                                           '.muddle/tags/deployment',
                                           'domains',   # we didn't ask for subdomains
                                           'versions',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                           # We only want role x86, not role arm
                                           'obj/main_pkg/arm',
                                           'install/arm',
                                          ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE "vertical"')
            target_dir = os.path.join(root_dir, 'vertical')
            muddle(['distribute', 'vertical', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'builds/01.pyc',
                                           # -- Checkouts
                                           'src/main_co',
                                           'src/first_co',
                                           # We want src/second_co
                                           # -- Packages: obj
                                           'obj/main_pkg',
                                           'obj/first_pkg',
                                           # We want obj/second_pkg
                                           # -- Packages: install
                                           'install/arm',
                                           # We want install/x86/second, but have no
                                           # way to stop getting ALL of install/x86
                                           # -- Subdomains
                                           # We've not asked for owt in subdomain2
                                           'domains/subdomain2',
                                           # -- Deployments
                                           'deploy',
                                           # -- Tags
                                           # -- etc
                                           '.muddle/instructions/first_pkg',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                           'versions',
                                         ],)# TODO: properly assert which tags are expected

            banner('TESTING DISTRIBUTE "vertical" WITH VCS AND VERSIONS')
            target_dir = os.path.join(root_dir, 'vertical-with-vcs-and-versions')
            # Remember, we're asking for VCS in the build description and version
            # directories, but not changing what the build description says for
            # explicitly asked for checkouts...
            muddle(['distribute', '-with-vcs', '-with-versions', 'vertical', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=[
                                           'builds/01.pyc',
                                           # -- Checkouts
                                           'src/main_co',
                                           'src/first_co',
                                           # We want src/second_co, but we didn't
                                           # ask for its VCS
                                           'src/second_co/.git*',
                                           # -- Packages: obj
                                           'obj/main_pkg',
                                           'obj/first_pkg',
                                           # We want obj/second_pkg
                                           # -- Packages: install
                                           'install/arm',
                                           # We want install/x86/second, but have no
                                           # way to stop getting ALL of install/x86
                                           # -- Subdomains
                                           # We've not asked for owt in subdomain2
                                           'domains/subdomain2',
                                           # -- Deployments
                                           'deploy',
                                           # -- Tags
                                           # We want tags for second_co and second_pkg
                                           # -- etc
                                           '.muddle/instructions/first_pkg',
                                           '.muddle/instructions/second_pkg/arm.xml',
                                           '.muddle/instructions/second_pkg/fred.xml',
                                         ],)# TODO: properly assert which tags are expected



if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        main(args)
        print '\nGREEN light\n'
    except Exception as e:
        print
        traceback.print_exc()
        print '\nRED light\n'
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
