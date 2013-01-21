"""
Tests the rest of muddled.
"""

import depend
import utils
import version_control
import env_store
import mechanics
import filespec
import pkg
import subst
import cpiofile

from depend import Label

def unit_test():
    print "> cpio"
    cpio_unit_test()
    print "> Utils"
    utils_unit_test()
    print "> env"
    env_store_unit_test()
    print "> subst"
    subst_unit_test()
    print "> filespec"
    filespec_unit_test()
    print "> VCS"
    vcs_unit_test()
    print "> Depends"
    depend_unit_test()
    print "> Mechanics"
    mechanics_unit_test()
    print "> All done."

def cpio_unit_test():
    """
    A brief test of the cpio module. Uses ``/tmp/test.cpio``.
    """

    #f1 = cpiofile.file_from_fs("/var/run/motd")
    f1 = cpiofile.file_from_fs(__file__)  # A file we're fairly sure exists
    f1.rename("foo")
    f2 = cpiofile.file_for_dir("bar")
    f3 = cpiofile.File()
    f3.rename("bar/baz")
    f3.set_contents("Hello, World!\n")

    arc = cpiofile.Archive()
    #arc.add_files([f1, f2, f3])
    arc.add_files([f1])
    arc.render("/tmp/test.cpio", True)
    # Now just make sure that cpio can read the data

    rv = utils.run_cmd("cpio -i --to-stdout </tmp/test.cpio")

def env_store_unit_test():
    """
    Test some bits of the environment store mechanism.
    """

    ee = env_store.EnvExpr(env_store.EnvExpr.StringType, "a")
    ee.append("b")
    ee.append("c")

    assert ee.to_sh(True) == '"a""b""c"'
    assert ee.to_sh(False) == 'abc'

    ee = env_store.EnvExpr(env_store.EnvExpr.RefType, "a")
    assert ee.to_sh(True) == '"$a"'

    # Now try something a bit more complex ..
    ee = env_store.EnvExpr(env_store.EnvExpr.CatType)
    ee.append_str("Fish")
    ee.append_ref("Soup")
    ee.append_str("Wombat")

    assert ee.to_sh(True) == '"Fish""$Soup""Wombat"'

    assert ee.to_value(env = { "Soup" : "X"}) == "FishXWombat"

    lst = ee.to_py(env_var = "env")

    assert len(lst) == 3

    assert lst[0] == '"Fish"'
    assert lst[1] == 'env["Soup"]'
    assert lst[2] == '"Wombat"'



def subst_unit_test():
    """
    Substitution unit test.
    """

    test_env = { "FISH" : "soup", "WOMBAT" : "herring" }
    result = subst.subst_str("${WOMBAT} is ${FISH}", None, test_env)
    assert result == "herring is soup"

    return 0

def filespec_unit_test():
    """
    Filespec unit tests.
    """

    lsp = filespec.ListFileSpecDataProvider(["/a/b", "/a/c", "/a/b/c", "/a/b/cee", "/d", "/d/bcee" ])

    l_full = lsp.list_files_under("/a", True)
    assert len(l_full) == 4

    l_part = lsp.list_files_under("/a", False)
    assert len(l_part) == 2

    # Right ..
    fs1 = filespec.FileSpec("/a", ".*", False, False)
    results = fs1.match(lsp)
    assert len(results) == 2
    assert "/a/b" in results
    assert "/a/c" in results

    fs1 = filespec.FileSpec("/a", "b", allUnder = False, allRegex = False)
    results = fs1.match(lsp)
    assert len(results) == 1
    assert "/a/b" in results

    fs1 = filespec.FileSpec("/a", "b", allUnder = True, allRegex = False)
    results = fs1.match(lsp)
    assert len(results) == 3
    assert "/a/b/c" in results
    assert "/a/b/cee" in results
    assert "/a/b" in results

    fs1 = filespec.FileSpec("/", "(.*)b(.*)", allUnder = True, allRegex = True)
    results = fs1.match(lsp)
    assert len(results) == 5
    assert "/d/bcee" in results
    assert "/a/b/c" in results
    assert "/a/b/cee" in results
    assert "/a/b" in results


def mechanics_unit_test():
    """
    Check mechanics.
    """

    builder = mechanics.Builder("/tmp", None)
    lbl = Label(utils.LabelType.Checkout, "bob", None, "*")
    s1 = builder.get_environment_for(lbl)
    s1.set_type("PATH", env_store.EnvType.Path)
    s1.append("PATH", "a")
    s1.set("FISH", "42")

    lbl = Label(utils.LabelType.Checkout, "bob", None, "a")
    s2 = builder.get_environment_for(lbl)
    s2.set_type("PATH", env_store.EnvType.Path)
    s2.append("PATH", "b")
    s2.set("FISH", "shark")

    in_env = { "FISH" : "x" , "PATH" :  "p" }
    builder.setup_environment(lbl, in_env)
    assert in_env["PATH"] == "p:a:b"
    assert in_env["FISH"] == "shark"



