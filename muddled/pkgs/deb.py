"""
Some code which sneakily steals binaries from Debian/Ubuntu.

Quite a lot of code for embedded systems can be grabbed pretty much
directly from the relevant Ubuntu binary packages - this won't work
with complex packages like exim4 without some external frobulation,
since they have relatively complex postinstall steps, but it works
quite nicely for things like util-linux, and provided you're on a
supported architecture it's a quick route to externally maintained
binaries which actually work and it avoids having to build
absolutely everything in your linux yourself.

This package allows you to 'build' a package from a source file in
a checkout which is a .deb. We run dpkg with enough force options
to install it in the relevant install directory.

You still need to provide any relevant instruction files
(we'll register <filename>.instructions.xml for you automatically
if it exists).

We basically ignore the package database (there is one, but
it's always empty and stored in the object directory).
"""

import muddled.pkg as pkg
import muddled.db as db
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import os
import re
import stat
import muddled.rewrite as rewrite

def rewrite_links(inv, label):
    obj_dir = inv.package_obj_path(label.name, label.role, domain = label.domain)

    # Now, we walk obj_dir. For every symlink we find to '/' something, 
    # rewrite it to be to 'obj_dir/' something.
    stack = [ ]

    the_re = re.compile(r"(.*)\.la$")
    
    stack.append(".")

    while len(stack) > 0 :
        current = stack.pop()
        
        object_name = os.path.join(obj_dir, current)
        
        st_rec = os.lstat(object_name)
        if stat.S_ISDIR(st_rec.st_mode):
            # It's a directory.
            things_here = os.listdir(object_name)
            for thing in things_here:
                new_thing = os.path.join(current, thing)
                stack.append(new_thing)

        elif stat.S_ISLNK(st_rec.st_mode):
            # Read the link.
            link_target = os.readlink(object_name)

            os.unlink(object_name)
            # Prepend the object dir.
            if (len(link_target) > 0 and 
                link_target[0] == '/'):
                link_target = link_target[1:]
                new_link_target = os.path.join(obj_dir, link_target)
            else:
                # The link was relative to the current directory
                (base, leaf) = os.path.split(current)
                new_link_target = os.path.join(obj_dir, 
                                               base, link_target)

            os.symlink(new_link_target, object_name)
            # We used to delete .la files here, but now rewrite()
            # rewrites them. Which is much more friendly :-)
        else:
            # Boring. ignore it.
            pass




def extract_into_obj(inv, co_name, label, pkg_file):
    co_dir = inv.checkout_path(co_name, domain = label.domain)
    obj_dir = inv.package_obj_path(label.name, label.role, domain = label.domain)
    dpkg_cmd = "dpkg-deb -X %s %s"%(os.path.join(co_dir, pkg_file), 
                                    os.path.join(obj_dir, "obj"))
    utils.run_cmd(dpkg_cmd)

    # Now install any include or lib files ..
    installed_into = os.path.join(obj_dir, "obj")
    inc_dir = os.path.join(obj_dir, "include")
    lib_dir = os.path.join(obj_dir, "lib")
    lib_dir = os.path.join(obj_dir, "share")
    
    utils.ensure_dir(inc_dir)
    utils.ensure_dir(lib_dir)
    
    # Copy everything in usr/include ..
    for i in (("include", "include"), ("lib", "lib"), 
              ("usr/include", "include"), ("usr/lib", "lib"), 
              ("usr/share", "share")):
        (src,dst) = i
        src_path = os.path.join(installed_into, src)    
        dst_path= os.path.join(obj_dir, dst)

        if (os.path.exists(src_path) and os.path.isdir(src_path)):
            utils.copy_without(src_path,
                               dst_path,
                               without = None)
    

