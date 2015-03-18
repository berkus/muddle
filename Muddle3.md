

# Introduction #

This page describes the intentions for muddle3 - the next version of muddle.

Muddle (i.e., muddle2) is too slow for large build descriptions. The build descriptions themselves are also a bit of a mess, and the codebase is showing its ragged edges. Thus we'd like to produce muddle3.

The main aims are:

  * Cache information to speed things up. This is the biggest win for actual muddle users.
  * But the .muddle directory is a Good Idea, so keep it.
  * Improve/simplify the muddled APIs.
  * Labels everywhere.
  * Continue in Python 2.6, but aim to be Python 3 compatible.
  * Split the dependency engine from the VCS-and-build-system layer.

_All content on this page is subject to change as we work things out!_

# Details #

Not in any particular order...

## Python version ##
Whilst it would be nice to move to Python 3, we already cause enough problems by relying on Python 2.6. Thus we shall continue to use Python 2.6, but aim to make porting to Python 3 as simple as possible.

> (So far, I've not even tried running the 2to3 tool on muddle.)

## Labels everywhere ##
The original implementation of muddle, and thus muddle2 as well, passes around only those parts of a label that are "needed". This sounded like a good idea at the time. When implementing domain support, it quickly became apparent that it is difficult to expand the "needed" if not all of the label is given. Thus muddle3 will pass labels around as such.

This then leads to the question of what to do when a method that expects a "package:" label is called - whether it should check that it has been given a valid "package:" label, or perhaps something it does not expect.

The decision is that **labels are typed**. Thus appropriate checks will be made as necessary to ensure that the label is of the correct type (whatever that is deemed to mean!). This also means we need to work out how to say what we want of a label -- duck typing is a good thing when that's what we want, but we also want to be able to "say" that a label must match particular requirements.

> Can we do this with appropriate use of interfaces and so on? That might be fun...

## Splitting engines, plugins, etc. ##

Muddle2 is fundamentally a label/dependency engine plus some knowledge about interacting with particular VCSs and how to build systems on Unix (via the checkout:/package:/deployment: style labels).

It feels like it would be a good idea to separate these more, probably by having a central label/dependency engine, and then a series of plugins (or something) to specify how to perform the current "build system" stuff.

Other potential plugins would be for use on Wndows to handle installation of things, and who knows what else (we don't really need any more examples, but the current situation rather discourages people from trying to produce any).

So one aim is to untangle things as we go, and the other is to think about how one might produce a "plugin" mechanism.

## Simplifying/improooving APIs ##

At the moment, build descriptions import too many different modules, and the APIs of several of the commands used are inconvenient or over-verbose. Many of the keyword arguments have odd names, and they are not consistent across methods.

One of the major changes for muddle3 will be to simplify this, so that fewer imports are needed, and the build description code becomes shorter and easier to read.

## Support Unicode ##
Which elements of a label should be able to be Unicode, as opposed to ASCII? Python3 would help here...

## Caching information ##
Muddle2 is slow, very slow, for large dependency sets. This needs fixing.

### Dependency caching ###
The obvious thing to do is to store the dependency information, since calculating this is what takes the vast bulk of the time.

When reading in the build descriptions, produce an MD5 (or other) sum of the Python files, and check if it has changed. If it has, throw away the old cache and recalculate all the dependencies. Otherwise just use the precalculated data.

Richard's suggestion is to use SQLite as a first solution, as it is free and comes with Python.

I wonder if we should also investigate ZODB or some other (lighter weight?) OODB approach. However, using something provided as standard sounds like a good thing.

### Query caching ###

When a makefile (or other subprocess) does a "muddle query", we'd like it to be as quick as possible. Clearly making muddle (in general) start up more quickly helps, but another obvious saving is to cache (and possibly precalculate) certain queries - "muddle query objdir" springs to mind as an obvious case.

## The .muddle directory ##

The .muddle directory _as a directory of files_ is clearly one of muddles major wins. We have **no intention** of changing this. For a start, we don't think it is a bottleneck, but even if it is, we would use a caching approach to maintain the current structure.

> _It is important that one can change the build state using simple file system tools, and we stand by that as a fundamental benefit of muddle._

## Python modules for VCS support? ##

At the moment, all of the VCS support is done via the command line (i.e., by generating shell commands, executing them, and possibly parsing the output). This is clumsy and error prone (not least when the output from a command changes!), but does mean we do not have any external dependencies.

All of the major VCSs (Subversion, Bazaar, Mercurial and git) have Python modules (in some cases, more than one) that enable one to interact directly with the VCS. This would simplify the codebase in many ways, but at the expense of actually depending on said modules.

On the other hand, PyPI is there, and we should probably be in it. so this may or may not be a big stumbling block.

## The muddle command line ##

The muddle command line is getting cluttered and illogical. Also, quite a bit of the code could do with abstracting out and putting elsewhere.

On the other hand. the basic approach of the Command subclasses as the basis for commands does seem to work quite well.

## Incremental changes to the codebase ##

We both agree that doing the work by incremental changes to the existing codebase is sensible. It allows us to make sure it is still working (because we'll still be using it for existing projects, which, after all, are what is driving this effort), and it avoids the need to reimplement stuff that we don't want to change. And we're less likely to forget something!

However, since we are the major users, and since muddle2 is mostly working (cross fingers), we can safely afford to break APIs at head-of-tree.

This does mean it may be difficult to tell when muddle2 has actually become muddle3...