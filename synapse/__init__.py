import logging
import gevent
import requests


from dateutil.parser import parse as dateutil_parse
from nucleus import notification_signals
from nucleus.models import Persona, Star
from nucleus.vesicle import Vesicle
from synapse.electrical import ElectricalSynapse

ALLOWED_MESSAGE_TYPES = [
    "change_notification",
    "object_request",
    "object",
    "starmap_request",
    "starmap"
]

CHANGE_TYPES = ("create", "update", "delete")
OBJECT_TYPES = ("star", "planet", "persona")

PERSONA_NOT_FOUND = 0
SESSION_INVALID = 1


class Synapse(gevent.server.DatagramServer):
    """
    Handles connections with peers
    """

    # Somamap contains information about all online somas
    #
    # It contains values such as:
    # SOMA_ID: {
    #     "host": string IP_ADDRESS,
    #     "port_external": int PORT_NUMBER_OF_INCOMING_CONNECTIONS,
    #     "port_internal": int PORT_USED_BY_PEER_TO_SEND_VESICLES,
    #     "connectable": bool BEHIND_FIREWALL?,
    #     "starmap": STARMAP
    #     "last_seen": datetime LAST_SEEN
    # }
    self.somamap = dict()

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

        stars = Star.query.all()
        personas = Persona.query.all()
        planets = Planet.query.all()

        new_starmap = dict()
        for star in stars:
            new_starmap[star.id] = {
                "type": "Star",
                "creator": star.creator_id,
                "modified": star.modified.isoformat()
            }

        for persona in personas:
            new_starmap[persona.id] = {
                "type": "Persona",
                "creator": None,
                "modified": persona.modified.isoformat()
            }

        for planet in planets:
            new_starmap[planet.id] = {
                "type": "Planet",
                "creator": None,
                "modified": planet.modified.isoformat()
            }

        return new_starmap

    def _connect_signals(self):
        """
        Connect to Blinker signals
        """

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

        signal('soma-discovered').connect(self.on_soma_discovered)

    def _distribute_vesicle(self, vesicle, signed=False, recipients=None):
        """
        Distribute vesicle to online peers

        @param vesicle Contains content and an author.
        @param signed If signed=True vesicle is encrypted given that vesicle.author_id is found
                        locally. Otherwise a NameError is thrown.
        @param recipients A list of persona objects. If this is set the vesicle is
                        encrypted for these recipients.
        """

        if signed:
            author = Persona.query.get(vesicle.author_id)
            vesicle.sign(author)

        if recipients:
            author = Persona.query.get(vesicle.author_id) if author is None else author
            vesicle.encrypt(author, recipients=recipients)

        for host, port in self.peers.iteritems():
            # TODO: Check whether that peer has the message already
            self.message_pool.spawn(self.send_vesicle, vesicle, (host, port))

    def _send_vesicle(self, vesicle, soma_id, signed=False, recipients=None):
        """
        Transmit @param vesicle to specified @param soma_id

        @param soma_id recipient of the vesicle
        @param signed like _distribute_vesicle
        @param recipients like _distribute_vesicle
        """
        from gevent import socket

        if soma_id not in self.somamap.keys():
            self.logger.error("send_vesicle: soma {} not found".format(soma_id))
            return
        else:
            address = (self.somamap[soma_id]["host"], self.somamap[soma_id]["port_external"])

        if signed:
            author = Persona.query.get(vesicle.author_id)
            vesicle.sign(author)

        if recipients:
            author = Persona.query.get(vesicle.author_id) if author is None else author
            vesicle.encrypt(author, recipients=recipients)

        vesicle_json = vesicle.json()

        # Send message
        sock = socket.socket(type=socket.SOCK_DGRAM)
        sock.connect(address)
        sock.send(vesicle_json)

        try:
            data, address = sock.recvfrom(8192)  # Read 8KB
            self.logger.debug("[{source}] replied: '{resp}'".format(
                source=self.source_format(address), resp=data))
        except Exception, e:
            self.logger.error("[{source}] replied: {error}".format(
                source=self.source_format(address), error=e))



    def handle(self, data, address):
        """
        Handle incoming connections
        """
        self.logger.debug("Incoming message\nSource:{}\nLength:{} {}\nContent:{}".format(
            source_format(address),
            len(data),
            "(shortened)" if len(data) > 256 else "",
            data[:256]))

        if len(data) > 0:
            self.handle_vesicle(data, address)
        else:
            sock = socket.socket(type=socket.SOCK_DGRAM)
            sock.connect(address)
            sock.send("OK")
            self.logger.error("Malformed request: too short ({} bytes)\n{}".format(len(data), data))

    def handle_change_notification(self, vesicle):
        """
        Act on received change notifications
        """
        # Verify vesicle
        errors = list()
        try:
            change = vesicle.data["change"]
            object_type = vesicle.data["object_type"]
            object_id = vesicle.data["object_id"]
            change_time = vesicle.data["change_time"]
        except KeyError, e:
            errors.append("missing key\n{}".format(e))

        if change not in CHANGE_TYPES:
            errors.append("unknown change type: {}".format(change))

        if object_type not in OBJECT_TYPES:
            errors.append("unknown object type: {}".format(object_type))

        try:
            change_time = dateutil_parse(change_time)
        except ValueError:
            errors.append("malformed change time: {}".format(change_time))

        if not vesicle.signed():
            errors.append("Invalid or missing signature")

        if len(errors) > 0:
            self.logger.error("Malformed change notification\n{}".format("\n".join(errors)))
            return

        # Check whether the changed object exists locally
        if object_type == "Star":
            o = Star.query.get(object_id)
        elif object_type == "Persona":
            o = Persona.query.get(object_id)
        elif object_type == "Planet":
            o = Planet.query.get(object_id)

        # Reflect changes if neccessary
        if change == "delete":
            # TODO: Verify authority

            if o is None:
                self.logger.info("<{} {}> deleted (no local copy)".format(
                    object_type, object_id[:6]))
            else:
                db.session.delete(o)
                self.starmap.remove(o)
                db.session.add(self.starmap)
                db.session.commit()
                self.logger.info("<{} {}> deleted".format(
                    object_type, object_id[:6]))

        elif change == "insert":
            # Object already exists locally
            if o is not None:
                self.logger.info("{} already exists.".format(o))

            # Request object
            else:
                self.logger.info("New <{} {}> available".format(object_type, object_id[:6]))
                # TODO: Check if we even want to have this thing, also below in update
                self.request_object(object_type, object_id, address)

        elif change == "update":

            #
            # untested
            #

            self.logger.info("Updated {} {} available".format(object_type, object_id))
            if o is None:
                self.request_object(object_type, object_id, address)
            else:
                # Check if this is a newer version
                if o.modified < change_time:
                    self.request_object(object_type, object_id, address)
                else:
                    self.logger.debug("Updated {object_type} {object_id} is obsolete \
                        (Remote modified: {remote} Local modified: {local}".format(
                        object_type=object_type,
                        object_id=object_id, remote=change_time, local=o.modified))

    def handle_object(self, vesicle):
        """
        Act on received objects
        """

        # Validate response
        errors = list()

        try:
            object_type = message.data["object_type"]
            obj = message.data["object"]
        except KeyError, e:
            errors.append("Missing key: {}".format(e))

        if object_type not in OBJECT_TYPES:
            errors.append("Unknown object type: {}".format(object_type))

        if errors:
            self.logger.error("Malformed object received\n{}".format("\n".join(errors)))

        # Handle answer
        # TODO: Handle updates
        if object_type == "Star":
            o = Star.query.get(obj['id'])
            if o is None:
                o = Star(obj["id"], obj["text"], obj["creator_id"])

                orb = Orb.query.get(o.id)
                if not orb:
                    orb = Orb("Star", o.id, o.modified, obj["creator_id"])
                # buggy...
                #self.starmap.add(orb)

                db.session.add(o)
            else:
                self.logger.warning("[{}] Received already existing {}".format(
                    self.source_format(address), o))
        elif object_type == "Persona":
            o = Persona.query.get(obj['id'])
            if o is None:
                o = Persona(
                    id=obj["id"],
                    username=obj["username"],
                    email=obj["email"],
                    sign_public=obj["sign_public"],
                    crypt_public=obj["crypt_public"],
                )

                orb = Orb.query.get(o.id)
                if not orb:
                    orb = Orb("Persona", o.id, o.modified)
                #self.starmap.add(orb)

                db.session.add(o)
            else:
                self.logger.warning("[{}] Received already existing {}".format(
                    self.source_format(address), o))
        db.session.commit()
        self.logger.info("[{}] Received {}".format(
            self.source_format(address), o))

    def handle_object_request(self, vesicle):
        """
        Act on received object requests
        """

        # Validate vesicle
        errors = []
        object_id = None
        object_type = None

        try:
            object_id = message.data["object_id"]
            object_type = message.data["object_type"]
        except KeyError, e:
            errors.append("missing key ({})".format(vesicle, e))

        if object_type not in OBJECT_TYPES:
            errors.append("invalid object_type: {}".format(object_type))

        if errors:
            self.logger.error("Received malformed object request {}:\n{}".format(vesicle, "* "+e for e in errors))
            return

        # Load object
        obj = None
        if object_type == "Star":
            obj = Star.query.get(object_id)
        elif object_type == "Persona":
            obj = Persona.query.get(object_id)
        elif object_type == "Planet":
            obj = Planet.query.get(object_id)

        if obj is None:
            # TODO: Serve error message
            self.logger.error("Requested object <{type} {id}> not found".format(
                type=object_type, id=object_id[:6]))
            self.socket.sendto(str(), address)
            return

        # Construct response
        data = {
            "object": obj.export(exclude=["sign_private, crypt_private"]),
            "object_type": object_type
        }
        vesicle = Vesicle("object", data)

        # Send response
        self.send_message(address, message)
        self.logger.info("Sent {object_type} {object_id} to {address}".format(
            object_type=object_type,
            object_id=object_id,
            address=self.source_format(address)
        ))

    def handle_vesicle(self, data, address):
        """
        Parse received vesicles, update somamap and call handler
        """

        vesicle = Vesicle.read(data)
        if not vesicle:
            return

        if vesicle.soma_id not in self.somamap:
            # Test connectable
            sock = socket.socket(type=socket.SOCK_DGRAM)
            sock.connect(address)
            sock.send("")
            try:
                sock.recvfrom(1)
                connectable = True
            except socket.error:
                connectable = False

            self.somamap[soma_id] = {
                "host": address[0],
                "port_external": address[1],
                "port_internal": vesicle.reply_to,
                "connectable": connectable,
                "starmap": None,
                "last_seen": datetime.datetime.now()
            }

            logging.info("Encountered new soma ({})".format(self.somamap[soma_id][:6])

        #
        #
        # DECRYPT AND CHECK SIGNATURE
        #
        #

        # Call handler depending on message type
        if vesicle.message_type in ALLOWED_MESSAGE_TYPES:
            handler = getattr(self, "handle_{}".format(vesicle.message_type))
            handler(vesicle)

    def handle_starmap(self, vesicle):
        """
        Handle received starmaps
        """

        # TODO validate response
        soma_remote_id = message.data['soma_id']
        remote_starmap = message.data['starmap']

        log_starmap = "\n".join(["- <{} {}>".format(
            orb_info['type'], orb_id[:6]) for orb_id, orb_info in remote_starmap.iteritems()])

        self.logger.info("Scanning starmap of {} orbs from {}\n{}".format(
            len(remote_starmap), self.source_format(address), log_starmap))

        # Get or create copy of remote Soma's starmap
        local_starmap = Starmap.query.get(soma_remote_id)
        if local_starmap is None:
            local_starmap = Starmap(soma_remote_id)
            db.session.add(local_starmap)

        request_objects = list()  # list of objects to be downloaded
        for orb_id, orb_info in remote_starmap.iteritems():
            orb_type = orb_info['type']
            orb_modifed = iso8601.parse_date(orb_info['modified'])
            orb_creator = orb_info['creator']

            # Create Orb if the object has not been seen before
            orb_local = Orb.query.get(orb_id)
            if orb_local is None:
                orb_local = Orb(orb_type, orb_id, orb_modifed, orb_creator)
                db.session.add(orb_local)

            # Request corresponding object if this object is not yet in
            # our own starmap (greedy downloading)
            #if not orb_local in self.starmap.index:

            # As the above doesnt work yet (*bug*), check directly
            if (orb_type == 'Star' and Star.query.get(orb_id) is None) \
              or (orb_type == "Persona" and Persona.query.get(orb_id) is None) \
              or (orb_type == "Planet" and Planet.query.get(orb_id) is None):
                request_objects.append((orb_type, orb_id, soma_remote_id))
            # Also download if the remote version is newer
            # elif orb_modifed > orb_local.modified:
            #     request_objects.append((orb_type, orb_id, address))

            # Add to local copy of the remote starmap to keep track of
            # who already has the Orb
            if orb_local not in local_starmap.index:
                local_starmap.index.append(orb_local)
                db.session.add(local_starmap)
        db.session.commit()

        # Spawn requests
        for orb_type, orb_id, soma_remote_id in request_objects:
            self.message_pool.spawn(self.request_object, orb_type, orb_id, soma_remote_id)

    def handle_starmap_request(self, vesicle):
        """
        Handle received starmap requests
        """

        vesicle = Vesicle("starmap", data={
            'soma_id': app.config['SOMA_ID'],
            'starmap': self._create_starmap()
        })

        self.logger.info("Sending requested starmap of {} orbs to {}".format(
            len(data), self.source_format(address)))
        self.message_pool.spawn(self._send_vesicle, vesicle, address, signed=True)

    def on_star_created(self, sender, star):
        """
        React to star_created signal
        """
        # Update starmap
        orb = Orb("Star", star.id, star.modified, star.creator.id)
        self.starmap.add(orb)

        # distribute notification_message
        data = dict({
            "object_type": "Star",
            "object_id": star.id,
            "change": "create",
            "change_time": star.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_star_modified(self, sender, star):
        """
        React to star-modified signal
        """
        # Update starmap
        orb = Orb.query.get(star.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))
        if orb.modified != star.modified:
            orb.modified = star.modified
            db.session.add(orb)
            db.session.commit()

            # distribute notification_message
            data = dict({
                "object_type": "Star",
                "object_id": star.id,
                "change": "update",
                "change_time": star.modified.isoformat()
            })

            vesicle = Vesicle(message_type="change_notification", data=data)
            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(message, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, star))


    def on_star_deleted(self, sender, star):
        """
        React to star-deleted signal
        """
        # Update starmap
        orb = Orb.query.get(star.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))
        db.session.delete(orb)
        db.session.commit()

        # distribute notification_message
        data = dict({
            "object_type": "Star",
            "object_id": star.id,
            "change": "delete",
            "change_time": star.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_planet_created(self, sender, planet):
        """
        React to planet-created signal
        """
        # Update starmap
        orb = Orb("Planet", planet.id, planet.modified)
        self.starmap.add(orb)

        # distribute notification_message
        data = dict({
            "object_type": "Planet",
            "object_id": planet.id,
            "change": "create",
            "change_time": planet.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_planet_modified(self, sender, planet):
        """
        React to planet-modified signal
        """
        # Update starmap
        orb = Orb.query.get(planet.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))

        if orb.modified != planet.modified:
            orb.modified = planet.modified
            db.session.add(orb)
            db.session.commit()

            # distribute notification_message
            data = dict({
                "object_type": "Planet",
                "object_id": planet.id,
                "change": "update",
                "change_time": planet.modified.isoformat()
            })

            vesicle = Vesicle(message_type="change_notification", data=data)
            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(message, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, planet))

    def on_planet_deleted(self, sender, planet):
        """
        React to star-deleted signal
        """
        # Update starmap
        orb = Orb.query.get(planet.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))
        db.session.delete(orb)
        db.session.commit()

        # distribute notification_message
        data = dict({
            "object_type": "Planet",
            "object_id": planet.id,
            "change": "delete",
            "change_time": planet.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_persona_created(self, sender, persona):
        """
        React to persona-created signal
        """
        # Update starmap
        orb = Orb("Persona", persona.id, persona.modified)
        self.starmap.add(orb)

        # distribute notification_message
        data = dict({
            "object_type": "Persona",
            "object_id": persona.id,
            "change": "create",
            "change_time": persona.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_persona_modified(self, sender, persona):
        """
        React to persona-modified signal
        """
        # Update starmap
        orb = Orb.query.get(persona.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))

        if orb.modified != persona.modified:
            orb.modified = persona.modified
            db.session.add(orb)
            db.session.commit()

            # distribute notification_message
            data = dict({
                "object_type": "Persona",
                "object_id": persona.id,
                "change": "update",
                "change_time": persona.modified.isoformat()
            })

            vesicle = Vesicle(message_type="change_notification", data=data)
            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(message, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, persona))

    def on_persona_deleted(self, sender, persona):
        """
        React to persona-deleted signal
        """
        # Update starmap
        orb = Orb.query.get(persona.id)
        if not orb:
            raise NameError("Orb {} not found".format(orb))
        db.session.delete(orb)
        db.session.commit()

        # distribute notification_message
        data = dict({
            "object_type": "Persona",
            "object_id": persona.id,
            "change": "delete",
            "change_time": persona.modified.isoformat()
        })

        vesicle = Vesicle(message_type="change_notification", data=data)
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(message, signed=True)

    def on_soma_discovered(self, sender, soma):
        """
        Add new somas to the somamap

        soma = {
            "id": string SOMA_ID
            "host": string IP_ADDRESS,
            "port_external": int PORT_NUMBER_OF_INCOMING_CONNECTIONS,
            "port_internal": int PORT_USED_BY_PEER_TO_SEND_VESICLES,
            "connectable": bool BEHIND_FIREWALL?,
            "last_seen": datetime LAST_SEEN
        }
        """
        try:
            soma_id = soma['id']
            host = soma['host']
            port_external = soma['port_external']
            port_internal = soma['port_internal']
            connectable = soma['connectable']
            last_seen = soma['last_seen']
        except KeyError, e:
            self.logger.error("Invalid soma information: {}".format(e))

        self.somamap[soma_id] = {
            "host": host,
            "port_external": port_external,
            "port_internal": port_internal,
            "connectable": connectable,
            "starmap": None,
            "last_seen": dateutil_parse(last_seen)
        }

        self.request_starmap(soma_id)
        self.logger.info("Discovered new soma {}@{}".format(soma_id, source_format(host, port)))

    def request_starmap(self, soma_id):
        """
        Request a starmap from the given @param soma_id
        """

        if not soma_id in self.somamap:
            raise KeyError("Soma {} not found".format(soma_id[:6]))
        s = self.somamap[soma_id]

        self.logger.info("Requesting starmap from soma {} ({})".format(soma_id[:6],
            source_format(s['address'], s['port_external'])))

        vesicle = Vesicle("starmap_request", data=dict())
        self._send_vesicle(vesicle, soma_id, signed=True)

    def request_object(self, object_type, object_id, soma_id):
        """
        Try retrieving object @param object_id of kind @param object_type from @param soma_id
        """

        self.logger.info("Requesting <{object_type} {object_id}> from {source}".format(
            object_type=object_type, object_id=object_id[:6], source=source_format(address)))

        vesicle = Vesicle("object_request", data={
            "object_type": object_type,
            "object_id": object_id
        })

        self._send_vesicle(vesicle, soma_id, signed=True)

    def shutdown(self):
        self.pool.kill()
    