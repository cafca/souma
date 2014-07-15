import logging
import os

import appdirs

# ANY CHANGES MADE TO OPTIONS DEPENDING ON LOCAL_PORT NEED TO BE UPDATED IN
# web_ui/__init__.py


def read_version():
    """ Return current version identifier as recorded in `souma/__init__.py` """
    with open("__init__.py", 'rb') as f:
        return f.readline().split("=")[1].strip().replace('"', '')

USER_DATA = appdirs.user_data_dir("souma", "souma", roaming=True)
RUNTIME_DIR = ""

VERSION = read_version()
UPDATE_URL = "https://github.com/ciex/souma/wiki/Download-links"
UPDATE_CHECK_INTERVAL = 15 * 60

#
# --------------------- FLASK OPTIONS ---------------------
#

LOCAL_PORT = 5000
LOCAL_HOSTNAME = 'app.souma.io'
LOCAL_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, LOCAL_PORT)

DEBUG = False
USE_DEBUG_SERVER = False

TIMEZONE = 'Europe/Berlin'

SECRET_KEY_FILE = os.path.join(USER_DATA, "secret_key_{}.dat".format(LOCAL_PORT))
PASSWORD_HASH_FILE = os.path.join(USER_DATA, "pw_hash_{}.dat".format(LOCAL_PORT))

# Uncomment to log DB statements
# SQLALCHEMY_ECHO = True

DATABASE = os.path.join(USER_DATA, 'souma_{}.db'.format(LOCAL_PORT))
SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE

# uploads are placed in the UPLOADS_DEFAULT_DEST/'attachments' subfolder by flask-uploads
# this is configured in web_ui/__init__.py
UPLOADS_DEFAULT_DEST = os.path.join(USER_DATA, "attachments")
ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'])
SEND_FILE_MAX_AGE_DEFAULT = 1

LOG_LEVEL = logging.DEBUG
FILE_LOGGING = True
CONSOLE_LOGGING = True
LOG_FILENAME = os.path.join(USER_DATA, "app.log")
LOG_SQL_STATEMENTS = False
LOG_MAXBYTES = 10 * 1024 * 1024
LOG_FORMAT = (
    '%(name)s :: %(module)s [%(pathname)s:%(lineno)d]\n' +
    '%(message)s\n')

LAYOUT_DEFINITIONS = dict()

LESS_FILENAMES = ["main"]

#
# --------------------- SYNAPSE OPTIONS -------------------
#

SYNAPSE_PORT = LOCAL_PORT + 2000

# A: Use local test server
# LOGIN_SERVER = "app.souma.io:24500"
# LOGIN_SERVER_SSL = False

# B: Use Heroku server
LOGIN_SERVER = "glia.herokuapp.com"
LOGIN_SERVER_SSL = True

# Setting this to True will automatically upload all vesicles to Myelin, and
# enable periodic polling of the Myelin for new Vesicles sent to one of the
# Personas controlled by this Souma
ENABLE_MYELIN = True

# The interval in seconds at which the Myelin will be polled for new Vesicles
MYELIN_POLLING_INTERVAL = 10
