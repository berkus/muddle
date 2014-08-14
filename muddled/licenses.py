"""
Matters relating to attributing licenses to checkouts
"""

import copy
import os
import fnmatch

from muddled.depend import Label, required_by, label_list_to_string, \
        normalise_checkout_label
from muddled.utils import GiveUp, LabelType, wrap

import logging
def log(*args, **kwargs):
    args = [str(arg) for arg in args]
    logging.getLogger(__name__).warning(' '.join(args))

logger = logging.getLogger(__name__)

ALL_LICENSE_CATEGORIES = ('gpl', 'open-source', 'prop-source', 'binary', 'private')

class License(object):
    """The representation of a source license.

    License instances should be:

        1. Singular
        2. Immutable

    but I don't particularly propose to work hard to enforce those...

    Use the subclasses to create your actual License instance, so that you
    can use any appropriate extra methods...
    """

    def __init__(self, name, category, version=None):
        """Initialise a new License.

        The 'name' is the name of this license, as it is normally recognised.

        'category' is meant to be a broad categorisation of the type of the
        license. Currently that is one of:

            * 'gpl' - some sort of GPL license, which propagate the need to
              distribute source code to other "adjacent" entities
            * 'open-source' - an open source license, anything that is not 'gpl'.
              Source code may, but need not be, distributed.
            * 'prop-source' - a proprietary source license, not an open source
              license. This might, for instance, be used for /etc files, which
              are distributed as "source code" (i.e., text), but are not
              in fact licensed under an open source license.
            * 'binary' - a binary license, indicating that the source code is
              not to be distributed, but binary (the contents of the "install"
              directory) may be.
            * 'private' - a marker that the checkout should not be distributed
              at all.

        'version' may be a version string. If it is None, then it will not be
        shown in the str() or repr() for a license.
        """
        self.name = name
        if category not in ALL_LICENSE_CATEGORIES:
            raise GiveUp("Attempt to create License '%s' with unrecognised"
                         " category '%s'"%(name, category))
        self.category = category
        self.version = version

    def __str__(self):
        if self.version:
            return '%s %s'%(self.name, self.version)
        else:
            return self.name

    def __repr__(self):
        if self.version:
            return '%s(%r, %r, version=%r)'%(self.__class__.__name__,
                    self.name, self.category, self.version)
        else:
            return '%s(%r, %r)'%(self.__class__.__name__, self.name, self.category)

    def __eq__(self, other):
        return (self.name == other.name and
                self.category == other.category and
                self.version == other.version)

    def __hash__(self):
        return hash((self.name, self.category, self.version))

    def copy_with_version(self, version):
        """Make a copy of this license with a different version string.
        """
        new = copy.copy(self)
        new.version = version
        return new

    def distribute_as_source(self):
        """Returns True if we this license is for source distribution.

        Currently, equivalent to having a category of open-source, gpl or
        prop-source.
        """
        return self.category in ('open-source', 'gpl', 'prop-source')

    def is_open(self):
        """Returns True if this is some sort of open-source license.

        Note: this includes GPL and LGPL licenses.
        """
        return self.category in ('open-source', 'gpl')

    def is_open_not_gpl(self):
        """Returns True if this license is 'open-source' but not 'gpl'.
        """
        return self.category == 'open-source'

    def is_proprietary_source(self):
        """Returns True if this is some sort of propetary source license.

        (i.e., has category 'prop-source')

        Note: this does *not* include 'open-source' or 'gpl'.
        """
        return self.category == 'prop-source'

    def is_gpl(self):
        """Returns True if this is some sort of GPL license.
        """
        return self.category == 'gpl'

    def is_lgpl(self):
        """Returns True if this is some sort of LGPL license.

        This *only* works for the LicenseLGpl class (and any subclasses of it,
        of course).
        """
        return False

    def is_binary(self):
        """Is this a binary-distribution-only license?
        """
        return self.category == 'binary'

    def is_private(self):
        """Is this a private-do-not-distribute license?
        """
        return self.category == 'private'

    def propagates(self):
        """Does this license "propagate" to other checkouts?

        In other words, if checkout A has this license, and checkout B depends
        on checkout A, does the license have an effect on what you can do with
        checkout B?

        For non-GPL licenses, the answer is assumed "no", and we thus return
        False.

        For GPL licenses with a linking exception (e.g., the GCC runtime
        library, or some Java libraries with CLASSPATH exceptions), the answer
        is also "no", and we return False.

        However, for most GPL licenses (and this includes LGPL), the answer
        if "yes", there is some form of propagation (remember, LGPL allows
        dynamic linking, and use of header files, but not static linking),
        and we return True.

        If we return True, it is then up to the user to decide if this means
        anything in this particular case - muddle doesn't know *why* one
        checkout depends on another.
        """
        return False

