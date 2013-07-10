import logging
import requests

from web_ui import app


class ElectricalSynapse(object):
    """
    Handle connection to HTTP endpoints
    """

    def __init__(self):
        self.logger = logging.getLogger('e-synapse')
        self.logger.setLevel(app.config['LOG_LEVEL'])

        # Core setup
        self.host = "http://{host}/".format(host=app.config['LOGIN_SERVER'])
        self.session = requests.Session()

        # Test connection to glia-server
        try:
            self.session.get(self.host)
        except requests.ConnectionError, e:
            self.logger.error("Could not establish connection to glia server\n - {}".format(e))
            quit()

        # Login all owned personas
        persona_set = Persona.query.filter('sign_private != ""').all()

        if len(persona_set) == 0:
            self.logger.warning("No controlled Persona found.")
        else:
            for p in persona_set:
                self.login(p)
                self.update_peer_list(p)

    def _keepalive(self, persona):
        """
        Send keepalive for persona to server
        """
        pass

    def _queue_keepalive(self, persona, timeout):
        """
        Queue keepalive for persona in @param timeout seconds
        """
        pass

    def _request_resource(self, endpoint, params):
        """
        Request the resource at @param endpoint using @param params
        """
        pass

    def login(self, persona):
        """
        Login a persona on the server, register if not existing
        """
        pass

    def logout(self, persona):
        """
        Terminate persona's session on the host
        """
        pass

    def register(self, persona):
        """
        Register a persona on the server
        """
        pass

    def shutdown(self):
        """
        Terminate connections and logout
        """

    def update_peer_list(self, persona):
        """
        Retrieve current addresses of persona's peers from the server
        """
        pass

    def unregister(self, persona):
        """
        Remove persona's data from the glia server
        """
        pass