Muddle is a build system for systems. It specialises in taking a set of packages and welding them together into a firmware image for an embedded system. The assembly of these packages is directed by an executable build description written in Python.

Muddle was designed specifically for use in producing an embedded system from scratch. It is aimed at people who start with a new board and need to assemble the operating system and user space software for it. It does not provide pre-packaged solutions in the manner of Yocto or open-embedded.

Among other things, muddle supports:

  * Specifying the dependencies of packages, and thus the order of build and rebuild.
  * Building the Linux kernel, and generating CPIO initrds from source. Note that this does not require sudo at any stage.
  * Building separate targets from the same packages, sharing binaries and object files as necessary.
  * Interacting with version control systems (currently, svn, bazaar and git, though adding another is no more than a couple of day's work)
  * Producing binary distributions.
  * Producing source code releases. Packages can be marked with their license-type, allowing automated generation of GPL-compliant releases.  Muddle makes it easier to make such build subsets buildable, rather than just providing a source dump.
  * Managing maintenance release branches of all packages in the build tree (still under development)

Muddle is used internally at Kynesim, as well as by other people. If you have problems with it, or ideas on how it could be improved, please do raise an issue, or contact us directly.

There is a mirror of the muddle source code at https://github.com/tibs/muddle.mirror, which should normally be up-to-date - please use this if Google is having problems.

Documentation lives at http://muddle.readthedocs.org/, thanks to [ReadTheDocs](https://readthedocs.org/), who are wonderful people. The documentation should be updated every time a change is pushed to the main source code repository.

Some slides for a talk rrw gave on muddle are available in the [Downloads](http://code.google.com/p/muddle/downloads/list) section.

The [Kynesim blog](http://kynesim.blogspot.com/) also periodically has articles on using muddle.

Note: muddle currently requires Python 2.7, but the intention is to move to Python 3 at some point in 2014.


---


Traditionally, muddle is also licenced to kill and to serve drinks after hours.


---

On Monday 29th August 2011, muddle was moved from subversion to git. If you're still accessing it via subversion, note that you are using a "frozen" version, which will not be developed further. The last subversion revision is [revision 638](https://code.google.com/p/muddle/source/detail?r=638). Also note that due to difficulties in converting our subversion repository to git, only trunk has been converted, and at that only since [revision 78](https://code.google.com/p/muddle/source/detail?r=78) (around when something strange seems to have happened, probably to do with trying to merge stuff in subversion).

---