class LicensePrivate(License):
    """A "private" license - we do not want to distribute anything
    """

    def __init__(self, name, version=None):
        super(LicensePrivate, self).__init__(name=name, category='private', version=version)

    def __repr__(self):
        if self.version:
            return '%s(%r, version=%r)'%(self.__class__.__name__, self.name, self.version)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseBinary(License):
    """A binary license - we distribute binary only, not source code
    """

    def __init__(self, name, version=None):
        super(LicenseBinary, self).__init__(name=name, category='binary', version=version)

    def __repr__(self):
        if self.version:
            return '%s(%r, version=%r)'%(self.__class__.__name__, self.name, self.version)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseProprietarySource(License):
    """A source license, but not open source.

    This is separate from the "open" licenses mainly because it is not, in
    fact, representing an open license, so even if it were to be treated
    identically in all matters, it would still be wrong.

    The class name is rather long, but it is hard to think of a shorter name
    that explains what it is for.
    """

    def __init__(self, name, version=None):
        super(LicenseProprietarySource, self).__init__(name=name,
                            category='prop-source', version=version)

    def __repr__(self):
        if self.version:
            return '%s(%r, version=%r)'%(self.__class__.__name__, self.name, self.version)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseOpen(License):
    """Some non-GPL open source license.

    This should probably be named "LicenseOpenSource", but that is rather long.
    """

    def __init__(self, name, version=None):
        super(LicenseOpen, self).__init__(name=name, category='open-source', version=version)

    def __repr__(self):
        if self.version:
            return '%s(%r, version=%r)'%(self.__class__.__name__, self.name, self.version)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseGPL(License):
    """Some sort of GPL license.

    (Why LicenseGPL rather than GPLLicense? Because I find the later more
    confusing with the adjacent 'L's, and I want to keep GPL uppercase...)
    """

    def __init__(self, name, version=None, with_exception=False):
        """Initialise a new GPL License.

        The 'name' is the name of this license, as it is normally recognised.

        Some GNU libraries provide a `linking exception`_, which allows
        software to "link" (depending on the exception) to the library, without
        needing to be GPL-compatible themselves. One example of this (more or
        less) is the LGPL, for which we have a separate class. Another example
        is the GCC Runtime Library.

        .. _`linking exception`: http://en.wikipedia.org/wiki/GPL_linking_exception
        """
        super(LicenseGPL, self).__init__(name=name, category='gpl', version=version)
        self.with_exception = with_exception

    def __repr__(self):
        if self.with_exception:
            if self.version:
                return '%s(%r, version=%r, with_exception=True)'%(self.__class__.__name__,
                        self.name, self.version)
            else:
                return '%s(%r, with_exception=True)'%(self.__class__.__name__, self.name)
        else:
            if self.version:
                return '%s(%r, version=%r)'%(self.__class__.__name__, self.name, self.version)
            else:
                return '%s(%r)'%(self.__class__.__name__, self.name)

    def __eq__(self, other):
        # Doing the super-comparison first guarantees we're both some sort of GPL
        return (super(LicenseGPL, self).__eq__(other) and
                self.with_exception == other.with_exception)

    def __hash__(self):
        return hash((self.name, self.category, self.with_exception))

    def is_gpl(self):
        """Returns True if this is some sort of GPL license.
        """
        return True

    def propagates(self):
        return not self.with_exception

    # I don't want to type all that documentation again...
    propagates.__doc__ = License.propagates.__doc__

