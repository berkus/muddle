"""
Actions and mechanisms relating to distributing build trees
"""

from muddled.depend import Action, Rule
from muddled.utils import MuddleBug, LabelTag

class DistributePackage(Action):
    """
    An action that distributes a package.

    It copies the the obj/ and install/ directories for the package, as well
    as any instructions (and anything else I haven't yet thought of).
    """

    def build_label(self, builder, label):
        print 'DistributePackage %s'%label

        # 1. Get the target dir from the builder.invocation
        # 2. Get the actual directory of the package obj/ and install/
        #    directories
        # 3. Use copywithout to copy the obj/ and install/ directories over
        # 4. Set the appropriate tags in the target .muddle/ directory
        # 5. Set the /distributed tag on the package

class DistributeCheckout(Action):
    """
    An action that distributes a checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)
    """

    def __init__(self, copy_vcs_dir=False):
        self.copy_vcs_dir = copy_vcs_dir

    def build_label(self, builder, label):
        print 'DistributeCheckout %s (%s VCS)'%(label,
                'without' if self.copy_vcs_dir else 'with')

        # 1. Get the target dir from the builder.invocation
        # 2. Get the actual directory of the checkout
        # 3. If we're not doing copy_vcs_dir, find the VCS for this
        #    checkout, and from that determine its VCS dir, and make
        #    that our "without" string
        # 4. Do a copywithout to do the actual copy, suitably ignoring
        #    the VCS directory if necessary.
        # 5. Set the appropriate tags in the target .muddle/ directory
        # 6. Set the /distributed tag on the checkout

def distribute_checkout(builder, label, copy_vcs_dir=False):
    """Request the distribution of the given checkout.

    'label' must be a checkout label, but the tag is not important.

    By default, don't copy any VCS directory.
    """
    if label.type != LabelType.Checkout:
        raise MuddleBug('Attempt to use non-checkout label %s for a distribute checkout rule'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributeCheckout(copy_vcs_dir)
    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

def distribute_package(builder, label):
    """Request the distribution of the given package.

    'label' must be a package label, but the tag is not important.
    """
    if label.type != LabelType.Package:
        raise MuddleBug('Attempt to use non-package label %s for a distribute package rule'%label)

    source_label = label.copy_with_tag(LabelTag.PostInstalled)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributePackage()
    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

