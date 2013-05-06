#!/usr/bin/python

from soma import app, db
from soma.synapse.models import Starmap
from gevent.wsgi import WSGIServer
from synapse import Synapse
from set_hosts import test_host_entry
from sqlalchemy.exc import OperationalError

# Initialize database
try:
    db.session.execute("SELECT * FROM 'starmap' LIMIT 1")
except OperationalError:
    app.logger.info("Initializing database")
    db.create_all()
    db.session.add(Starmap(app.config['SOMA_ID']))
    db.session.commit()

if not test_host_entry:
    app.logger.error("Please execute set_hosts.py with administrator privileges\
        to allow access to Soma at http://app.soma/.")
    quit()

if app.config['USE_DEBUG_SERVER']:
    # flask development server
    app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
else:
    # Synapse
    app.logger.info("Starting Synapses")
    synapse = Synapse((app.config['LOCAL_HOSTNAME'], app.config['SYNAPSE_PORT']))
    synapse.start()

    # gevent server
    app.logger.info("Starting Web-UI")
    local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
    local_server.serve_forever()
