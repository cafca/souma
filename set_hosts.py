#!/usr/bin/env python

# This script adds a host entry for app.soma => 127.0.0.1
# so the app can be accessed at app.soma"""

import os
import logging

from sys import platform

logger = logging.getLogger()

if platform == 'win32':
    WINDIR = os.environ["WINDIR"]
    HOSTSFILE = os.path.join(WINDIR, 'system32', 'drivers', 'etc', 'hosts')
else:
    # Is this really the place on all systems other than Windows?
    HOSTSFILE = '/etc/hosts'

SOMA_ENTRY = "127.0.0.1 app.souma"
entry_found = False


def test_host_entry():
    """Return True if the right entry is found in the hosts file"""
    with open(HOSTSFILE) as f:
        for line in f.readlines():
            if line == SOMA_ENTRY:
                return True
    return False


if not test_host_entry():
    logging.info("[soma] adding entry for app.soma to etc/hosts..")
    with open(HOSTSFILE, 'a') as f:
        f.write("\n\n# Access Soma at app.soma\n" + SOMA_ENTRY)
else:
    logging.info("[soma] hosts entry found")