def depend_unit_test():
    """
    Some fairly simple tests for the dependency solver.
    """

    l1 = Label(utils.LabelType.Checkout, "co_1", "role_1", utils.LabelTag.CheckedOut)
    l2 = Label(utils.LabelType.Checkout, "co_1", "role_1", utils.LabelTag.Fetched)
    l3 = Label(utils.LabelType.Package, "pkg_1", "role_1", utils.LabelTag.PreConfig)
    l4 = Label(utils.LabelType.Deployment, "dep_1", "role_2", utils.LabelTag.Built)

    # Check label_from_string ..
    lx = Label.from_string("foo:bar{baz}/wombat[T]")

    lx_a = Label("foo", "bar", "baz", "wombat")
    assert lx.__cmp__(lx_a) == 0
    assert lx.transient
    assert not lx.system

    lx = Label.from_string("foo:bar/wombat[T]")
    lx_a = Label("foo", "bar", None, "wombat")
    assert lx.__cmp__(lx_a) == 0
    assert lx.transient
    assert not lx.system

    lx = Label.from_string("*:bar/wombat")
    assert (lx is not None)
    lx_a = Label("*", "bar", None, "wombat")
    print "lx = %s\n lx_a = %s"%(lx,lx_a)
    assert lx.__cmp__(lx_a) == 0
    assert not lx.transient
    assert not lx.system


    lx = Label.from_string("*:wombat/*")
    assert lx is not None
    lx_a = Label("*", "wombat", None, "*")
    assert lx.__cmp__(lx_a) == 0
    assert not lx.transient
    assert not lx.system

    lx = Label.from_string(l1.__str__())
    print "l1 str = %s"%l1.__str__()
    assert (lx is not None)
    assert (lx == l1)

    lx = Label.from_string(l2.__str__())
    assert (lx is not None)
    assert (lx == l2)

    lx = Label.from_string(l3.__str__())
    assert (lx is not None)
    assert (lx == l3)

    lx = Label.from_string(l4.__str__())
    assert (lx is not None)
    assert (lx == l4)

    # Let's check that label matching works the way we think it does ..
    la1 = l1.copy()
    la1.type = "*"

    la2 = l1.copy()
    la2.name = "*"

    la3 = l1.copy()
    la3.role = "*"
    la3.name = "*"

    la4 = l1.copy()
    la4.tag = "*"

    assert l1.match(l1) == 0
    assert l2.match(l1) is None
    assert la1.match(l1) == -1
    assert l1.match(la1) == -1
    assert (l2.match(la4)) == -1
    assert l1.match(la3) == -2

    r1 = depend.Rule(l1, pkg.NoAction())

    r2 = depend.Rule(l2, pkg.NoAction())
    r2.add(l1)

    r3 = depend.Rule(l3, pkg.NoAction())
    r4 = depend.Rule(l4, pkg.NoAction())

    r3.add(l2)
    r4.add(l3); r4.add(l2)

    rs = depend.RuleSet()
    rs.add(r1)
    rs.add(r2)
    rs.add(r3)
    rs.add(r4)
    print "RuleSet = %s\n"%rs

    r3_required_for = depend.needed_to_build(rs, l3)
    print "r3_for = %s\n"%(depend.rule_list_to_string(r3_required_for))

    r2_required_by = depend.required_by(rs, l2)
    print "r2_for = %s\n"%(depend.rule_list_to_string(r2_required_by))

def utils_unit_test():
    """
    Unit testing on various utility code.
    """

    s = utils.c_escape("Hello World!")
    assert s == "Hello World!"

    s = utils.c_escape("Test \" \\ One")

    assert s == "Test \\\" \\\\ One"

    s = utils.pad_to("0123456789", 11)
    assert s == "0123456789 "

    s = utils.pad_to("0123456789", 8)
    assert s == "0123456789"

    s = utils.pad_to("0", 10, "z")
    assert s == "0zzzzzzzzz"

    s = utils.split_path_left("a/b/c")

    assert s == ("a", "b/c")

    s = utils.split_path_left("/a/b/c")
    print "s = %s %s"%s
    assert s == ("", "a/b/c")

    s = utils.replace_root_name("/a", "/b", "/a/c")
    assert s == "/b/c"

    s = utils.replace_root_name("/a", "/b", "/d/e")
    assert s == "/d/e"


def vcs_unit_test():
    """
    Perform VCS unit tests.
    """
    repo = "http://www.google.com/"
    (x,y) = version_control.split_vcs_url(repo)

    assert version_control.split_vcs_url(repo) == (None, None)

    repo = "cVs+pserver://Foo.example.com/usr/cvs/foo"
    (vcs,url) = version_control.split_vcs_url(repo)
    assert vcs == "cvs"
    assert url == "pserver://Foo.example.com/usr/cvs/foo"

# End file.


