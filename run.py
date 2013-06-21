#!/usr/bin/python

import gevent

from web_ui import app, db
from gevent.wsgi import WSGIServer
from synapse.models import Starmap
from synapse import Synapse
from sqlalchemy.exc import OperationalError

# Initialize database
try:
    db.session.execute("SELECT * FROM 'starmap' LIMIT 1")
except OperationalError:
    app.logger.info("Initializing database")
    db.create_all()
    db.session.add(Starmap(app.config['SOMA_ID']))
    db.session.commit()

if app.config['USE_DEBUG_SERVER']:
    # flask development server
    app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
else:
    shutdown = gevent.event.Event()

    # Synapse
    app.logger.info("Starting Synapses")
    synapse = Synapse(('0.0.0.0', app.config['SYNAPSE_PORT']))
    synapse.start()

    # gevent server
    if not app.config['NO_UI']:
        app.logger.info("Starting Web-UI")
        local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
        local_server.start()

    shutdown.wait()
