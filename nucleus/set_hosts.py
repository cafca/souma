import os
import logging

from sys import platform

logger = logging.getLogger()

if platform == 'win32':
    WINDIR = os.environ["WINDIR"]
    HOSTSFILE = os.path.join(WINDIR, 'system32', 'drivers', 'etc', 'hosts')
else:
    HOSTSFILE = '/etc/hosts'

SOMA_ENTRY = "127.0.0.1\t\tapp.souma"


def test_host_entry():
    """Return True if the right entry is found in the hosts file"""
    with open(HOSTSFILE) as f:
        for line in f.readlines():
            if line == SOMA_ENTRY:
                logging.info("Found hosts entry for local Souma service")
                return True
    logging.info("No host entry for local Souma service found")
    return False


def create_new_hosts_file(tempfile_handle):
    """Create a copy of /etc/hosts with a new entry for Souma added and return File handle"""
    new_lines = "\n\n# Access Souma at http://app.souma:5000/\n" + SOMA_ENTRY

    with open(HOSTSFILE, "r") as f:
        new_hosts = f.read() + new_lines

    with open(tempfile_handle, 'w') as f:
        f.write(new_hosts)