class LicenseLGPL(LicenseGPL):
    """Some sort of Lesser GPL (LGPL) license.

    The lesser GPL implies that it is OK to link to this checkout as a shared
    library, or to include its header files, but not link statically. We don't
    treat that as a "with_exception" case specifically, since it is up to the
    user to decide if an individual checkout that depends on a checkout with
    this license is affected by our GPL-ness.
    """

    def __init__(self, name, version=None, with_exception=False):
        """Initialise a new LGPL License.

        The 'name' is the name of this license, as it is normally recognised.
        """
        super(LicenseLGPL, self).__init__(name=name, version=version, with_exception=with_exception)

    def is_lgpl(self):
        """Returns True if this is some sort of LGPL license.
        """
        return True

# Let's define some standard licenses
# We'll try to use the names from http://www.spdx.org/licenses/ as the
# dictionary keys. Also see http://opensource.org/licenses/alphabetical for
# a list of actual open source licenses.
standard_licenses = {
        'Apache-2.0':      LicenseOpen('Apache', version='2.0'),
        'APL-1.0':         LicenseOpen('Adaptive Public License', version='1.0'),
        'Artistic-2.0':    LicenseOpen('Artistic License', version='2.0'),
        'BSD-3-Clause':    LicenseOpen('BSD 3-clause "New" or "Revised" license'),
        'BSD-4-Clause':    LicenseOpen('BSD 4-clause "Original" license ("with advertising")'),
        'BSD-2-Clause':    LicenseOpen('BSD 2-clause "Simplified" or "FreeBSD"'),

        'BSL-1.0':         LicenseOpen('Boost Software License', version='1.0'),
        'CDDL-1.0':        LicenseOpen('Common Development and Distribution License'),
        'EPL-1.0':         LicenseOpen('Eclipse Public License', version='1.0'),
        'IPA':             LicenseOpen('IPA Font License'),
        'MIT':             LicenseOpen('MIT License'),
        'MPL-1.1':         LicenseOpen('Mozilla Public License', version='1.1'),
        'MPL-2.0':         LicenseOpen('Mozilla Public License', version='2.0'),
        'OFL-1.1':         LicenseOpen('Open Font License', version='1.1'),
        'OSL-3.0':         LicenseOpen('Open Software License', version='3.0'),
        'Python-2.0':      LicenseOpen('Python License', version='2.0'),
        'QPL-1.0':         LicenseOpen('Q Public License', version='1.0'),
        'UKOGL':           LicenseOpen('UK Open Government License'),
        'Libpng':          LicenseOpen('libpng license'), # libpng has its own license
        'Zlib':            LicenseOpen('zlib license'), # ZLIB has its own license

        'GPL-2.0-linux':   LicenseGPL('GPL', version='v2.0', with_exception=True),

        'GPL':             LicenseGPL('GPL', version='any version'),
        'GPL-2.0':         LicenseGPL('GPL', version='v2.0 only'),
        'GPL-2.0+':        LicenseGPL('GPL', version='v2.0 or later'),

        'GPL-2.0-with-autoconf-exception':  LicenseGPL('GPL with Autoconf exception',
                                                       version='v2.0', with_exception=True),
        'GPL-2.0-with-bison-exception':     LicenseGPL('GPL with Bison exception',
                                                       version='v2.0', with_exception=True),
        'GPL-2.0-with-classpath-exception': LicenseGPL('GPL with Classpath exception',
                                                       version='v2.0', with_exception=True),
        'GPL-2.0-with-font-exception':      LicenseGPL('GPL with Font exception',
                                                       version='v2.0', with_exception=True),
        'GPL-2.0-with-GCC-exception':       LicenseGPL('GPL with GCC Runtime Library exception',
                                                       version='v2.0', with_exception=True),

        'GPL-3.0':         LicenseGPL('GPL', version='v3.0 only'),
        'GPL-3.0+':        LicenseGPL('GPL', version='v3.0 or later'),

        'GPL-3.0-with-autoconf-exception':  LicenseGPL('GPL with Autoconf exception',
                                                       version='v3.0', with_exception=True),
        'GPL-3.0-with-bison-exception':     LicenseGPL('GPL with Bison exception',
                                                       version='v3.0', with_exception=True),
        'GPL-3.0-with-classpath-exception': LicenseGPL('GPL with Classpath exception',
                                                       version='v3.0', with_exception=True),
        'GPL-3.0-with-font-exception':      LicenseGPL('GPL with Font exception',
                                                       version='v3.0', with_exception=True),
        'GPL-3.0-with-GCC-exception':       LicenseGPL('GPL with GCC Runtime Library exception',
                                                       version='v3.0', with_exception=True),

        'LGPL':            LicenseLGPL('Lesser GPL', version='any version'),
        'LGPL-2.0':        LicenseLGPL('Lesser GPL', version='v2.0 only'),
        'LGPL-2.0+':       LicenseLGPL('Lesser GPL', version='v2.0 or later'),

        'LGPL-2.1':        LicenseLGPL('Lesser GPL', version='v2.1 only'),
        'LGPL-2.1+':       LicenseLGPL('Lesser GPL', version='v2.1 or later'),

        'LGPL-3.0':        LicenseLGPL('Lesser GPL', version='v3.0 only'),
        'LGPL-3.0+':       LicenseLGPL('Lesser GPL', version='v3.0 or later'),

        'Proprietary':          LicenseProprietarySource('Proprietary Source'),

        'Private':              LicensePrivate('Private'),
        'CODE NIGHTMARE GREEN': LicensePrivate('Code Nightmare Green'),
        }

