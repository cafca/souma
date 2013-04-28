import sys
import os

from flask import json

# Access the absolute path of the script file with this
_basedir = os.path.abspath(os.path.dirname(__file__))

# This is the main Flask debug switch
DEBUG = True
USE_DEBUG_SERVER = False

SEND_FILE_MAX_AGE_DEFAULT = 1

# TODO: Generate after installation, keep secret.
SECRET_KEY = '\xae\xac\xde\nIH\xe4\xed\xf0\xc1\xb9\xec\x08\xf6uT\xbb\xb6\x8f\x1fOBi\x13'

# Comment this out to set a custom password
# pw: jodat
PASSWORD_HASH = '8302a8fbf9f9a6f590d6d435e397044ae4c8fa22fdd82dc023bcc37d63c8018c'

# Setup host addresses
if len(sys.argv) == 2:
    LOCAL_PORT = int(sys.argv[1])
else:
    LOCAL_PORT = 5000

# The "Local" server has the Web UI
LOCAL_HOSTNAME = 'app.soma'
LOCAL_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, LOCAL_PORT)

MEMCACHED_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, 24000)
SYNAPSE_PORT = LOCAL_PORT + 50

LOGIN_SERVER_HOST = "app.soma"
LOGIN_SERVER_PORT = "24500"
LOGIN_SERVER = "{}:{}".format(LOGIN_SERVER_HOST, LOGIN_SERVER_PORT)

DATABASE = 'khemia_{}.db'.format(LOCAL_PORT)
SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE

LOG_FORMAT = (
    '%(name)s :: %(module)s [%(pathname)s:%(lineno)d]\n' +
    '%(message)s\n')

try:
    layout_path = os.path.join(_basedir, 'web_ui', 'layouts.json')
    with open(layout_path) as f:
        LAYOUT_DEFINITIONS = json.load(f)
except IOError, e:
    LAYOUT_DEFINITIONS = dict()
