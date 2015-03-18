# Frequently asked questions about muddle #

_(including also "Infrequently asked questions we'd like to mention")_

## How do I: Update all packages from source control? ##

```
$ muddle update _all
```

Will pull the latest revision of every checkout from the remote repository.

## Set an environment variable in a build description? ##

### For deployment ###

```
muddled.deployment.set_env(builder, deployment_name, name, value)
```
can be used to set the environment variable "name" to "value" in the named deployment.

> (I assume this means "when running instruction files during deployment)

### For a single package ###

```
muddled.pkg.set_env_for_package(builder, package_name, package_roles, name, value)
```
can be used to set the environment variable "name" to "value" in the given package built in the given roles.

### For several packages, using wildcarding ###

For instance, if I want to set the toolchain and architecture for use in my Makefiles.

```
# Both Linux and Busybox share some environment we'd like to specify
# only once. The mechanism for doing this is a little bit cunning
label = muddled.depend.label_from_string('package:*{omap}/*') # i.e., all our packages
# We can retrieve the "environment" (technically, an environment Store)
# that will be used for that label - this will create one if it doesn't
# exist yet
env = builder.invocation.get_environment_for(label)
# And adding values to that is simple
env.set("OMAP_CROSS_COMPILE", "/opt/codesourcery/arm-2008q3/bin/arm-none-linux-gnueabi-")
env.set("OMAP_ARCH", "arm")
```

## Why aren't MUDDLE\_CROSS\_COMPILE and MUDDLE\_ARCH standard parts of muddle? ##

(or, why is the previous FAQ entry written at all)

When these FAQs were written, I still wasn't sure if/how to incorporate setting cross-compilation information, nor whether I had a list of everything that might be wanted. I am increasingly coming to the conclusion that MUDDLE\_CROSS\_COMPILE and MUDDLE\_ARCH are "semi standard" environment variables we should be supporting, possibly along with MUDDLE\_KERNELDIR (this last, or something like it, is automatically set by the muddle Python module that builds a "local" Linux kernel).

It is quite likely that these will be standardised in the near future, at which time a nicer way of setting them will probably also be provided (and some examples).

## How do I: Provoke "make menuconfig" for Linux or Busybox? ##

When setting up a Linux, Busybox or similar build, the norm is to make the "configure" step copy a known-suitable configuration file to ".config". The normal user does not want to change that.

However, when developing a system, it can be useful/necessary to run the "menuconfig" stage. One wants to do this with the appropriate environment, however, which one has gone to some care to set up in the muddle build description.

The correct way to do this is to use "muddle runin" -- for instance, following on from the example above:

```
$ muddle runin 'package:linux_kernel{omap}/*' 'make menuconfig ARCH=$OMAP_ARCH CROSS_COMPILE=$OMAP_CROSS_COMPILE'
```

You may then want to do:

```
$ muddle runin 'package:linux_kernel{omap}/*' 'make uImage ARCH=$OMAP_ARCH CROSS_COMPILE=$OMAP_CROSS_COMPILE'
```

to rebuild immediately **with that configuration**, or possibly the (simpler)

```
$ muddle rebuild linux_kernel{omap}
```

depending on exactly how your Makefile is written.

## How do I: "fold" deployments? ##

Consider that I have two packages ("rootfs" and "optional") which I want to deploy into the same deployment directory. Specifically, I want "rootfs" to end up in "deploy/rootfs" and "optional" to end up in "deploy/rootfs/opt/packages".

> _My previous solution to this was wrong, as it relied on illegal labels as part of an intermediate stage, and thus worked, at best, by coincidence. A proper solution will be forthcoming when I've worked one out._

## How do I: test muddle? ##

Most muddle testing is done by testing individual builds.

However, there are an increasing number of doctests in docstrings, and a limited number of "unit" tests (limited but still valuable). I run these with "nose" - for instance, after `cd`'ing to the muddle checkout directory:

```
$ nosetests --with-doctest
....................
----------------------------------------------------------------------
Ran 21 tests in 0.286s

OK
```

## Why aren't Labels singletons? ##

Labels are fundamental to the working of muddle, and it could perhaps be asked why it is possible to create two identical Labels, when they could be instead be implemented as singletons (i.e., all Label instances that compare the same are indeed the same object).

The first answer is probably just that it was easier. Making a singleton class is more work, and like most things that are more work, it's generally better not to bother until you know you have to.

It's not common in Python to expect `is` comparisons to work for user classes, so there's no general incentive to make Label instance singleton, and indeed, the general Python wisdom is that singletons are often ill advised.

There's a slight concern in that Label instances (let's just call them "labels" from now on) can have flags which don't affect comparison, so two "identical" labels could actually differ. In practice, those flags ("system defined" and "transient") are set by muddle itself. I don't believe that the particular labels concerned are created more than once, and if they were, I don't believe this is system-critical (raise an issue if you know otherwise!).