def print_standard_licenses():
    keys = standard_licenses.keys()
    maxlen = len(max(keys, key=len))

    gpl_keys = []
    open_keys = []
    binary_keys = []
    private_keys = []
    other_keys = []

    for key in keys:
        license = standard_licenses[key]
        if license.is_gpl():
            gpl_keys.append((key, license))
        elif license.is_open():
            open_keys.append((key, license))
        elif license.is_proprietary_source():
            open_keys.append((key, license))
        elif license.is_binary():
            binary_keys.append((key, license))
        elif license.is_private():
            private_keys.append((key, license))
        else:
            other_keys.append((key, license))

    log('Standard licenses are:')

    for thing in (gpl_keys, open_keys, binary_keys, private_keys, other_keys):
        if thing:
            log()
            for key, license in sorted(thing):
                log('%-*s %r'%(maxlen, key, license))
    log()

def set_license(builder, co_label, license, license_file=None, not_built_against=False):
    """Set the license for a checkout.

    'co_label' is either a checkout label, or the name of a checkout.

        (Specifying a checkout label allows a domain name to be specified as
        well. The tag of the checkout label is ignored.)

    'license' must either be a License instance, or the mnemonic for one
    of the standard licenses.

    Some licenses (for instance, 'BSD-3-clause') require inclusion of their
    license file in binary distributions. 'license_file' allows the relevant
    file to be named (relative to the root of the checkout directory), and
    implies that said file should be included in all distributions.

    If 'not_built_against' is True, then it will be noted that nothing
    "builds against" this checkout. See 'set_nothing_builds_against()' for
    more information - this parameter is a useful convenience to save an
    extra call.
    """

    if isinstance(co_label, basestring):
        # Given a string, we'll assume it was a checkout name
        co_label = Label(LabelType.Checkout, co_label, tag='*')

    if isinstance(license, License):
        builder.db.set_checkout_license(co_label, license)
    else:
        builder.db.set_checkout_license(co_label,
                                                   standard_licenses[license])

    if license_file:
        builder.db.set_checkout_license_file(co_label, license_file)

    if not_built_against:
        set_nothing_builds_against(builder, co_label)

