#!/usr/bin/python
import sys
import os

# Add parent directory of current working directory to path so the current
# directory can be imported as a module (I have no idea why this is neccessary).
cwd_parent_dir = os.sep.join(os.getcwd().split(os.sep)[:-1])
sys.path.append(cwd_parent_dir)

from soma import app, db
from soma.synapse.models import Starmap
from gevent.wsgi import WSGIServer
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
    # Synapse
    app.logger.info("Starting Synapses")
    synapse = Synapse((app.config['LOCAL_HOSTNAME'], app.config['SYNAPSE_PORT']))
    synapse.start()

    # gevent server
    app.logger.info("Starting Web-UI")
    local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
    local_server.serve_forever()