class DebDevDependable(PackageBuilder):
    """
    Use dpkg to extract debian archives into obj/include and obj/lib
    directories so we can use them to build other packages.
    """
    def __init__(self, name, role, co, pkg_name, pkg_file, 
                 instr_name = None,
                 postInstallMakefile = None, 
                 nonDevCoName = None,
                 nonDevPkgFile = None):
        """
        As for a DebDependable, really.
        """
        PackageBuilder.__init__(self, name, role)
        self.co_name = co
        self.pkg_name = pkg_name
        self.pkg_file = pkg_file
        self.nonDevPkgFile = nonDevPkgFile
        self.nonDevCoName = nonDevCoName
        self.instr_name = instr_name
        self.post_install_makefile = postInstallMakefile
        

    def ensure_dirs(self, builder, label):
        inv = builder.invocation

        if not os.path.exists(inv.checkout_path(self.co_name, domain = label.domain)):
            raise utils.Failure("Path for checkout %s does not exist."%self.co_name)

        utils.ensure_dir(os.path.join(inv.package_obj_path(label.name, label.role, 
                                                           domain = label.domain), "obj"))

    def build_label(self, builder, label):
        """
        Actually install the dev package.
        """
        self.ensure_dirs(builder, label)

        tag = label.tag
        
        if (tag == utils.Tags.PreConfig):
            # Nothing to do
            pass
        elif (tag == utils.Tags.Configured):
            pass
        elif (tag == utils.Tags.Built):
            pass
        elif (tag == utils.Tags.Installed):
            # Extract into /obj
            inv = builder.invocation
            extract_into_obj(inv, self.co_name, label, self.pkg_file)
            if (self.nonDevPkgFile is not None):
                extract_into_obj(inv, self.nonDevCoName, label, self.nonDevPkgFile)

            # Now we rewrite all the absolute links to be relative to the install
            # directory.
            rewrite_links(inv, label)
                

        elif (tag == utils.Tags.PostInstalled):
            if self.post_install_makefile is not None:
                inv = builder.invocation
                co_path =inv.checkout_path(self.co_name, domain = label.domain) 
                os.chdir(co_path)
                utils.run_cmd("make -f %s %s-postinstall"%(self.post_install_makefile, 
                                                           label.name))

            # .. and now we rewrite any pkgconfig etc. files left lying
            # about.
            obj_path = builder.invocation.package_obj_path(label.name, 
                                                           label.role, 
                                                           domain = label.domain)
            print "> Rewrite .pc and .la files in %s"%(obj_path)
            rewrite.fix_up_pkgconfig_and_la(builder, obj_path)

        elif (tag == utils.Tags.Clean or tag == utils.Tags.DistClean):
            # Just remove the object directory.
            inv = builder.invocation
            utils.recursively_remove(inv.package_obj_path(label.name, label.role, 
                                                          domain = label.domain))
        else:
            raise utils.Error("Invalid tag specified for deb pkg %s"%(label))



class DebDependable(PackageBuilder):
    """
    Use dpkg to extract debian archives from the given
    checkout into the install directory.
    """

    def __init__(self, name, role, co, pkg_name, pkg_file,
                 instr_name = None, 
                 postInstallMakefile = None):
        """
        * co - is the checkout name in which the package resides.
        * pkg_name - is the name of the package (dpkg needs it)
        * pkg_file - is the name of the file the package is in, relative to
          the checkout directory.
        * instr_name - is the name of the instruction file, if any.
        * postInstallMakefile - if not None::
            
            make -f postInstallMakefile <pkg-name>

          will be run at post-install time to make links, etc.
        """
        PackageBuilder.__init__(self, name, role)
        self.co_name = co
        self.pkg_name = pkg_name
        self.pkg_file = pkg_file
        self.instr_name = instr_name
        self.post_install_makefile = postInstallMakefile


    def ensure_dirs(self, builder, label):
        inv = builder.invocation

        if not os.path.exists(inv.checkout_path(self.co_name, domain = label.domain)):
            raise utils.Failure("Path for checkout %s does not exist."%self.co_name)

        utils.ensure_dir(inv.package_install_path(label.name, label.role, 
                                                  domain = label.domain))
        utils.ensure_dir(inv.package_obj_path(label.name, label.role,
                                              domain = label.domain))
        
    def build_label(self, builder, label):
        """
        Build the relevant label.
        """
        
        self.ensure_dirs(builder, label)
        
        tag = label.tag
        
        if (tag == utils.Tags.PreConfig):
            # Nothing to do.
            pass
        elif (tag == utils.Tags.Configured):
            pass
        elif (tag == utils.Tags.Built):
            pass
        elif (tag == utils.Tags.Installed):
            # Concoct a suitable dpkg command.
            inv = builder.invocation
            
            # Extract into the object directory .. so I can depend on them later.
            # - actually, Debian packaging doesn't work like that. Rats.
            #  - rrw 2009-11-24
            #extract_into_obj(inv, self.co_name, label, self.pkg_file)            

            inst_dir = inv.package_install_path(label.name, label.role, 
                                                domain = label.domain)
            co_dir = inv.checkout_path(self.co_name, domain = label.domain)

            # Using dpkg doesn't work here for many reasons.
            dpkg_cmd = "dpkg-deb -X %s %s"%(os.path.join(co_dir, self.pkg_file), 
                                            inst_dir)
            utils.run_cmd(dpkg_cmd)
            
            # Pick up any instructions that got left behind
            instr_file = self.instr_name
            if (instr_file is None):
                instr_file = "%s.instructions.xml"%(label.name)
            
            instr_path = os.path.join(co_dir, instr_file)

            if (os.path.exists(instr_path)):
                # We have instructions ..
                ifile = db.InstructionFile(instr_path)
                ifile.get()
                self.builder.instruct(label.name, label.role, ifile)
        elif (tag == utils.Tags.PostInstalled):
            if self.post_install_makefile is not None:
                inv = builder.invocation
                co_path =inv.checkout_path(self.co_name, domain =  label.domain) 
                os.chdir(co_path)
                utils.run_cmd("make -f %s %s-postinstall"%(self.post_install_makefile, 
                                                           label.name))
        elif (tag == utils.Tags.Clean or tag == utils.Tags.DistClean):#
            inv = builder.invocation
            admin_dir = os.path.join(inv.package_obj_path(label.name, label.role, 
                                     domain = label.domain))
            utils.recursively_remove(admin_dir)
        else:
            raise utils.Error("Invalid tag specified for deb pkg %s"%(label))

