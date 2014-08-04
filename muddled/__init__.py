"""
Muddle - A VCS-agnostic package build and configuration management system
"""

# We import the vcs module here so that *its* __init__ can load each
# individual VCS, and they can register the VCS with version_control.py
import muddled.vcs
import logging

# default level is warning, some test scripts test the output of muddle with the assumption that this is the case
logging.basicConfig(format="%(message)s", level=logging.WARNING)

# TODO: write logs to timestamped files or similar