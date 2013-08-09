import json
import logging
import os
import requests

from Crypto import Random

from nucleus import notification_signals
from nucleus.models import Persona, Souma
from web_ui import app

API_VERSION = 0
API_VERSION_LONG = 0.1


class ElectricalSynapse(object):
    """
    Handle connection to HTTP endpoints
    """

    def __init__(self, host=app.config['LOGIN_SERVER']):
        self.logger = logging.getLogger('e-synapse')
        self.logger.setLevel(app.config['LOG_LEVEL'])

        # Core setup
        self.souma = Souma.query.filter("sign_private != ''").first()
        self.host = "http://{host}".format(host=host)
        self.session = requests.Session()
        self._peers = dict()
        self._sessions = dict()

        # PyCrypto random number generator for authentication
        self.rng = Random.new()

        # Setup signals
        self.soma_discovered = notification_signals.signal('soma-discovered')
        notification_signals.signal('persona-created').connect(self.on_persona_created)
        notification_signals.signal('persona-modified').connect(self.on_persona_modified)
        notification_signals.signal('persona-deleted').connect(self.on_persona_deleted)

        # Test connection to glia-server
        try:
            self.session.get(self.host)
        except requests.ConnectionError, e:
            self.logger.error("Could not establish connection to glia server\n* {}".format(e))
            quit()

        # Login all owned personas
        self.login_all()

    def _get_session(self, persona):
        """
        Return the current session id for persona or create a new session
        """
        if persona.id in self._sessions:
            return self._sessions[persona.id]
        else:
            return self.persona_login(persona)

    def _set_session(self, persona, session_id, timeout):
        """
        Store a new session id for persona

        Args:
            persona (persona)
            session_id (str): New session id. If set to none, the session is removed
            timeout (str): ISO formatted datetime of session timeout
        """

        if session_id is None:
            del self._sessions[persona.id]
        else:
            to = dateutil_parse(timeout)

            self._sessions[persona.id] = {
                'id': session_id,
                'timeout': to
            }

    def _log_errors(self, msg, errors):
        """
        Log a list of errors to the logger

        Args:
            msg(str): A message describing the error source
            errors(list): A list of error messages
        """

        self.logger.error("{msg}:\n{list}".format(msg=msg, list="\n* ".join(errors)))

    def _keepalive(self, persona):
        """
        Keep @param persona's glia session alive by sending a keep-alive vesicle

        If there is no session yet for persona, she is logged in.
        """

        endpoint = "/".join(["personas", persona.id, self._get_session(persona)])
        r, errors = self._request_resource("GET", endpoint)

        if errors:
            self._log_errors("Error in keep_alive for {}".format(persona), errors)

            # Login if session is invalid
            if synapse.SESSION_INVALID in r['errors']:
                self.login(persona)
        else:
            session_id = r['data']['session_id']
            timeout = r['data']['timeout']
            self._set_session(persona, session_id, timeout)

            self.queue_keepalive(persona)

    def _queue_keepalive(self, persona, timeout=900):
        """
        Queue keepalive for persona in @param timeout seconds (default 15 minutes)
        """

        buf = 10  # seconds
        remaining = (self._get_session(persona)['timeout'] - datetime.datetime.now()).seconds
        if (remaining - buf) < 0:
            remaining = 2

        ping = Greenlet(self._keep_alive, persona)
        ping.start_later(remaining)

    def _request_resource(self, method, endpoint, params=None, payload=None):
        """
        Request a resource from the server

        Args:
            method (str): One of "GET", "POST", "PUT", "UPDATE", "DELETE"
            endpoint (list): A list of strings forming the path of the API endpoint
            params (dict): Optional parameters to attach to the query strings
            payload (object): Will be attached to the request JSON encoded

        Returns:
            A tuple of two elements:
            [0] (object) The decoded response of the server
            [1] (list) A list of error strings specified in the `errors` field of the response
        """
        # Validate params
        HTTP_METHODS_1 = ("GET", "DELETE")
        HTTP_METHODS_2 = ("POST", "PUT", "PATCH")  # have `data` parameter

        if method not in HTTP_METHODS_1 and method not in HTTP_METHODS_2:
            raise ValueError("Invalid request method {}".form(method))

        if payload:
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a dictionary type")
            try:
                payload = json.encode(payload)
            except ValueError, e:
                raise ValueError("Error encoding payload of {}:\n{}".format(self, e))
        else:
            payload = None

        # Construct URL
        url_elems = [self.host, str(API_VERSION)]
        url_elems.extend(endpoint)
        url = "/".join(url_elems)

        # Authentication parameters
        params['souma_id'] = self.souma.id
        params['rand'] = self.rng.read(16)
        params['auth'] = self.souma.sign("".join([self.souma.id, params['rand'], url, payload]))

        # Make request
        errors = list()
        call = getattr(self.session, method.lower())
        try:
            if method in HTTP_METHODS_1:
                r = call(url, params=params)
            else:
                r = call(url, payload, headers={'Content-Type': "application/json"}, params=params)
            r.raise_for_status()
        except requests.exceptions.RequestException, e:
            errors.append(e)

        # Log all errors
        if errors:
            raise requests.exceptions.RequestException("{} {} failed.\nParam: {}\nPayload: {}\nErrors:\n* {}".format(
                method, endpoint, params, payload, "\n* ".join(str(e) for e in errors)))

        # Parse JSON, extract errors
        else:
            error_strings = list()
            try:
                resp = r.json()
            except ValueError, e:
                self.logger.warning("Parsing JSON failed: {}".format(e))
                return (r.text, error_strings)

            if 'errors' in resp['data']:
                for error in resp['data']['errors']:
                    error_strings.append("{}: {}".format(error[0], error[1]))

            self.logger.debug("Received data: {}".format(resp.text))
            return (resp, error_strings)

    def _update_peer_list(self, persona):
        """
        Retrieve current IPs of persona's peers

        Args:
            persona (persona): The Persona whose peers will be located

        Returns:
            list A list of error messages
        """

        contacts = Persona.query.get(persona.id).contacts

        peer_ids = list()  # peers we want to look up
        for p in contacts:
            peer_ids.append(p.id)

        # ask glia server for peer info
        resp, errors = self._request_resource("GET", ["personas"], params=peer_ids)
        # TODO: Remove peers that are no longer online

        if errors:
            self._log_errors("Error updating peer list", errors)

        offline = 0
        for p_id, somas in resp['peer_list']:
            if somas:
                for soma in somas:
                    self.soma_discovered.send(self._update_peer_list, message=soma)
            else:
                offline += 1
                self.logger.info("No online souma found for {}".format(contacts.get(p_id)))

        self.logger.info("Updated peer list: {}/{} online".format(len(resp)-offline, len(resp)))

        return errors

    def find_persona(self, addresses):
        """
        Find personas by their email address

        Args:
            addresses (list): Email addresses to search for

        Returns:
            list A list of dictionaries containing found profile information

            Keys:
                "persona_id",
                "username",
                "host",
                "port_external",
                "port_internal",
                "crypt_public",
                "sign_public",
                "connectable"
        """

        address_list = list()
        for a in addresses:
            address_list.append(sha256(a).hexdigest())

        app.logger.info("Searching Glia for {}".format(",".join(addresses)))
        data = {
            "addresses": address_list
        }

        return self._request_resource("POST", ["personas"], payload=data)

    def login_all(self):
        """
        Login all personas with a non-empty private key
        """
        persona_set = Persona.query.filter('sign_private != ""').all()
        if len(persona_set) == 0:
            self.logger.warning("No controlled Persona found.")
        else:
            for p in persona_set:
                self.persona_login(p)
                self.update_peer_list(p)

    def on_persona_created(self, sender, message):
        """Register new personas with glia-server"""
        pass

    def on_persona_modified(self, sender, message):
        """Update persona info on glia-server when changed"""
        pass

    def on_persona_deleted(self, sender, message):
        """Delete persona from glia-server"""
        pass

    def persona_info(self, persona_id):
        """
        Return a dictionary containing info about a persona

        Parameters:
            persona_id (str): Persona ID

        Returns:
            dict persona's public profile and auth_token for authentication
        """
        return self._request_resource("GET", ["personas", persona_id])

    def persona_login(self, persona):
        """
        Login a persona on the server, register if not existing

        Returns:
            str -- new session id
        """

        # Check current state
        if persona.id in self._sessions:
            return self._get_session(persona)["session_id"]

        # Obtain auth token
        info, errors = self._request_resource("GET", ["personas", persona.id])
        if errors:
            self._log_errors("Error logging in", errors)

            # Register persona if not existing
            if PERSONA_NOT_FOUND in info['errors']:
                self.persona_register(persona)
                return
        auth = info["auth"]

        # Send login request
        data = {
            'auth_signed': persona.sign(auth),
        }
        resp, errors = self._request_resource("PUT", ["personas", persona.id], payload=data)

        # Read response
        if errors:
            self._log_errors("Login failed", errors)
            return None
        else:
            session_id = resp['session_id']
            timeout = resp['timeout']

            self._set_session(persona, session_id, timeout)
            self.queue_keepalive(persona)
            self._update_peer_list(persona)

            self.logger.info("Persona {} logged in until {}".format(persona, timeout))
            return session_id

    def persona_logout(self, persona):
        """
        Terminate persona's session on the host

        Parameters:
            persona -- persona to be logged out

        Returns:
            dict -- error_name:error_message
        """
        ses = self._get_session(persona)
        resp, errors = self._request_resource("DELETE", ["personas", persona.id, ses["id"]])

        if errors:
            self._log_errors("Error logging out", errors)
            return errors
        else:
            self._set_session(persona, None, None)
            self.logger.info("Logged out {}".format(persona))

    def persona_register(self, persona):
        """
        Register a persona on the server

        Parameters:
            persona -- persona to be registered

        Returns:
            list -- error messages
        """

        # Create request
        data = {
            'persona_id': persona.id,
            'username': persona.username,
            'email_hash': persona.get_email_hash(),
            'sign_public': persona.sign_public,
            'crypt_public': persona.crypt_public,
            'reply_to': app.config['SYNAPSE_PORT']
        }

        response, errors = self._request_resource("POST", ["personas", persona.id], payload=data)

        if errors:
            self._log_errors("Error creating glia profile for {}".format(persona), errors)
            return errors

        # Evaluate response
        try:
            session_id = response['data']['session_id']
            timeout = response['data']['timeout']
        except KeyError, e:
            return ["Invalid server response: {}".format(e)]

        self.logger.info("Registered {} with server.".format(persona))
        self._set_session(persona, session_id, timeout)
        self._update_peer_list(persona)
        self._queue_keepalive(persona)

    def persona_unregister(self, persona):
        """
        Remove persona's data from the glia server

        Parameters:
            persona (persona):persona to be unregistered

        Returns:
            dict error_name:error_message
        """

        response, errors = self._request_resource("DELETE", ["personas", persona.id])

        if errors:
            self._log_errors("Error unregistering persona {}".format(persona), errors)
        else:
            self.logger.info("Unregisterd persona {} from Glia server:\n{}".format(persona, response))

    def shutdown(self):
        """
        Terminate connections and logout
        """
        pass
