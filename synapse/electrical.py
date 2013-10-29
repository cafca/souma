import datetime
import json
import logging
import os
import requests

from base64 import b64encode, b64decode
from Crypto import Random
from dateutil.parser import parse as dateutil_parse
from gevent import Greenlet
from hashlib import sha256
from operator import itemgetter

from nucleus import notification_signals, ERROR
from nucleus.models import Persona, Souma
from web_ui import app

API_VERSION = 0
API_VERSION_LONG = 0.1


class GliaAuth(requests.auth.AuthBase):
    """Attaches HTTP Glia Authentication to the given Request object."""
    def __init__(self, souma, payload=None):
        self.souma = souma
        self.payload = payload if payload is not None else str()
        self.rng = Random.new()

    def __call__(self, r):
        # modify and return the request
        rand = self.rng.read(16)

        r.headers['Glia-Souma'] = self.souma.id
        r.headers['Glia-Rand'] = rand
        r.headers['Glia-Auth'] = self.souma.sign("".join([
            str(self.souma.id), 
            rand, 
            r.url, 
            self.payload
        ]))
        return r


class ElectricalSynapse(object):
    """
    Handle connection to HTTP endpoints
    """

    def __init__(self, host=app.config['LOGIN_SERVER']):
        self.logger = logging.getLogger('e-synapse')
        self.logger.setLevel(app.config['LOG_LEVEL'])

        # Core setup
        self.souma = Souma.query.filter("sign_private != ''").first()  # The Souma which hosts this Synapse
        self.host = "http://{host}".format(host=host)  # The Glia server to connect to
        self.session = requests.Session()  # Session object to use for requests
        self._peers = dict()
        self._sessions = dict()  # Holds session info for owned Personas (see _get_session(), _set_session()

        # Setup signals
        self.soma_discovered = notification_signals.signal('soma-discovered')
        notification_signals.signal('persona-created').connect(self.on_persona_created)
        notification_signals.signal('persona-modified').connect(self.on_persona_modified)
        notification_signals.signal('persona-deleted').connect(self.on_persona_deleted)

        # Test connection to glia-server
        try:
            server_info, errors = self._request_resource("GET", [])
        except requests.ConnectionError, e:
            self.logger.error("Could not establish connection to glia server\n* {}".format(e))
            quit()

        # Register souma if neccessary
        if errors:
            # Check for SOMA_NOT_FOUND error code in server response
            if ERROR["SOUMA_NOT_FOUND"](None)[0] in map(itemgetter(0), server_info["meta"]["errors"]):
                if self.souma_register():
                    server_info, errors = self._request_resource("GET", [])
                else:
                    self._log_errors("Error registering Souma", errors)
                    quit()
            else:
                self._log_errors("Error connecting to Glia", errors)
                quit()

        try:
            self.logger.info(
                "\n".join(["{:=^80}".format(" GLIA INFO "),
                          "{:>12}: {} ({})".format("status", server_info["server_status"][0]["status_message"], server_info["server_status"][0]["status_code"]),
                          "{:>12}: {}".format("server id", server_info["server_status"][0]["id"]),
                          "{:>12}: {}".format("personas", server_info["server_status"][0]["personas_registered"]),
                          "{:>12}: {}".format("vesicles", server_info["server_status"][0]["vesicles_stored"])
                          ]))
        except KeyError, e:
            self.logger.warning("Received invalid server status: Missing {}".format(e))

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

        self.logger.error("{msg}:\n{list}".format(msg=msg, list="\n* ".join(str(e) for e in errors)))

    def _keepalive(self, persona):
        """
        Keep @param persona's glia session alive by sending a keep-alive request

        If there is no session yet for persona, she is logged in.
        """

        self.logger.info("Sending keepalive for {}".format(persona))

        session_id = self._get_session(persona)["id"]
        resp, errors = self._request_resource("GET", ["sessions", session_id])

        if errors:
            self._log_errors("Error requesting keepalive for {}".format(persona), errors)

            # Login if session is invalid
            if ERROR["SESSION_INVALID"] in resp['meta']['errors']:
                self.login(persona)
        else:
            session_id = resp['sessions'][0]['id']
            timeout = resp['sessions'][0]['timeout']
            self._set_session(persona, session_id, timeout)

            self._queue_keepalive(persona)

    def _queue_keepalive(self, persona, timeout=900):
        """
        Queue keepalive for persona in @param timeout seconds (default 15 minutes)
        """

        buf = 10  # seconds
        remaining = (self._get_session(persona)['timeout'] - datetime.datetime.now()).seconds - buf
        if (remaining - buf) < 0:
            remaining = 2

        self.logger.info("Next keepalive for {} queued in {} seconds".format(persona, remaining))

        ping = Greenlet(self._keepalive, persona)
        ping.start_later(remaining)

    def _request_resource(self, method, endpoint, params=None, payload=None):
        """
        Request a resource from the server

        Args:
            method (str): One of "GET", "POST", "PUT", "PATCH", "DELETE"
            endpoint (list): A list of strings forming the path of the API endpoint
            params (dict): Optional parameters to attach to the query strings
            payload (object): Will be attached to the request JSON encoded

        Returns:
            A tuple of two elements:
            [0] (object) The (decoded) response of the server
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
                payload_json = json.dumps(payload)
            except ValueError, e:
                raise ValueError("Error encoding payload of {}:\n{}".format(self, e))
        else:
            payload_json = None

        # Construct URL
        url_elems = [self.host, "v"+str(API_VERSION)]
        url_elems.extend(endpoint)
        url = "/".join(url_elems) + "/"

        # Make request
        headers = dict()
        errors = list()
        parsing_failed = False
        http_errors = False

        call = getattr(self.session, method.lower())
        try:
            if method in HTTP_METHODS_1:
                self.logger.debug("{} {}".format(method, url))
                r = call(url, headers=headers, params=params, auth=GliaAuth(souma=self.souma))
            else:
                self.logger.debug("{} {}\n{}".format(method, url, payload_json))
                headers['Content-Type'] = "application/json"
                r = call(url, payload_json, headers=headers, params=params, auth=GliaAuth(souma=self.souma, payload=payload_json))
            r.raise_for_status()
        except requests.exceptions.RequestException, e:
            http_errors = True
            errors.append(e)

        # Try parsing the response
        resp = None
        try:
            resp = r.json()
            self.logger.info("Received data:\n{}".format(resp))
        except ValueError, e:
            resp = None
            parsing_failed = True
            errors.append("Parsing JSON failed: {}".format(e))   
        except UnboundLocalError:
            parsing_failed = True
            errors.append("No data received")

        error_strings = list()
        not_registered = False
        if not parsing_failed and 'meta' in resp:
            for error in resp['meta']['errors']:
                error_strings.append("{}: {}".format(error[0], error[1]))

        # Don't return empty error_strings if parsing server errors has failed, return client-side errors instead
        elif errors:
            error_strings = errors

        # Log all errors
        if errors:
            self.logger.error("{} {} failed.\nParam: {}\nPayload: {}\nErrors:\n* {}".format(
                method, endpoint, params, payload_json, "\n* ".join(str(e) for e in errors)))

        return (resp, error_strings)

    def _update_peer_list(self, persona):
        """
        Retrieve current IPs of persona's peers

        Args:
            persona (persona): The Persona whose peers will be located

        Returns:
            list A list of error messages or None
        """

        self.logger.info("Updating peerlist for {}".format(persona))

        contacts = Persona.query.get(persona.id).contacts

        peer_ids = list()  # peers we want to look up
        for p in contacts:
            peer_ids.append(p.id)

        if len(peer_ids) == 0:
            self.logger.info("{} has no peers. Peerlist update cancelled.".format(persona))
        else:
            # ask glia server for peer info
            resp, errors = self._request_resource("GET", ["sessions"], params={'ids': ",".join(peer_ids)})
            # TODO: Remove peers that are no longer online

            if errors:
                self._log_errors("Error updating peer list", errors)
                return errors

            else:
                offline = 0
                for infodict in resp['sessions']:
                    p_id = infodict['id']
                    soumas = infodict['soumas']

                    if soumas:
                        for souma in soumas:
                            self.soma_discovered.send(self._update_peer_list, message=souma)
                    else:
                        offline += 1
                        self.logger.info("No online souma found for {}".format(contacts.get(p_id)))

                self.logger.info("Updated peer list: {}/{} online".format(len(resp["sessions"])-offline, len(resp)))


    def find_persona(self, address):
        """
        Find personas by their email address

        Args:
            address (string): Email address to search for

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

        self.logger.info("Requesting persona record for email-address {}".format(address))

        app.logger.info("Searching Glia for {}".format(address))
        payload = {
            "email_hash": [sha256(address).hexdigest(), ]
        }

        return self._request_resource("POST", ["personas"], payload=payload)

    def login_all(self):
        """
        Login all personas with a non-empty private key
        """
        persona_set = Persona.query.filter('sign_private != ""').all()
        if len(persona_set) == 0:
            self.logger.warning("No controlled Persona found.")
        else:
            self.logger.info("Logging in {} personas".format(len(persona_set)))
            for p in persona_set:
                self.persona_login(p)


    def myelin_store(self, vesicle):
        """
        Store a Vesicle in Myelin

        Parameters:
            vesicle (Vesicle) The vesicle to be stored

        Returns:
            list List of error strings if such occurred
        """
        self.logger.info("Storing {} in Myelin".format(vesicle))

        data = {
            "vesicles": [vesicle.json(), ]
        }

        resp, errors = self._request_resource("PUT", ["myelin", "vesicles", vesicle.id], payload=data)

        if errors:
            self._log_errors("Error storing {}".format(vesicle), errors)
            return errors
        else:
            self.logger.info("Successfully stored {}".format(vesicle))

    def on_persona_created(self, sender, message):
        """Register new personas with glia-server"""
        persona = message
        self.persona_register(persona)

    def on_persona_modified(self, sender, message):
        """Update persona info on glia-server when changed"""
        self.logger.warning("on_persona_modified not yet implemented")

    def on_persona_deleted(self, sender, message):
        """Delete persona from glia-server"""
        persona = message
        self.persona_unregister(persona)

    def persona_info(self, persona_id):
        """
        Return a dictionary containing info about a persona

        Parameters:
            persona_id (str): Persona ID

        Returns:
            dict persona's public profile and auth_token for authentication
        """
        self.logger.info("Requesting info_dict for <Persona [{}]>".format(persona_id[:6]))
        return self._request_resource("GET", ["personas", persona_id])

    def persona_login(self, persona):
        """
        Login a persona on the server, register if not existing

        Returns:
            str -- new session id
        """

        self.logger.info("Logging in {}".format(persona))

        # Check current state
        if persona.id in self._sessions:
            return self._get_session(persona)["session_id"]

        # Obtain auth token
        info, errors = self._request_resource("GET", ["personas", persona.id])
        if errors:
            self._log_errors("Error logging in", errors)

            # Register persona if not existing
            if ERROR["OBJECT_NOT_FOUND"](None)[0] in map(itemgetter(0), info["meta"]["errors"]):
                errors = self.persona_register(persona)

                if errors:
                    self.logger.error("Failed logging in / registering {}.".format(persona))
                    return None
                else:
                    return self._get_session(persona)["session_id"]
        try:
            auth = info["personas"][0]["auth"]
        except KeyError, e:
            self.logger.warning("Server sent invalid response: Missing `{}` field.".format(e))
            return None

        # Send login request
        data = {
            "personas": [{
                "id": persona.id,
                'auth_signed': persona.sign(auth),
                'reply_to': app.config["SYNAPSE_PORT"]
            }]
        }
        resp, errors = self._request_resource("POST", ["sessions"], payload=data)

        # Read response
        if errors:
            self._log_errors("Login failed", errors)
            return None
        else:
            session_id = resp["sessions"][0]['id']
            timeout = resp["sessions"][0]['timeout']

            self._set_session(persona, session_id, timeout)
            self._queue_keepalive(persona)
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
        self.logger.info("Logging out {}".format(persona))
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

        self.logger.info("Registering {}".format(persona))

        # Create request
        data = {
            "personas": [{
                'persona_id': persona.id,
                'username': persona.username,
                'email_hash': persona.get_email_hash(),
                'sign_public': persona.sign_public,
                'crypt_public': persona.crypt_public,
                'reply_to': app.config['SYNAPSE_PORT']
            }, ]
        }

        response, errors = self._request_resource("PUT", ["personas", persona.id], payload=data)

        if errors:
            self._log_errors("Error creating glia profile for {}".format(persona), errors)
            return errors

        # Evaluate response
        try:
            session_id = response['sessions'][0]['id']
            timeout = response['sessions'][0]['timeout']
        except KeyError, e:
            return ["Invalid server response: Missing key `{}`".format(e)]

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

        self.logger.info("Unregistering {}".format(persona))

        response, errors = self._request_resource("DELETE", ["personas", persona.id])

        if errors:
            self._log_errors("Error unregistering persona {}".format(persona), errors)
        else:
            self.logger.info("Unregisterd persona {} from Glia server:\n{}".format(persona, response))

    def souma_register(self):
        """
        Register this Souma with the glia server

        Returns:
            bool -- True if successful
        """

        self.logger.info("Registering local {} with Glia-server".format(self.souma))

        data = {
            "soumas": [{
                "id": self.souma.id,
                "crypt_public": self.souma.crypt_public,
                "sign_public": self.souma.sign_public,
            }, ]
        }

        response, errors = self._request_resource("POST", ["soumas"], payload=data)

        if errors:
            self._log_errors("Registering {} failed".format(self.souma), errors)
            return False
        else:
            self.logger.info("Successfully registered {} with server".format(self.souma))
            return True


    def shutdown(self):
        """
        Terminate connections and logout
        """
        for p in self._sessions:
            self.persona_logout(p['id'])
