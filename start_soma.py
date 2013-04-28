#!/usr/bin/python

from soma import app
from soma.web_ui.models import init_db
from gevent.wsgi import WSGIServer
from synapse import Synapse
from set_hosts import test_host_entry

app.logger.info("Initializing DB")
init_db()

if not test_host_entry:
    app.logger.error("Please execute set_hosts.py with administrator privileges\
        to allow access to Soma at http://app.soma/.")
    quit()

if app.config['USE_DEBUG_SERVER']:
    # flask development server
    app.run(app.config['LOCAL_HOSTNAME'], app.config['LOCAL_PORT'])
else:
    # Synapse
    app.logger.info("Starting Synapses...")
    synapse = Synapse((app.config['LOCAL_HOSTNAME'], app.config['SYNAPSE_PORT']))
    synapse.start()

    # gevent server
    app.logger.info("Starting Web-UI...")
    local_server = WSGIServer(('', app.config['LOCAL_PORT']), app)
    local_server.serve_forever()
