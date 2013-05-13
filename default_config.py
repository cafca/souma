import sys
import os

from flask import json
from Crypto.Hash import SHA256

# Access the absolute path of the script file with this
_basedir = os.path.abspath(os.path.dirname(__file__))

# This is the main Flask debug switch
DEBUG = True
USE_DEBUG_SERVER = False

SEND_FILE_MAX_AGE_DEFAULT = 1

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

# Uncomment this to use Heroku server
#LOGIN_SERVER_HOST = "glia.herokuapp.com"
#LOGIN_SERVER_PORT = "80"

LOGIN_SERVER = "{}:{}".format(LOGIN_SERVER_HOST, LOGIN_SERVER_PORT)

DATABASE = 'ark_{}.db'.format(LOCAL_PORT)
SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE

# Set secret key
try:
    with open('secret_key') as f:
        SECRET_KEY = f.read()
except IOError:
    SECRET_KEY = os.urandom(24)
    with open('secret_key', 'w') as f:
        f.write(SECRET_KEY)

if len(SECRET_KEY) != 24:
    raise ValueError('Secret key not valid ({}). Try deleting the file "secretkey".'.format(SECRET_KEY))

SOMA_ID = SHA256.new(SECRET_KEY+str(LOCAL_PORT)).hexdigest()

if 'SOMA_PASSWORD_HASH_{}'.format(LOCAL_PORT) in os.environ:
    PASSWORD_HASH = os.environ['SOMA_PASSWORD_HASH_{}'.format(LOCAL_PORT)]
else:
    PASSWORD_HASH = None

LOG_FORMAT = (
    '%(name)s :: %(module)s [%(pathname)s:%(lineno)d]\n' +
    '%(message)s\n')

try:
    layout_path = os.path.join(_basedir, 'web_ui', 'layouts.json')
    with open(layout_path) as f:
        LAYOUT_DEFINITIONS = json.load(f)
except IOError, e:
    LAYOUT_DEFINITIONS = dict()
