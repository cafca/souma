import logging
import sys
import argparse

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flaskext import uploads
from humanize import naturaltime
from werkzeug.contrib.cache import SimpleCache

# Initialize Flask app
app = Flask('soma')
app.config.from_object("default_config")
app.jinja_env.filters['naturaltime'] = naturaltime

# Parse command line arguments
parser = argparse.ArgumentParser(description='Start Soma client')
parser.add_argument(
    '--no_ui',
    default=False,
    action="store_true",
    help="skip starting the web ui server")

parser.add_argument(
    '-p',
    '--port',
    default=app.config['LOCAL_PORT'],
    type=int,
    help='run synapse on this port')

parser.add_argument(
    '-g',
    '--glia',
    default=app.config['LOGIN_SERVER'],
    help="glia server")

args = parser.parse_args()
app.config['LOCAL_PORT'] = args.port
app.config['NO_UI'] = args.no_ui
app.config['LOGIN_SERVER'] = args.glia

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

# Log configuration info
app.logger.info(
    "\n".join(["{:=^80}".format(" SOMA CONFIGURATION "),
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
