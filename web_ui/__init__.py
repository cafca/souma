import logging
import os
import sys
import argparse

from Crypto.Hash import SHA256
from flask import Flask, json
from flask.ext.sqlalchemy import SQLAlchemy
from flaskext import uploads
from humanize import naturaltime
from werkzeug.contrib.cache import SimpleCache


# Initialize Flask app
app = Flask('souma')

# Load config from default_config.py
app.config.from_object("web_ui.default_config")
app.jinja_env.filters['naturaltime'] = naturaltime

# Create application data folder
if not os.path.exists(app.config["USER_DATA"]):
    os.mkdir(app.config["USER_DATA"], 0700)

# Parse command line arguments
parser = argparse.ArgumentParser(description='Start Souma client')
parser.add_argument('--no_ui',
    default=False,
    action="store_true",
    help="skip starting the web ui server")

parser.add_argument('-v',
    '--verbose',
    default=False,
    action="store_true",
    help="gimme moar-logs")

parser.add_argument('-r',
    '--reset',
    default=False,
    action="store_true",
    help="reset database and secret key (irreversible!)")

parser.add_argument('-p',
    '--port',
    type=int,
    help='run synapse on this port')

parser.add_argument('-g',
    '--glia',
    default=app.config['LOGIN_SERVER'],
    help="glia server url")

args = parser.parse_args()
app.config['NO_UI'] = args.no_ui
app.config['LOGIN_SERVER'] = args.glia

if args.verbose is True:
    app.config["LOG_LEVEL"] = logging.DEBUG
    app.logger.debug("Verbose logs active")

if args.port is not None:
    app.config['LOCAL_PORT'] = args.port
    app.config['LOCAL_ADDRESS'] = "{}:{}".format(app.config['LOCAL_HOSTNAME'], args.port)
    app.config['SYNAPSE_PORT'] = args.port + 50
    app.config['DATABASE'] = os.path.join(app.config["USER_DATA"], 'souma_{}.db'.format(app.config["LOCAL_PORT"]))
    app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + app.config['DATABASE']
    app.config["SECRET_KEY_FILE"] = os.path.join(app.config["USER_DATA"], "secret_key_{}.dat".format(args.port))
    app.config["PASSWORD_HASH_FILE"] = os.path.join(app.config["USER_DATA"], "pw_hash_{}.dat".format(args.port))

if args.reset is True:
    for fileid in ["DATABASE", "SECRET_KEY_FILE", "PASSWORD_HASH_FILE"]:
        try:
            os.remove(app.config[fileid])
        except OSError:
            app.logger.warning("RESET: {} not found".format(fileid))
        else:
            app.logger.warning("RESET: {} deleted")


""" Load/set secret key """
try:
    with open(app.config["SECRET_KEY_FILE"], 'rb') as f:
        app.config['SECRET_KEY'] = f.read(24)
except IOError:
    # Create new secret key
    app.logger.debug("Creating new secret key")
    app.config['SECRET_KEY'] = os.urandom(24)
    with open(app.config["SECRET_KEY_FILE"], 'wb') as f:
        os.chmod(app.config["SECRET_KEY_FILE"], 0700)
        f.write(app.config['SECRET_KEY'])

# Generate ID used to identify this machine
app.config['SOUMA_ID'] = SHA256.new(app.config['SECRET_KEY'] + str(app.config['LOCAL_PORT'])).hexdigest()[:32]

if 'SOUMA_PASSWORD_HASH_{}'.format(app.config['LOCAL_PORT']) in os.environ:
    app.config['PASSWORD_HASH'] = os.environ['SOUMA_PASSWORD_HASH_{}'.format(app.config["LOCAL_PORT"])]
else:
    app.config['PASSWORD_HASH'] = None


# Load layout definitions
try:
    with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'layouts.json')) as f:
        app.config['LAYOUT_DEFINITIONS'] = json.load(f)
except IOError, e:
    logging.error("Failed loading layout definitions")
    app.config['LAYOUT_DEFINITIONS'] = dict()


# Setup SQLAlchemy database
db = SQLAlchemy(app)


# Setup attachment access
attachments = uploads.UploadSet('attachments', uploads.IMAGES)
uploads.configure_uploads(app, (attachments))


# Setup loggers
# Flask is configured to route logging events only to the console if it is in debug
# mode. This overrides this setting and enables a new logging handler which prints
# to the shell.
loggers = [app.logger, logging.getLogger('synapse'), logging.getLogger('e-synapse')]
console_handler = logging.StreamHandler(stream=sys.stdout)
console_handler.setFormatter(logging.Formatter(app.config['LOG_FORMAT']))

for l in loggers:
    del l.handlers[:]  # remove old handlers
    l.setLevel(logging.DEBUG)
    l.addHandler(console_handler)
    l.propagate = False  # setting this to true triggers the root logger


# Log loaded configuration info
app.logger.info(
    "\n".join(["{:=^80}".format(" SOUMA CONFIGURATION "),
              "{:>12}: {}".format("souma", app.config['SOUMA_ID'][:6]),
              "{:>12}: {}".format("web ui", "disabled" if app.config['NO_UI'] else app.config['LOCAL_ADDRESS']),
              "{:>12}: {}:{}".format(
                  "synapse",
                  app.config['LOCAL_HOSTNAME'],
                  app.config['SYNAPSE_PORT']),
              "{:>12}: {}".format("database", app.config['DATABASE']),
              "{:>12}: {}".format("glia server", app.config['LOGIN_SERVER'])]))


# Setup Cache
cache = SimpleCache()


def logged_in():
    """Check whether a user is logged in"""
    return cache.get('password') is not None

# Views need to be imported at the bottom to avoid circular import (see Flask docs)
import web_ui.views
