#!/usr/bin/python

import os
import sys
import webbrowser
import semantic_version
import argparse

from web_ui import app, db

from gevent import Greenlet, monkey
from gevent.wsgi import WSGIServer
from gevent.event import Event
from sqlalchemy.exc import OperationalError
from sys import platform
from uuid import uuid4

from astrolab.helpers import setup_astrolab
from nucleus.set_hosts import test_host_entry, create_new_hosts_file, HOSTSFILE
from nucleus.models import Souma, Starmap
from nucleus.helpers import configure_from_args, log_config_info, set_souma_id
from synapse import Synapse
from web_ui.helpers import host_kind, compile_less


monkey.patch_all()

""" parse arguments for config """
# Parse command line arguments
parser = argparse.ArgumentParser(description='Start Souma client')
parser.add_argument('--no_ui',
    default=False,
    action="store_true",
    help="skip starting the web ui server")

parser.add_argument('-d',
    '--debug',
    default=False,
    action="store_true",
    help="display more log events, halt on exceptions")

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
configure_from_args(app, args)
set_souma_id(app)
log_config_info(app)

""" patch gevent for py2app """
if getattr(sys, 'frozen', None) == 'macosx_app':
        import imp
        import httplib

        original_load_module = imp.load_module
        original_find_module = imp.find_module

        def custom_load_module(name, file, pathname, description):
            if name == '__httplib__':
                return httplib
            return original_load_module(name, file, pathname, description)

        def custom_find_module(name, path=None):
            if name == 'httplib':
                return (None, None, None)
            return original_find_module(name, path)

        imp.load_module = custom_load_module
        imp.find_module = custom_find_module

        # Verify that the patch is working properly (you can remove these lines safely)
        __httplib__ = imp.load_module('__httplib__', *imp.find_module('httplib'))
        assert __httplib__ is httplib


""" Initialize database """
start = True
local_souma = None

try:
    local_souma = Souma.query.get(app.config["SOUMA_ID"])
except OperationalError, e:
    app.logger.error("An operational error occured while testing the local database. " +
        "This is normal if you don't have a local database yet. If you do already have data" +
        "you should reset it with `-r` or delete it from `{}`\n\nError: {}".format(
            app.config["USER_DATA"], e))
    local_souma = None
    start = False

if local_souma is None:
    # Make sure all models have been loaded before creating the database to
    # create all their tables
    from astrolab import interestmodel

    app.logger.info("Setting up database")
    db.create_all()

    app.logger.info("Setting up Nucleus for <Souma [{}]>".format(app.config['SOUMA_ID'][:6]))
    local_souma = Souma(id=app.config['SOUMA_ID'], version=app.config["VERSION"])
    local_souma.generate_keys()
    local_souma.starmap = Starmap(id=uuid4().hex, kind="index")

    db.session.add(local_souma)
    try:
        db.session.commit()
    except OperationalError, e:
        app.logger.error("Failed setting up database.\n\n{}".format(e))
        start = False
    else:
        start = True

elif local_souma.version < semantic_version.Version(app.config["VERSION"]):
    app.logger.error("""Local Souma data is outdated (local Souma {} < codebase {}
        You should reset all user data with `-r` or delete it from `{}`""".format(
        local_souma.version, app.config["VERSION"], app.config["USER_DATA"]))
    start = False

#__file__ doesn't work with freezing
app.config["RUNTIME_DIR"] = os.path.abspath('.')

""" Start app """
if start:
    if app.config['USE_DEBUG_SERVER']:
        # flask development server
        app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
    else:
        shutdown = Event()

        # Synapse
        app.logger.info("Starting Synapses")

        if app.config["DEBUG"]:
            synapse = Synapse()
            synapse.electrical.login_all()
        else:
            try:
                synapse = Synapse()
                synapse.electrical.login_all()
            except Exception, e:
                app.logger.error(e)

        # Web UI
        if not app.config['NO_UI']:
            if not test_host_entry():
                app.logger.info("No hosts entry found. Will now enable access to local Souma service in your browser.")
                app.logger.info("Please enter your Administrator password if prompted")
                tempfile_path = os.path.join(app.config["USER_DATA"], "hosts.tmp")
                create_new_hosts_file(tempfile_path)
                # move temporary new hosts file to final location using administrator privileges
                if platform == 'win32':
                    os.system("runas /noprofile /user:Administrator move '{}' '{}'".format(tempfile_path, HOSTSFILE))
                else:
                    cmd = """osascript -e 'do shell script "mv \\"{}\\" \\"{}\\"" with administrator privileges'"""
                    os.system(cmd.format(tempfile_path, HOSTSFILE))

            # Compile less when running from console
            if host_kind() == "":
                compile_less()

            app.logger.info("Starting Web-UI")
            local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
            local_server.start()
            webbrowser.open("http://{}/".format(app.config["LOCAL_ADDRESS"]))

        # Setup Astrolab
        Greenlet.spawn(setup_astrolab)

        shutdown.wait()
