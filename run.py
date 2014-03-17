#!/usr/bin/python

import gevent

from web_ui import app, db

from gevent.wsgi import WSGIServer
from sqlalchemy.exc import OperationalError
from uuid import uuid4

from nucleus.models import Souma, Starmap
from synapse import Synapse

from astrolab.helpers import repeated_func_schedule
from astrolab.interestmodel import update

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

""" Start app """
if app.config['USE_DEBUG_SERVER']:
    # flask development server
    app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
else:
    shutdown = gevent.event.Event()

    # Synapse
    app.logger.info("Starting Synapses")
    try:
        synapse = Synapse()
    except Exception, e:
        app.logger(e)

    repeated_func_schedule(60 * 60, update)

    # Web UI
    if not app.config['NO_UI']:
        app.logger.info("Starting Web-UI")
        local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
        local_server.start()

    shutdown.wait()