def simple(builder, coName, name, roles, 
           depends_on = [ ],
           pkgFile = None, debName = None, instrFile = None, 
           postInstallMakefile = None, isDev = False, 
           nonDevCoName = None, 
           nonDevPkgFile = None):
    """
    Build a package called 'name' from co_name / pkg_file with
    an instruction file called instr_file. 

    'name' is the name of the muddle package and of the debian package.
    if you want them different, set deb_name to something other than
    None.
    
    Set isDev to True for a dev package, False for an ordinary
    binary package. Dev packages are installed into the object
    directory where MUDDLE_INC_DIRS etc. expects to look for them.
    Actual packages are installed into the installation directory
    where they will be transported to the target system.
    """
    if (debName is None):
        debName = name


    if (pkgFile is None):
        pkgFile = debName

    for r in roles:
        if isDev:
            dep = DebDevDependable(name, r, coName, debName, 
                                   pkgFile, instrFile, 
                                   postInstallMakefile, 
                                   nonDevCoName = nonDevCoName,
                                   nonDevPkgFile = nonDevPkgFile)
        else:
            dep = DebDependable(name, r, coName, debName, 
                                pkgFile, instrFile, 
                                postInstallMakefile)
            
        pkg.add_package_rules(builder.invocation.ruleset, 
                              name, r, dep)
        # We should probably depend on the checkout .. .
        pkg.package_depends_on_checkout(builder.invocation.ruleset, 
                                        name, r, coName, dep)
        # .. and some other packages. Y'know, because we can ..
        pkg.package_depends_on_packages(builder.invocation.ruleset, 
                                        name, r, utils.Tags.PreConfig, 
                                        depends_on)
        
    # .. and that's it.

def dev(builder, coName, name, roles,
        depends_on = [ ],
        pkgFile = None, debName = None,
        nonDevCoName = None,
        nonDevDebName = None,
        instrFile = None,
        postInstallMakefile = None):
    """
    A wrapper for 'deb.simple', with the "idDev" flag set True.

    nonDevCoName  is the checkout in which the non-dev version of the package resides.
    nonDevDebName is the non-dev version of the package; this is sometimes needed
                  because of the odd way in which debian packages the '.so' link
                  in the dev package and the sofiles themselves into the non-dev.

    """
    simple(builder, coName, name, roles, depends_on,
           pkgFile, debName, instrFile, postInstallMakefile,
           nonDevCoName = nonDevCoName,
           nonDevPkgFile = nonDevDebName, 
           isDev = True)
          

def deb_prune(h):
    """
    Given a cpiofile heirarchy, prune it so that only the useful 
    stuff is left.
    
    We do this by lopping off directories, which is easy enough in
    cpiofile heirarchies.
    """
    h.erase_target("/usr/share/doc")
    h.erase_target("/usr/share/man")



# End file.
    

        
        

