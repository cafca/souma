import os
import logging

#
# --------------------- FLASK OPTIONS ---------------------
#

LOCAL_PORT = 5000
LOCAL_HOSTNAME = 'app.souma'
LOCAL_ADDRESS = "{}:{}".format(LOCAL_HOSTNAME, LOCAL_PORT)

DEBUG = True
USE_DEBUG_SERVER = False

# Uncomment to log DB statements
# SQLALCHEMY_ECHO = True

DATABASE = 'souma_{}.db'.format(LOCAL_PORT)
SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE

# uploads are placed in the UPLOADS_DEFAULT_DEST/'attachments' subfolder by flask-uploads
# this is configured in web_ui/__init__.py
UPLOADS_DEFAULT_DEST = os.path.join(os.path.abspath(os.path.dirname(__file__)), "static")
ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'])
SEND_FILE_MAX_AGE_DEFAULT = 1

LOG_LEVEL = logging.INFO
LOG_FORMAT = (
    '%(name)s :: %(module)s [%(pathname)s:%(lineno)d]\n' +
    '%(message)s\n')

#
# --------------------- SYNAPSE OPTIONS -------------------
#

SYNAPSE_PORT = LOCAL_PORT + 50

LOGIN_SERVER = "app.souma:24500"
# Uncomment this to use Heroku server
# LOGIN_SERVER = "glia.herokuapp.com"

# Setting this to True will automatically upload all vesicles to Myelin, and
# enable periodic polling of the Myelin for new Vesicles sent to one of the
# Personas controlled by this Souma
ENABLE_MYELIN = True

# The interval in seconds at which the Myelin will be polled for new Vesicles
MYELIN_POLLING_INTERVAL = 10
