import datetime
import logging
import requests

from dateutil.parser import parse as dateutil_parse
from flask import json
from gevent import Greenlet
from gevent.pool import Pool
from gevent.server import DatagramServer
from requests import ConnectionError
from soma import app, db, notification_signals
from soma.web_ui.models import Persona, Star, ContactRequestNotification
from soma.synapse.models import Message


class Synapse(DatagramServer):
    """ Handle connections to peers """

    def __init__(self, address):
        # UDP server
        DatagramServer.__init__(self, address)

        self.logger = logging.getLogger('synapse')
        self.logger.setLevel(logging.INFO)

        # Test connection to glia-server
        url = "http://{host}/".format(host=app.config['LOGIN_SERVER'])
        try:
            requests.get(url)
        except ConnectionError, e:
            self.logger.error("Could not establish connection to glia server\n - {}".format(e))
            quit()

        # Queue messages for sending
        self.message_pool = Pool(10)

        # Format a host address
        self.source_format = lambda address: None if address is None else \
            "{host}:{port}".format(host=address[0], port=address[1])

        self.sessions = dict()

        # Contains addresses of online peers as peer_id: (host,port)
        self.peers = dict()

        # Create blinker signals
        self.signal = notification_signals.signal

        star_created = self.signal('star-created')
        star_deleted = self.signal('star-deleted')
        persona_created = self.signal('persona-created')
        contact_request_sent = self.signal('contact-request-sent')
        self.signal('contact-request-received')

        # Subscribe notification message distribution to signals
        star_created.connect(self.on_notification_signal)
        star_deleted.connect(self.on_notification_signal)

        persona_created.connect(self.on_notification_signal)
        persona_created.connect(self.on_persona_created)

        contact_request_sent.connect(self.on_contact_request_sent)

        # Login all owned personas
        persona_set = Persona.query.filter('sign_private != ""').all()
        for p in persona_set:
            self.message_pool.spawn(self.login, p)

        if len(persona_set) == 0:
            self.logger.warning("No controlled Persona found.")

    def request_object(self, object_type, object_id, address):
        """ Request an object from a peer """
        self.logger.info("Requesting {object_type} {object_id} from {source}".format(
            object_type=object_type, object_id=object_id, source=self.source_format(address)))

        # Construct request
        data = {"object_type": object_type, "object_id": object_id}
        message = Message("object_request", data)

        # Send request
        self.send_message(address, message)

    def handle(self, data, address):
        """ Handle incoming connections """
        if len(data) == 0:
            self.logger.info("[{}] Empty message received".format(address[0]))
        else:
            self.logger.debug("[{source}] Received {l} bytes: {json}".format(
                source=self.source_format(address), json=data, l=len(data)))
            self.socket.sendto('Received {} bytes'.format(len(data)), address)

            if address[0] in self.peers:
                return_address = (address[0], self.peers[address[0]])
            else:
                return_address = address
                self.logger.warning("No known return path for message sender {}".format(
                    self.source_format(address)))

            # TODO: Attempt correcting time of message by comparing machine clocks in the message
            #   (see bittorrent utp spec)

            self.handle_message(data, return_address)

    def handle_message(self, data, address):
        """Parse received Message objects and pass them on to the correct handler"""

        # Try parsing the message
        try:
            message = Message.read(data)
        except KeyError, e:
            self.logger.error("[{source}] Message malformed ({error})".format(
                source=self.source_format(address), error=e))
            return

        # Allowed message types
        message_types = [
            "change_notification",
            "object_request",
            "object",
            "inventory_request",
            "inventory",
            "contact_request"
        ]

        # Pass on the message depending on message type
        if message.message_type in message_types:
            handler = getattr(self, "handle_{message_type}".format(message_type=message.message_type))
            handler(message, address)

    def handle_change_notification(self, message, address):
        """ Delete or download the object the notification was about if that is neccessary """

        # Verify message
        # TODO: Check authenticity and authority
        change = message.data["change"]
        object_type = message.data["object_type"]
        object_id = message.data["object_id"]
        change_time = dateutil_parse(message.data["change_time"])

        # Load object if it exists
        if object_type == "Star":
            o = Star.query.get(object_id)
        elif object_type == "Persona":
            o = Persona.query.get(object_id)

        # TODO: Update inventory db

        # Reflect changes if neccessary
        if change == "delete":
            # Check authority to delete
            if o is None:
                self.logger.info("[{source}] {object_type} {object_id} deleted (no local copy)".format(
                    source=self.source_format(address), object_type=object_type, object_id=object_id))
            else:
                db.session.delete(o)
                db.session.commit()
                self.logger.info("[{source}] {object_type} {object_id} deleted".format(
                    source=self.source_format(address), object_type=object_type, object_id=object_id))

        elif change == "insert":
            # Object already exists locally
            if o is not None:
                self.logger.info("[{source}] New {object_type} {object_id} already exists.".format(
                    source=self.source_format(address), object_type=object_type, object_id=object_id))

            # Request object
            else:
                self.logger.info("[{source}] New {object_type} {object_id} available".format(
                    source=self.source_format(address), object_type=object_type, object_id=object_id))
                # TODO: Check if we even want to have this thing, also below in update
                self.request_object(object_type, object_id, address)

        elif change == "update":

            #
            # WIP & untested
            #

            self.logger.info("[{source}] Updated {object_type} {object_id} available".format(
                source=self.source_format(address), object_type=object_type, object_id=object_id))
            if o is None:
                self.request_object(object_type, object_id, address)
            else:
                # Check if this is a newer version
                if o.modified < change_time:
                    self.request_object(object_type, object_id, address)
                else:
                    self.logger.debug("[{source}] Updated {object_type} {object_id} is obsolete \
                        (Remote modified: {remote} Local modified: {local}".format(
                        source=self.source_format(address), object_type=object_type,
                        object_id=object_id, remote=change_time, local=o.modified))
        else:
            self.logger.error("[{msg}] Protocol error: Unknown change type '{change}'".format(
                msg=message, change=change))

    def handle_contact_request(self, message, address):
        """Handle received contact request"""

        # Validate request
        author_id = message.author_id
        recipient_id = message.data['recipient_id']

        author = Persona.query.get(author_id)
        if author is None:
            self.logger.info("Creating missing request author persona.")
            self.handle_object(message, address)

        p = Persona.query.get(recipient_id)
        if p is None or p.sign_private is None:
            # The requested persona is not available
            # TODO: Return error response
            self.logger.warning("Received a contact request addressed to a foreign persona. ({})".format(author))
        else:
            self.logger.info("Received contact request for {} from {}".format(p, author))
            # Save contacting persona
            if Persona.query.get(author_id) is None:
                self.handle_object(message, ('', ''))

            # Create notification to ask user for confirmation
            notif = ContactRequestNotification(author_id, recipient_id)
            db.session.add(notif)
            db.session.commit()

            # Send signal
            self.signal('contact-request-received').send(self.server_request, message=message)

    def handle_inventory(self, message, address):
        """ Look through an inventory to see if we want to download some of it """
        pass

    def handle_inventory_request(self, message, address):
        """ Send an inventory of published objects to the given address """
        pass

    def handle_object(self, message, address):
        """ Handle a received download """
        # Validate response
        # TODO: Decryption
        object_type = message.data["object_type"]
        obj = message.data["object"]

        # Handle answer
        # TODO: Handle updates
        if object_type == "Star":
            o = Star(obj["id"], obj["text"], obj["creator_id"])
        elif object_type == "Persona":
            # private key is not assumed
            o = Persona(
                id=obj["id"],
                username=obj["username"],
                email=obj["email"],
                sign_public=obj["sign_public"],
                crypt_public=obj["crypt_public"],
            )
        db.session.add(o)
        db.session.commit()
        self.logger.info("[{source}] Added new {object_type} {object_id}".format(
            source=self.source_format(address), object_type=object_type, object_id=obj['id']))

    def handle_object_request(self, message, address):
        """ Serve an object to address in response to a request """
        object_id = message.data["object_id"]
        object_type = message.data["object_type"]

        # Load object
        if object_type == "Star":
            obj = Star.query.get(object_id)
        elif object_type == "Persona":
            obj = Persona.query.get(object_id)

        if obj is None:
            # TODO: Serve error message
            self.logger.error("Requested object {type} <{id}> not found".format(
                type=object_type, id=object_id))
            self.socket.sendto(str(), address)
            return

        # Construct response
        data = {
            "object": obj.export(exclude=["sign_private, crypt_private"]),
            "object_type": object_type
        }
        message = Message("object", data)

        # Sign message
        if object_type == "Star" and obj.creator.sign_private != "":
            message.sign(obj.creator)
        elif object_type == "Persona" and obj.sign_private != "":
            message.sign(obj)

        # Send response
        self.send_message(address, message)
        self.logger.info("Sent {object_type} {object_id} to {address}".format(
            object_type=object_type,
            object_id=object_id,
            address=self.source_format(address)
        ))

    def inventory(self):
        """ Return inventory of all data stored on this machine in json format """

        # CURRENTLY NOT IN USE

        stars = Star.query.all()
        personas = Persona.query.all()

        inventory = dict()
        for star in stars:
            inventory[star.id] = {
                "type": "Star",
                "creator": star.creator_id,
                "modified": star.modified
            }

        for persona in personas:
            inventory[persona.id] = {
                "type": "persona",
                "modified": persona.modified,
                "email_hash": persona.email_hash
            }

        inventory_json = json.dumps(inventory)
        return inventory_json

    def on_notification_signal(self, sender, message):
        """ Distribute notification messages """
        self.logger.info("[{sender}] Distributing {msg}".format(sender=sender, msg=message))
        self.distribute_message(message)

    def on_persona_created(self, sender, message):
        """ Register newly created personas with server """
        persona_id = message.data['object_id']
        persona = Persona.query.get(persona_id)
        self.register_persona(persona)

    def on_contact_request_sent(self, sender, message):
        """ Send a contact request to the login server """
        self.logger.info("Sending contact request to server")
        url = "http://{host}/contact-request".format(host=app.config['LOGIN_SERVER'])
        resp, errors = self.server_request(url, message)
        if errors:
            for e in errors:
                self.logger.error("[pm-send contact request] {}".format(e))

    def distribute_message(self, message):
        """ Distribute a message to all peers who don't already have it """
        if self.peers:
            for host, port in self.peers.iteritems():
                # TODO: Check whether that peer has the message already
                self.message_pool.spawn(self.send_message, (host, port), message)

    def send_message(self, address, message):
        """ Send a message  """
        from gevent import socket

        message_json = message.json()

        # Send message
        sock = socket.socket(type=socket.SOCK_DGRAM)
        sock.connect(address)
        sock.send(message_json)
        try:
            data, address = sock.recvfrom(8192)  # Read 8KB
            self.logger.info("[{source}] replied: '{resp}'".format(
                source=self.source_format(address), resp=data))
        except Exception, e:
            self.logger.error("[{source}] replied: {error}".format(
                source=self.source_format(address), error=e))

    def server_request(self, url, message=None):
        """ HTTP request to server. Parses response and returns (resp, error_strings). """
        # Make request
        if message:
            headers = {"Content-Type": "application/json"}
            r = requests.post(url, message.json(), headers=headers)
            self.logger.debug("Posted request to server:\n{}".format(r.request.body))
        else:
            r = requests.get(url)
            self.logger.debug("Sent request to server:\n{} {}\n{}".format(
                r.request.method, r.request.url, r.request.body))

        # Parse response
        error_strings = list()

        # Status code above 400 means the request failed
        if r.status_code >= 400:
            error_strings.append("{} (HTTP error)".format(r.status_code))
            return (None, error_strings)

        # Parse JSON, extract errors
        else:
            resp = r.json()
            if 'errors' in resp['data']:
                for error in resp['data']['errors']:
                    error_strings.append("{}: {}".format(error[0], error[1]))

            # Intercept notifications
            if 'notifications' in resp['data']:
                notifications = resp['data']['notifications']

                # n contains a json string
                for n in notifications:
                    self.logger.info("Received notification message")
                    self.handle_message(n, (app.config['LOGIN_SERVER_HOST'], app.config['LOGIN_SERVER_PORT']))

            #self.logger.debug("[server] Received data: {}".format(resp))
            return (resp, error_strings)

    def update_peer_list(self, persona):
        """ Update list of current peer host addresses """

        if app.config['LOCAL_PORT'] == 5000:
            self.peers = {"127.0.0.1": 5051}
        else:
            self.peers = {"127.0.0.1": 5050}

        self.logger.info("Updated peer list ({} online)".format(len(self.peers)))

    def login(self, persona):
        """ Create session at login server """

        # Check current state
        url = "http://{host}/{persona_id}/".format(host=app.config['LOGIN_SERVER'], persona_id=persona.id)
        resp, errors = self.server_request(url)

        if errors:
            self.logger.error("Login failed with errors:\n{}".format("\n".join(errors)))
            if not resp:
                return

            # Check error list for code 3 (persona not found) and register new persona if found
            if 3 in [t[0] for t in resp['data']['errors']]:
                self.register_persona(persona)
                return

        # Persona is already logged in
        elif 'session_id' in resp['data']:
            self.logger.info("Persona {} already logged in.".format(persona))
            self.sessions[persona.id] = {
                'session_id': resp['data']['session_id'],
                'timeout': resp['data']['timeout']
            }
            self.queue_keepalive(persona)
            return

        # Do login
        if 'auth' in resp['data']:
            data = {
                'auth_signed': persona.sign(resp['data']['auth'])
            }
            r, errors = self.server_request(url, Message('session', data))

            if errors:
                self.logger.error("Login failed:\n{}".format("\n".join(errors)))
            else:
                self.sessions[persona.id] = {
                    'session_id': r['data']['session_id'],
                    'timeout': r['data']['timeout'],
                }
                self.logger.info("Persona {} logged in until {}".format(
                    persona, dateutil_parse(r['data']['timeout'])))
                self.queue_keepalive(persona)

    def keep_alive(self, persona):
        """ Ping server to keep session alive """

        url = "http://{host}/{persona_id}/".format(host=app.config['LOGIN_SERVER'], persona_id=persona.id)
        r, errors = self.server_request(url)

        if errors:
            self.logger.error("Error in keep_alive for {}:\n{}".format(
                persona, "\n".join(errors)))

            # Login if session is invalid
            if r and 6 in [t[0] for t in r['data']['errors']]:
                self.login(persona)
        else:
            self.sessions[persona.id] = {
                'session_id': r['data']['session_id'],
                'timeout': r['data']['timeout']
            }
            self.queue_keepalive(persona)

    def queue_keepalive(self, persona):
        """ Send keep-alive some time before the session times out """

        if persona.id not in self.sessions:
            send_in_seconds = 2
        else:
            buf = 30  # seconds
            timeout = dateutil_parse(self.sessions[persona.id]['timeout'])
            send_in_seconds = (timeout - datetime.datetime.now()).seconds - buf
            if send_in_seconds < 0:
                send_in_seconds = 2

        ping = Greenlet(self.keep_alive, persona)
        ping.start_later(send_in_seconds)

    def register_persona(self, persona):
        """ Register a persona on the login server """
        self.logger.info("Registering persona {} with login server".format(persona))

        # Create request
        data = {
            'persona_id': persona.id,
            'username': persona.username,
            'email_hash': persona.get_email_hash(),
            'sign_public': persona.sign_public,
            'crypt_public': persona.crypt_public,
            'reply_to': app.config['SYNAPSE_PORT']
        }
        message = Message('create_persona', data)

        url = "http://{host}/{persona}/create".format(host=app.config['LOGIN_SERVER'], persona=persona.id)
        response, errors = self.server_request(url, message=message)

        if errors:
            self.logger.error("Error creating account on server:\n{}".format("\n".join(errors)))

        # Evaluate response
        if 'session_id' in response['data']:
            self.logger.info("Registered {} with server.".format(persona))
            self.sessions[persona.id] = {
                'session_id': response['data']['session_id'],
                'timeout': response['data']['timeout'],
            }
            self.update_peer_list(persona)
            self.queue_keepalive(persona)

    def delete_account(self):
        """ Remove a persona from login server, currently not implemented """
        pass

    def shutdown(self):
        self.pool.kill()
        self.logout()
