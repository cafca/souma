#!/usr/bin/python

import gevent
import requests

from web_ui import app, db

from gevent import Greenlet
from gevent.wsgi import WSGIServer
from sqlalchemy.exc import OperationalError
from uuid import uuid4

from nucleus.models import Souma, Starmap
from synapse import Synapse

from astrolab.helpers import repeated_func_schedule
from astrolab.interestmodel import update


def setup_astrolab():
    """Download topic model and schedule model updates"""
    model_filename = app.config["TOPIC_MODEL"]
    word_ids_filename = app.config["TOPIC_MODEL_IDS"]

    model_url = app.config["TOPIC_MODEL_UPDATE"]
    word_ids_url = app.config["TOPIC_MODEL_IDS_UPDATE"]

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

# Initialize database
try:
    local_souma = Souma.query.get(app.config["SOUMA_ID"])
except OperationalError:
    app.logger.info("Setting up database")
    db.create_all()

    app.logger.info("Setting up Nucleus for <Souma [{}]>".format(app.config['SOUMA_ID'][:6]))
    local_souma = Souma(id=app.config['SOUMA_ID'])
    local_souma.generate_keys()
    local_souma.starmap = Starmap(id=uuid4().hex, kind="index")

    db.session.add(local_souma)
    db.session.commit()

if app.config['USE_DEBUG_SERVER']:
    # flask development server
    app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
else:
    shutdown = gevent.event.Event()

    # Synapse
    app.logger.info("Starting Synapses")
    synapse = Synapse()

    # Setup Astrolab
    Greenlet.spawn(setup_astrolab)

    # Web UI
    if not app.config['NO_UI']:
        app.logger.info("Starting Web-UI")
        local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
        local_server.start()

    shutdown.wait()