def set_license_for_names(builder, co_names, license):
    """A convenience function to set one license for several checkout names.

    Since this uses checkout names rather than labels, it is not domain aware.

    It calls 'set_license()' for each checkout name, passing it a checkout
    label constructed from the checkout name, with no domain.
    """
    # Try to stop the obvious mistake...
    if isinstance(co_names, basestring):
        raise GiveUp('Second argument to set_license_for_names() must be a sequence, not a string')

    for name in co_names:
        co_label = Label(LabelType.Checkout, name)
        set_license(builder, co_label, license)

def get_license(builder, co_label, absent_is_None=True):
    """Get the license for a checkout.

    If 'absent_is_None' is true, then if 'co_label' does not have an entry in
    the licenses dictionary, None will be returned. Otherwise, an appropriate
    GiveUp exception will be raised.

    This is a simple wrapper around builder.db.get_checkout_license.
    """
    return builder.db.get_checkout_license(co_label, absent_is_None)

def set_nothing_builds_against(builder, co_label):
    """Asserts that no packages "build against" this checkout.

    We assume that ``co_label`` is a checkout with a "propagating" license
    (i.e., some form of GPL license).

    This function tells the distribution/licensing system that there are no
    packages that build against (link against) this checkout, in a way which
    would cause GPL license "propagation".

    Typically used to mark checkouts that (just) provide or build:

        * an application (a program)
        * a kernel module
        * a text file (e.g., something to be placed in /etc)

    An example might be busybox, which is GPL-2 licensed, but which builds a
    set of independent programs.
    """
    builder.db.set_nothing_builds_against(co_label)

def set_license_not_affected_by(builder, this_label, co_label):
    """Asserts that the license for co_label does not affect this_label

    We assume that:

    1. 'this_label' is a package that depends (perhaps indirectly) on 'co_label',
       or is a checkout directly required by such a package.
    2. 'co_label' is a checkout with a "propagating" license (i.e., some form
       of GPL license).
    3. Thus by default the "GPL"ness would propagate from 'co_label' to
       'this_label' (and, if it is a package, to the checkouts it is (directly)
       built from).

    However, this function asserts that, in fact, this is not true. Our
    checkout is (or our checkouts are) not built in such a way as to cause the
    license for 'co_label' to propagate.

    Or, putting it another way, for a normal GPL license, we're not linking
    with anything from 'co_label', or using its header files, or copying GPL'ed
    files from it, and so on.

    If 'co_label' is under LGPL, then that would reduce to saying we're not
    static linking against 'co_label' (or anything else not allowed by the
    LGPL).

    Note that we may be called before 'co_label' has registered its license, so
    we cannot actually check that 'co_label' has a propagating license (or,
    indeed, that it exists or is depended upon by 'pkg_label').

    This is a simple wrapper around
    builder.db.set_license_not_affected_by.
    """
    builder.db.set_license_not_affected_by(this_label, co_label)

def get_not_licensed_checkouts(builder):
    """Return the set of all checkouts which do not have a license.

    (Actually, a set of checkout labels, with the label tag "/checked_out").
    """
    all_checkouts = builder.all_checkout_labels()
    result = set()
    checkout_has_license = builder.db.checkout_has_license
    for co_label in all_checkouts:
        if not checkout_has_license(co_label):
            result.add(normalise_checkout_label(co_label))
    return result

