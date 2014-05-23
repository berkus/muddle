#! /usr/bin/env python

"""Relational database support, via sqlite3

Our intent is to allow multiple simultaneous muddle builds, by allowing
parallel invocation of "muddle build". To make this possible, we need to
use some lockable mechanism for our tag management, instead of the older
tag-file approach (which is really nice and convenient, but doesn't allow
us to do what we need).
"""

import os
import sqlite3

# XXX Temporary things, until we're part of muddle
class GiveUp(Exception):
    pass
# XXX

# Various columns indicate whether we have started/finished some action
# For instance, we might have FINISHED checking a package's checkout out, but
# be IN_PROGRESS building it, which means we will be NOT_DONE installing it.
# We need that intermediate IN_PROGRESS state so that a muddle process can
# "claim" performing an action on a label.
# We shall call this our label's "state"
NOT_DONE    = 0
IN_PROGRESS = 1
FINISHED    = 2

VALID_STATES = (NOT_DONE, IN_PROGRESS, FINISHED)

# We deliberately use our label types as table names, so that we can deduce
# the table to use by dissecting the type out of a label.
CREATE_TABLES = """\
create table if not exists checkout(
    id          text primary key,       -- the checkout domain/name
    checkout    int default 0           -- state of checking the label out
);

create table if not exists package(
    id          text primary key,       -- the package domain/name/role
    preconfig   int default 0,          -- state for pre-configuring
    configure   int default 0,          -- state for configuring
    build       int default 0,          -- state for building
    install     int default 0,          -- state for installing
    postinstall int default 0,          -- state for post-installing

    clean       int default 0,          -- state for cleaning
    distclean   int default 0           -- state for distclean'ing
);

create table if not exists deployment(
    id          text primary key,       -- the deployment domain/name
    deploy      int default 0           -- state of deploying the label
);
"""

class TagDatabase(object):
    """This needs a better name(!)

    The interface we're using to our externally stored tag data

    Note that we don't maintain an open connection to the sqlite3 database,
    since we don't want to keep a lock on it longer than we need to.
    """

    def __init__(self, root_path):
        """Connect to our database.

        'root_path' is the location of the ".muddle" directory.

        We create the database if necessary, and set up its schema if
        the requisite tables don't exist yet.
        """

        self.root_path = root_path
        self.db_path = os.path.join(root_path, "muddle.db")
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(CREATE_TABLES)

    def add_label(self, label):
        """Add an empty row for a label.
        """
        label_type = 'checkout'     # XXX for the moment...
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('insert into %s (id) values (?)'%label_type, (label,))

    def set_tag(self, label, tag, state):
        """Set the 'label's 'tag' value to 'state'.
        """
        if state not in VALID_STATES:
            raise GiveUp('Cannot set label %s tag %s to state %s,'
                         ' not in %s'%(label, tag, state, VALID_STATES))
        label_type = 'checkout'     # XXX for the moment...
        with sqlite3.connect(self.db_path) as conn:
            # Unfortunately, I can't use "?" for the table name or the
            # column name. Of course, those *should* be entirely under our
            # control.
            conn.execute('update %s set %s=? where id=?'%(label_type, tag),
                    (state, label))


if __name__ == '__main__':

    db = TagDatabase('.')
    db.add_label('one')
    db.add_label('two')
    db.set_tag('one', 'checkout', FINISHED)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