Moreover, I've recently been implementing sub-builds ("domains" - see [issue 62](https://code.google.com/p/muddle/issues/detail?id=62)). In a sub-build, a whole other dependency tree is being imported. When import has finished, the labels in the sub-tree will have their domain names set (the syntax of a label being extended to "`type:(domain)name{role}/tag[flags]`" - ignore this until you need to know about it). It turns out to be **very useful** that I can rely on the labels introduced as the sub-build is being imported being separate from those in the main build, _even if they transiently have the same parts_. This means I can do the import, and then sweep through the sub-build labels adding the new domain name to them. If labels were singletons, I would instead have to sweep through the sub-build _replacing_ each label with a new label (and thus I would need to recreate each label _container_, which is an entirely different order of task).

This is, perhaps, an icky way to do the job, but it is _simple_, and that's very reassuring.

This also, perhaps, makes it clearer why we say "treat labels as immutable", but don't bother to enfore it - it's very Pythonic (!) to allow people to shoot themselves in the foot but assume they won't unless they have to.


# Common pitfalls #

(or, daft things I've now learnt not to do)

## Making a Makefile.muddle "too clever" ##

Since muddle itself takes care of dependencies between different phases of the build process, a Makefile.muddle should not contain:

```
install: all
```

since this will cause the muddle "install" step to rebuild the software. If that needed doing, muddle would have done it directly.

### Absolute filenames in instructions.xml ###

When writing an instructions.xml file, beware of things like:

```
 <mknod> 
   <name>/lib/udev/devices/console</name>
   <uid>0</uid>
   <gid>0</gid>
   <type>char</type>
   <major>5</major>
   <minor>1</minor>
   <mode>0600</mode>
 </mknod>
```

because that "/lib/udev/devices/console" is interpreted relative to your machine - in other words, it will try to create the node on the host. It is important in this case to leave off the initial "/". This is in contrast to the cases where 

&lt;filespec&gt;

 elements are used -- the 

&lt;root&gt;

 within a 

&lt;filespec&gt;

 is always relative to the muddle tree.

NB: This has been raised as [issue 54](https://code.google.com/p/muddle/issues/detail?id=54).

### Don't patch source code in the checkout directory when building ###

Sometimes you will want to build patched source. Your natural tendency will be to use the 'config:' target in your makefile to patch the source code your checkout produced. This is wrong.

Suppose your checkout is used by two packages: in which order are they built? Which sees the patched code and which the unpatched code? How do we distclean a package for reconfiguration? Who knows?

If a package wants to patch source code, you should copy the source code to your object directory and patch it there. If no package will ever want the unpatched source code, your checkout should itself apply the patches on checkout - there isn't currently a checkout class which does this, but there should be (feel free to write one!).

You will think this is restrictive, but it's either this or having a baroque set of rules for which packages see which checkouts (and which patches are relative to which patched source). Neither of these is terribly palatable and this is the least bad alternative.