def get_gpl_checkouts(builder):
    """Return a set of all the GPL licensed checkouts.

    That's checkouts with any sort of GPL license.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_gpl():
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_open_checkouts(builder):
    """Return a set of all the open licensed checkouts.

    That's checkouts with any sort of GPL or open license.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_open():
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_open_not_gpl_checkouts(builder):
    """Return a set of all the open licensed checkouts that are not GPL.

    Note sure why anyone would want this, but it's easy to provide.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.category == 'open-source':
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_implicit_gpl_checkouts(builder):
    """Find all the checkouts to which GPL-ness propagates.

    Returns a tuple, (result, because), where:

    * 'result' is a set of the checkout labels that are implicitly made "GPL"
      by propagation, and
    * 'because' is a dictionary linking each such label to a set of strings
       explaining the reason for the labels inclusion
    """

    # There are clearly two ways we can do this:
    #
    # 1. For each checkout, follow its dependencies until we find something
    #    that is non-system GPL, or we don't (obviously, finding one such
    #    is enough).
    #
    # 2. For each non-system GPL checkout, find everything that depends upon
    #    it and mark it as propagated-to
    #
    # In either case, it is definitely worth checking to see if there are
    # *any* non-system GPL checkouts.
    #
    # If we do (1) then we may need to traverse the entire dependency tree
    # for each and every checkout in it (e.g., if there are no non-system
    # GPL licensed checkouts).
    #
    # If we do (2), then we do nothing if there are no non-system GPL
    # checkouts. For each that there is, we do need to traverse the entire
    # dependency tree, but we can hope that this is for significantly fewer
    # cases than in (1).
    #
    # Also, it is possible that we may have "blockers" inserted into the tree,
    # which truncate such a traversal (I'm not 100% sure about this yet).
    #
    # Regardless, approach (2) seems the more sensible.

    all_gpl_checkouts = get_gpl_checkouts(builder)

    # Localise for our loop
    get_checkout_license = builder.db.get_checkout_license
    get_license_not_affected_by = builder.db.get_license_not_affected_by
    get_nothing_builds_against = builder.db.get_nothing_builds_against
    ruleset = builder.ruleset


    def add_if_not_us_or_gpl(our_co, this_co, result, because, reason):
        """Add 'this_co' to 'result' if it is not 'our_co' and not GPL itself.

        In which case, also add 'this_co':'reason' to 'because'

        Relies on 'our_co' having a wildcarded label tag.
        """
        if our_co.just_match(this_co):
            # OK, that's just some variant on ourselves
            logger.debug('BUT %s is our_co'%this_co)
            return
        this_license = get_checkout_license(this_co, absent_is_None=True)
        if this_license and this_license.is_gpl():
            logger.debug('BUT %s is already GPL'%this_co)
            return
        lbl = this_co.copy_with_tag('*')
        result.add(lbl)
        if lbl in because:
            because[lbl].add(reason)
        else:
            because[lbl] = set([reason])
        logger.debug('ADD %s'%lbl)

    result = set()              # Checkouts implicitly affected
    because = {}                # checkout -> what it depended on that did so
    logger.debug()
    logger.debug('Finding implicit GPL checkouts')
    for co_label in all_gpl_checkouts:
        logger.debug('.. %s'%co_label)
        license = get_checkout_license(co_label)
        if not license.propagates():
            logger.debug('     has a link-exception of some sort - ignoring it')
            continue
        if get_nothing_builds_against(co_label):
            logger.debug('     nothing builds against this - ignoring it')
            continue
        depend_on_this = required_by(ruleset, co_label)
        for this_label in depend_on_this:
            # We should have a bunch of package labels (possibly the same
            # package present with different tags), plus quite likely some
            # variants on our own checkout label, and sometimes other stuff
            logger.debug('     %s'%this_label)
            if this_label.type == LabelType.Package:

                not_affected_by = get_license_not_affected_by(this_label)
                if co_label in not_affected_by:
                    logger.debug('NOT against %s'%co_label)
                    continue

                # OK, what checkouts does that imply?
                pkg_checkouts = builder.checkouts_for_package(this_label)
                logger.debug('EXPANDS to %s'%(label_list_to_string(pkg_checkouts)))

                for this_co in pkg_checkouts:
                    logger.debug('         %s'%this_label)

                    not_affected_by = get_license_not_affected_by(this_co)
                    if co_label in not_affected_by:
                        logger.debug('NOT against %s'%co_label)
                        continue
                    # We know that our original 'co_label' has type '/*`
                    add_if_not_us_or_gpl(co_label, this_co, result, because,
                                         '%s depends on %s'%(this_label.copy_with_tag('*'),
                                                             co_label))
            elif this_label.type == LabelType.Checkout:
                # We know that our original 'co_label' has type '/*`
                add_if_not_us_or_gpl(co_label, this_label, result, because,
                                     '%s depends on %s'%(this_label.copy_with_tag('*'),
                                                         co_label))
            else:
                # Deployments don't build stuff, so we can ignore them
                logger.debug('IGNORE')
                continue
    return result, because

def get_prop_source_checkouts(builder):
    """Return a set of all the "proprietary source" licensed checkouts.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    prop_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_proprietary_source():
            prop_licensed.add(co_label)
    return prop_licensed

