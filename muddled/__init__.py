"""
Muddle - A VCS-agnostic package build and configuration management system
"""

# We import the vcs module here so that *its* __init__ can load each
# individual VCS, and they can register the VCS with version_control.py
import muddled.vcs
import logging

# Overridden by __main__ importing muddled.logs when run as a command
logging.basicConfig(format="%(message)s", level=logging.WARNING)
