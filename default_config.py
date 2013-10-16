import sys
import os
import logging

from flask import json
from Crypto.Hash import SHA256

# Access the absolute path of the script file with this
_basedir = os.path.abspath(os.path.dirname(__file__))

# This is the main Flask debug switch
DEBUG = True
USE_DEBUG_SERVER = False
SEND_FILE_MAX_AGE_DEFAULT = 1
# uploads are placed in the UPLOADS_DEFAULT_DEST/'attachments' subfolder by flask-uploads
# this is configured in web_ui/__init__.py
UPLOADS_DEFAULT_DEST = os.path.join(_basedir, "static")
ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'])

LOCAL_PORT = 5000

# The "Local" server has the Web UI
LOCAL_HOSTNAME = 'app.soma'
LOCAL_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, LOCAL_PORT)

MEMCACHED_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, 24000)
SYNAPSE_PORT = LOCAL_PORT + 50

LOGIN_SERVER = "app.soma:24500"
# Uncomment this to use Heroku server
#LOGIN_SERVER = "glia.herokuapp.com:80"

OPERATOR_ID = "operator"

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

SOMA_ID = SHA256.new(SECRET_KEY+str(LOCAL_PORT)).hexdigest()[:32]

if 'SOMA_PASSWORD_HASH_{}'.format(LOCAL_PORT) in os.environ:
    PASSWORD_HASH = os.environ['SOMA_PASSWORD_HASH_{}'.format(LOCAL_PORT)]
else:
    PASSWORD_HASH = None

LOG_LEVEL = logging.DEBUG
LOG_FORMAT = (
    '%(name)s :: %(module)s [%(pathname)s:%(lineno)d]\n' +
    '%(message)s\n')

try:
    layout_path = os.path.join(_basedir, 'web_ui', 'layouts.json')
    with open(layout_path) as f:
        LAYOUT_DEFINITIONS = json.load(f)
except IOError, e:
    LAYOUT_DEFINITIONS = dict()
