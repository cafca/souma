#!/usr/bin/python

import os
import requests
import sys
import webbrowser

from web_ui import app, db

from gevent import Greenlet, sleep
from gevent.wsgi import WSGIServer
from gevent.event import Event
from sqlalchemy.exc import OperationalError
from sys import platform
from uuid import uuid4

from nucleus.set_hosts import test_host_entry, create_new_hosts_file, HOSTSFILE
from nucleus.models import Souma, Starmap
from synapse import Synapse
from web_ui.helpers import host_kind, compile_less

from astrolab.helpers import repeated_func_schedule
from astrolab.interestmodel import update


def setup_astrolab():
    """Download topic model and schedule model updates"""
    sleep(0)
    model_filename = app.config["ASTROLAB_MODEL"]
    word_ids_filename = app.config["ASTROLAB_MODEL_IDS"]

    model_url = app.config["ASTROLAB_UPDATE"]
    word_ids_url = app.config["ASTROLAB_IDS_UPDATE"]

    try:
        with open(word_ids_filename):
            app.logger.debug("Model word ids found")
    except IOError:
        app.logger.info("Now downloading model data ids")
        r = requests.get(word_ids_url, stream=True)
        with open(word_ids_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()
        app.logger.info("Model data ids downloaded")

    try:
        with open(model_filename):
            app.logger.debug("Model data found")
    except IOError:
        app.logger.info("Downloading model data")
        r = requests.get(model_url, stream=True)
        with open(model_filename, 'wb') as f:
            i = 0
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()
                    i += 1
                    if i % (1024 * 5) == 0:
                        app.logger.info("Downloaded {} MB / 323 MB".format(i / 1024))
        app.logger.info("Model data downloaded")

    repeated_func_schedule(60 * 60, update)


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
try:
    local_souma = Souma.query.get(app.config["SOUMA_ID"])
except OperationalError:
    local_souma = None

if local_souma is None:
    app.logger.info("Setting up database")
    db.create_all()

    app.logger.info("Setting up Nucleus for <Souma [{}]>".format(app.config['SOUMA_ID'][:6]))
    local_souma = Souma(id=app.config['SOUMA_ID'])
    local_souma.generate_keys()
    local_souma.starmap = Starmap(id=uuid4().hex, kind="index")

    db.session.add(local_souma)
    db.session.commit()

#__file__ doesn't work with freezing
app.config["RUNTIME_DIR"] = os.path.abspath('.')

""" Start app """
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
                os.system("""osascript -e 'do shell script "mv \\"{}\\" \\"{}\\"" with administrator privileges'""".format(tempfile_path, HOSTSFILE))

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
