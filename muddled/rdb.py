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

# Various columns indicate whether we have started/finished some action
# For instance, we might have FINISHED checking a package's checkout out, but
# be IN_PROGRESS building it, which means we will be NOT_DONE installing it.
# We need that intermediate IN_PROGRESS state so that a muddle process can
# "claim" performing an action on a label.
# We shall call this our label's "state"
NOT_DONE    = 0
IN_PROGRESS = 1
FINISHED    = 2

CREATE_TABLES = """\
create table if not exists checkouts(
    id          text primary key,       -- the checkout domain/name
    checkout    int                     -- state of checking the label out
);

create table if not exists packages(
    id          text primary key,       -- the package domain/name/role
    preconfig   int,                    -- state for pre-configuring
    configure   int,                    -- state for configuring
    build       int,                    -- state for building
    install     int,                    -- state for installing
    postinstall int,                    -- state for post-installing

    clean       int,                    -- state for cleaning
    distclean   int                     -- state for distclean'ing
);

create table if not exists deployments(
    id          text primary key,       -- the deployment domain/name
    deploy      int                     -- state of deploying the label
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

if __name__ == '__main__':

    db = TagDatabase('.')

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
