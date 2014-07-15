import os
import sys
import logging

from logging.handlers import RotatingFileHandler
from flask import Flask
from flask.ext import uploads
from flask.ext.misaka import Misaka
from flask.ext.sqlalchemy import SQLAlchemy
from humanize import naturaltime
from werkzeug.contrib.cache import SimpleCache

from web_ui.helpers import localtime


# Initialize Flask app
app = Flask('souma')
# Setup SQLAlchemy database
db = SQLAlchemy(app)

# Load configuration
app.config.from_object("web_ui.default_config")

app.jinja_env.filters['naturaltime'] = naturaltime
app.jinja_env.filters['localtime'] = lambda value: localtime(value, tzval=app.config["TIMEZONE"])

# Register markdown filters
Misaka(app)

# Create application data folder
if not os.path.exists(app.config["USER_DATA"]):
    os.makedirs(app.config["USER_DATA"], 0700)

# Setup Cache
cache = SimpleCache()

# Setup attachment access
attachments = uploads.UploadSet('attachments', uploads.IMAGES,
    default_dest=lambda app_x: app_x.config["UPLOADS_DEFAULT_DEST"])
uploads.configure_uploads(app, (attachments))

# Setup loggers
# Flask is configured to route logging events only to the console if it is in debug
# mode. This overrides this setting and enables a new logging handler which prints
# to the shell.
handlers = []
loggers = [app.logger, logging.getLogger('synapse'), logging.getLogger('e-synapse')]

if app.config["LOG_SQL_STATEMENTS"]:
    loggers.append(logging.getLogger('sqlalchemy.engine'))

if app.config["CONSOLE_LOGGING"] is True:
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(logging.Formatter(app.config['LOG_FORMAT']))
    handlers.append(console_handler)

if app.config["FILE_LOGGING"] is True:
    file_handler = RotatingFileHandler(app.config["LOG_FILENAME"],
        maxBytes=app.config["LOG_MAXBYTES"], backupCount=5, delay=True)
    file_handler.setFormatter(logging.Formatter(app.config['LOG_FORMAT']))
    handlers.append(file_handler)

for l in loggers:
    del l.handlers[:]  # remove old handlers
    l.setLevel(logging.DEBUG)
    for h in handlers:
        l.addHandler(h)
    l.propagate = False  # setting this to true triggers the root logger


def logged_in():
    """Check whether a user is logged in"""
    return cache.get('password') is not None

# Views need to be imported at the bottom to avoid circular import (see Flask docs)
import web_ui.views
