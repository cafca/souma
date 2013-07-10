import logging
import gevent
import requests


from nucleus import notification_signals
from nucleus.models import Persona, Star
from nucleus.vesicle import Vesicle
from synapse.electrical import ElectricalSynapse


class Synapse(gevent.server.DatagramServer):
    """
    Handles connections with peers
    """

    self.peers = dict()  # Contains addresses of online peers as peer_id: (host,port)
    self.sessions = dict()

    def __init__(self, address):
        DatagramServer.__init__(self, address)

        self.logger = logging.getLogger('synapse')
        self.logger.setLevel(app.config['LOG_LEVEL'])

        # Core setup
        self.starmap = Starmap.query.get(app.config['SOMA_ID'])
        self.vesicle_pool = gevent.pool.Pool(10)
        self.electrical = ElectricalSynapse()

        # Connect to soma
        self._connect_signals()

    def _create_starmap(self):
        """
        Create a starmap listing all contents of the connected soma
        """
        pass

    def _connect_signals(self):
        """
        Connect to Blinker signals
        """

        # Create blinker signals
        signal = notification_signals.signal

        signal('star-created').connect(self.on_star_created)
        signal('star-modified').connect(self.on_star_modified)
        signal('star-deleted').connect(self.on_star_deleted)

        signal('planet-created').connect(self.on_planet_created)
        signal('planet-modified').connect(self.on_planet_modified)
        signal('planet-deleted').connect(self.on_planet_deleted)

        signal('persona-created').connect(self.on_persona_created)
        signal('persona-modified').connect(self.on_persona_modified)
        signal('persona-deleted').connect(self.on_persona_deleted)

        signal('new-contact').connect(self.on_new_contact)

    def _distribute_vesicle(self, vesicle):
        """
        Distribute vesicle to online peers
        """
        pass

    def _send_vesicle(self, vesicle, address):
        """
        Transmit vesicle to specified address
        """
        pass

    def handle(self, data, address):
        """
        Handle incoming connections
        """
        pass

    def handle_change_notification(self, message, address):
        """
        Act on received change notifications
        """
        pass

    def handle_object(self, data, address):
        """
        Act on received objects
        """
        pass

    def handle_object_request(self, data, address):
        """
        Act on received object requests
        """
        pass

    def handle_vesicle(self, data, address):
        """
        Handle received vesicles
        """
        pass

    def handle_starmap(self, data, address):
        """
        Handle received starmaps
        """
        pass

    def handle_starmap_request(self, data, address):
        """
        Handle received starmap requests
        """
        pass

    def on_star_created(self, sender, message):
        """
        React to star_created signal
        """
        pass

    def on_star_modified(self, sender, message):
        """
        React to star-modified signal
        """
        pass

    def on_star_deleted(self, sender, message):
        """
        React to star-deleted signal
        """
        pass

    def on_planet_created(self, sender, message):
        """
        React to planet-created signal
        """
        pass

    def on_planet_modified(self, sender, message):
        """
        React to planet-modified signal
        """
        pass

    def on_planet_deleted(self, sender, message):
        """
        React to star-deleted signal
        """
        pass

    def on_persona_created(self, sender, message):
        """
        React to persona-created signal
        """
        pass

    def on_persona_modified(self, sender, message):
        """
        React to persona-modified signal
        """
        pass

    def on_persona_deleted(self, sender, message):
        """
        React to persona-deleted signal
        """
        pass

    def shutdown(self):
        self.pool.kill()
    