def get_binary_checkouts(builder):
    """Return a set of all the "binary" licensed checkouts.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    binary_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_binary():
            binary_licensed.add(co_label)
    return binary_licensed

def get_private_checkouts(builder):
    """Return a set of all the "private" licensed checkouts.
    """
    all_checkouts = builder.all_checkout_labels()
    get_checkout_license = builder.db.get_checkout_license
    private_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_private():
            private_licensed.add(co_label)
    return private_licensed

def checkout_license_allowed(builder, co_label, categories):
    """Does this checkout have a license in the given categories?

    Returns True if the checkout has a license that is in any of the
    given categories, or if it does not have a license.

    Returns False if it is licensed, but its license is not in any of
    the given categories.
    """
    license = builder.db.get_checkout_license(co_label, absent_is_None=True)
    if license is None or license.category in categories:
        return True
    else:
        return False

def get_license_clashes(builder, implicit_gpl_checkouts):
    """Return clashes between actual license and "implicit GPL" licensing.

    ``get_implicit_gpl_checkouts()`` returns those checkouts that are
    implicitly "made" GPL by propagation. However, if the checkouts concerned
    were already licensed with either "binary" or "private" licenses, then it
    is likely that the caller would like to know about it, as it is probably
    a mistake (or at best an infelicity).

    This function returns two sets, (bad_binary, bad_private), of checkouts
    named in ``implicit_gpl_checkouts`` that have an explicit "binary" or
    "private" license.
    """
    bad_binary = set()
    bad_private = set()

    get_checkout_license = builder.db.get_checkout_license
    for co_label in implicit_gpl_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license is None:
            continue
        elif license.is_binary():
            bad_binary.add(co_label)
        elif license.is_private():
            bad_private.add(co_label)

    return bad_binary, bad_private

def report_license_clashes(builder, report_binary=True, report_private=True, just_for=None):
    """Report any license clashes.

    This wraps get_implicit_gpl_checkouts() and check_for_license_clashes(),
    plus some appropriate text reporting any problems.

    It returns True if there were any clashes, False if there were not.

    It reports clashes with "binary" licenses if 'report_binary' is True.

    It reports clashes with "private" licenses if 'report_private' is True.

    If both are False, it is silent.

    If 'just_for' is None, it looks at all the implicit GPL checkouts.
    Otherwise, it only considers those labels in 'just_for' that are also
    implicitly GPL.
    """
    implicit_gpl, because = get_implicit_gpl_checkouts(builder)

    if not implicit_gpl:
        return False

    if just_for:
        implicit_gpl = implicit_gpl.intersection(just_for)

    if not implicit_gpl:
        return False

    bad_binary, bad_private = get_license_clashes(builder, implicit_gpl)

    if not bad_binary and not bad_private:
        return False

    def report(co_label):
        license = get_checkout_license(co_label)
        reasons = because[co_label]
        header = '* %-*s is %r, but is implicitly GPL because:'%(maxlen, co_label, license)
        log(wrap(header, subsequent_indent='  '))
        log()
        for reason in sorted(reasons):
            log('  - %s'%reason)
        log()

    if report_binary or report_private:
        log()
        log('The following GPL license clashes occur:')
        log()

        maxlen = 0
        if report_binary:
            for label in bad_binary:
                length = len(str(label))
                if length > maxlen:
                    maxlen = length
        if report_private:
            for label in bad_private:
                length = len(str(label))
                if length > maxlen:
                    maxlen = length

        get_checkout_license = builder.db.get_checkout_license

        if report_binary:
            for co_label in sorted(bad_binary):
                report(co_label)

        if report_private:
            for co_label in sorted(bad_private):
                report(co_label)

    return True

def licenses_in_role(builder, role):
    """Given a role, what licenses are used by the packages (checkouts) therein?

    Returns a set of License instances. May also include None in the values in
    the set, if some of the checkouts are not licensed.
    """
    licenses = set()
    get_checkout_license = builder.db.get_checkout_license

    lbl = Label(LabelType.Package, "*", role, "*", domain="*")
    all_rules = builder.ruleset.rules_for_target(lbl)

    for rule in all_rules:
        pkg_label = rule.target
        checkouts = builder.checkouts_for_package(pkg_label)
        for co_label in checkouts:
            license = get_checkout_license(co_label, absent_is_None=True)
            licenses.add(license)

    return licenses

def get_license_clashes_in_role(builder, role):
    """Find license clashes in the install/ directory of 'role'.

    Returns two dictionaries (binary_items, private_items)

    'binary_items' is a dictionary of {checkout_label : binary_license}

    'private_items' is a dictionary of {checkout_label : private_license}

    If private_items has content, then there is a licensing clash in the given
    role, as one cannot do a binary distribution of both "binary" and "private"
    licensed content in the same "install" directory.
    """
    binary_items = {}
    private_items = {}

    get_checkout_license = builder.db.get_checkout_license

    lbl = Label(LabelType.Package, "*", role, "*", domain="*")
    all_rules = builder.ruleset.rules_for_target(lbl)

    for rule in all_rules:
        pkg_label = rule.target
        checkouts = builder.checkouts_for_package(pkg_label)
        for co_label in checkouts:
            license = get_checkout_license(co_label, absent_is_None=True)
            if license:
                if license.is_binary():
                    binary_items[normalise_checkout_label(co_label)] = license
                elif license.is_private():
                    private_items[normalise_checkout_label(co_label)] = license

    return binary_items, private_items

def report_license_clashes_in_role(builder, role, just_report_private=True):
    """Report license clashes in the install/ directory of 'role'.

    Basically, this function allows us to be unhappy if there are a mixture of
    "binary" and "private" things being put into the same "install/" directory.

    If 'just_report_private' is true, then we will only talk about the
    private entities, otherwise we'll report the "binary" licensed packages
    that end up there as well.

    If there was a clash reported, we return True, and otherwise we return
    False.
    """
    binary_items, private_items = get_license_clashes_in_role(builder, role)

    if not (binary_items and private_items):
        return False

    binary_keys = binary_items.keys()
    private_keys = private_items.keys()

    maxlen = 0
    for label in private_keys:
        length = len(str(label))
        if length > maxlen:
            maxlen = length

    if just_report_private:
        log('There are both binary and private licenses in role %s:'%(role))
        for key in sorted(private_keys):
            log('* %-*s is %r'%(maxlen, key, private_items[key]))
    else:
        for label in binary_keys:
            length = len(str(label))
            if length > maxlen:
                maxlen = length
        log('There are both binary and private licenses in role %s:'%(role))
        for key in sorted(binary_keys):
            log('* %-*s is %r'%(maxlen, key, binary_items[key]))
        for key in sorted(private_keys):
            log('* %-*s is %r'%(maxlen, key, private_items[key]))

    return True
