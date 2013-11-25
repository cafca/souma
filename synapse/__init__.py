import datetime
import logging
import gevent
import requests

from dateutil.parser import parse as dateutil_parse
from gevent.pool import Pool
from gevent.server import DatagramServer

from nucleus import notification_signals, source_format
from nucleus.models import Persona, Star, Planet
from nucleus.vesicle import Vesicle, PersonaNotFoundError
from synapse.electrical import ElectricalSynapse
from synapse.models import Starmap, Orb
from web_ui import app, db

# These are Vesicle options which are recognized by this Synapse
ALLOWED_MESSAGE_TYPES = [
    "change_notification",
    "object_request",
    "object",
    "starmap_request",
    "starmap"
]

CHANGE_TYPES = ("create", "update", "delete")
OBJECT_TYPES = ("Star", "Planet", "Persona")


class Synapse(gevent.server.DatagramServer):
    """
    A Synapse object reacts to local changes in the database and informs
    peers of Personas local to this machine about it. It also receives
    messages from them and updates the local database accordingly. 

    Synapse is a UDP server/client and can also use its ElectricalSynapse
    to exchange information using the Glia/Myelin server.

    Initializing a Synapse object logs in all connected Personas and starts
    listening on the specified port for UDP connections.

    Args:
        address (Tuple)
            0 -- (String) The IP-address this Synapse should listen on.
                Using '0.0.0.0' binds to a public IP address.
            1 -- (String) The port number to listen on.
    """

    # Soumamap contains information about all online soumas
    #
    # It contains values such as:
    # SOUMA_ID: {
    #     "host": string IP_ADDRESS,
    #     "port_external": int PORT_NUMBER_OF_INCOMING_CONNECTIONS,
    #     "port_internal": int PORT_USED_BY_PEER_TO_SEND_VESICLES,
    #     "connectable": bool BEHIND_FIREWALL?,
    #     "starmap": STARMAP
    #     "last_seen": datetime LAST_SEEN
    # }
    soumamap = dict()

    def __init__(self, address):
        DatagramServer.__init__(self, address)

        self.logger = logging.getLogger('synapse')
        self.logger.setLevel(app.config['LOG_LEVEL'])

        # Core setup
        self.starmap = Starmap.query.get(app.config['SOUMA_ID'])
        self.vesicle_pool = gevent.pool.Pool(10)

        # Connect to glia
        self.electrical = ElectricalSynapse(self)
        self.electrical.login_all()

        # Connect to nucleus
        self._connect_signals()

    def _create_starmap(self):
        """
        Create a starmap listing all contents of the local Souma
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
        Connect to Blinker signals which are registered in nucleus.__init__
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

        signal('souma-discovered').connect(self.on_souma_discovered)

    def _distribute_vesicle(self, vesicle, signed=False, recipients=None):
        """
        Distribute vesicle to all online peers. Uses Myelin if enabled.

        Args:
            vesicle (Vesicle): The message to transmit.
            signed (Bool): Set to True to sign using the Persona
                specified in vesicle.author_id
            recipients (List): List of Persona objects. If recipients is not
                empty, the Vesicle is encrypted and the key is transmitted for
                this list of Personas.

        Returns:
            Vesicle: The (signed and encrypted) Vesicle object
        """

        self.logger.debug("Distributing {} {} to {} recipients {}".format(
            "signed" if signed else "unsigned",
            vesicle,
            len(recipients) if recipients is not None else "0", 
            "via Myelin" if app.config["ENABLE_MYELIN"] else ""))

        if hasattr(vesicle, "author_id") and vesicle.author_id is not None:
            author = Persona.query.get(vesicle.author_id)

        if recipients:
            vesicle.encrypt(author, recipients=recipients)

        if signed:
            vesicle.sign(author)

        if app.config["ENABLE_MYELIN"]:
            self.electrical.myelin_store(vesicle)

        for souma_id in self.soumamap.iterkeys():
            # TODO: Check whether that peer has the message already
            self.message_pool.spawn(self.send_vesicle, vesicle, souma_id)

        return vesicle

    def _send_vesicle(self, vesicle, souma_id, signed=False, recipients=None):
        """
        Transmit a Vesicle to a specific Souma

        Args:
            vesicle (Vesicle): This Vesicle is transmitted
            souma_id (String): The ID of the recipient Souma
            signed (Bool): If True, the Vesicle is signed by vesicle.author_id
            recipients (List): List of Persona objects. If specified, the Vesicle
                is encrypted and a key is transmitted for these Personas.
        """
        from gevent import socket

        if souma_id not in self.soumamap.keys():
            self.logger.error("send_vesicle: souma {} not found".format(souma_id))
            return
        else:
            address = (self.soumamap[souma_id]["host"], self.soumamap[souma_id]["port_external"])

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
        Handle incoming connections. This method gets called when a UDP
        connection sends data to this Souma

        Args:
            data (String): Received raw data
            address (Tuple): Source address
                0 -- IP address
                1 -- Port number
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
        Act on received change notifications by updating the local instance
        of the changed object.

        Args:
            vesicle (Vesicle): The received change_notification Vesicle
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

        # Check authority if original object exists
        if o is not None:
            authority = o if object_type == "Persona" else o.creator
            if vesicle.author_id != authority.id:
                self.logger.warning("Unauthorized change request received! ({})".format(vesicle))

        # Check signature
        if not vesicle.signed():
            self.logger.warning("Signature error on change request! ({})".format(vesicle))

        # Reflect changes if neccessary
        elif change == "delete":
            if object_type == "Star":
                if o is None:
                    deleted_star = Star(id=object_id, text=None, creator=None)
                    deleted_star.set_state(-2)
                    db.session.add(deleted_star)
                    db.session.commit()
                    self.logger.info("<Star [{}]> marked deleted (no local copy available)".format(object_id[:6]))
                elif o.state == -2:
                    self.logger.info("<Star [{}]> is already deleted".format(object_id[:6]))
                else:
                    o.set_state(-2)
                    db.session.add(o)
                    db.session.commit()
                    self.logger.info("Deleted {}".format(o))
            else:
                if o is None:
                    self.logger.info("<{} [{}]> deleted (no local copy)".format(
                        object_type, object_id[:6]))
                else:
                    # self.starmap.remove(o)
                    # db.session.add(self.starmap)
                    # db.session.commit()
                    db.session.delete(o)
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
        Act on received objects by storing them if they aren't yet.

        Args:
            vesicle (Vesicle): Vesicle containing the new object
        """

        # Validate response
        errors = list()

        try:
            object_type = vesicle.data["object_type"]
            obj = vesicle.data["object"]
        except KeyError, e:
            errors.append("Missing key: {}".format(e))

        if object_type not in OBJECT_TYPES:
            errors.append("Unknown object type: {}".format(object_type))
            
        if errors:
            self.logger.error("Malformed object received\n{}".format("\n".join(errors)))
        else:
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
                    db.session.commit()
                    self.logger.info("Added new {}".format(o))
                else:
                    self.logger.warning("Received already existing {}".format(o))
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
                    db.session.commit()
                    self.logger.info("Added new {}".format(o))
                else:
                    self.logger.warning("Received already existing {}".format(o))

    def handle_object_request(self, vesicle):
        """
        Act on received object requests by sending the object in question back

        Args:
            vesicle (Vesicle): Vesicle containing metadata about the object
        """

        # Validate vesicle
        errors = []
        object_id = None
        object_type = None

        try:
            object_id = vesicle.data["object_id"]
            object_type = vesicle.data["object_type"]
        except KeyError, e:
            errors.append("missing key ({})".format(vesicle, e))

        if object_type not in OBJECT_TYPES:
            errors.append("invalid object_type: {}".format(object_type))

        if errors:
            self.logger.error("Received malformed object request {}:\n{}".format(vesicle, ("* "+e for e in errors)))
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
        self.send_message(address, vesicle)
        self.logger.info("Sent {object_type} {object_id} to {address}".format(
            object_type=object_type,
            object_id=object_id,
            address=self.source_format(address)
        ))

    def handle_vesicle(self, data, address):
        """
        Parse received vesicles, update soumamap and call handler

        Args:
            data (String): JSON encoded Vesicle
            address (Tuple): Address of the Vesicle's sender for replies
                0 -- IP
                1 -- PORT 

        Returns:
            Vesicle: The Vesicle that was decrypted and loaded
            None: If no Vesicle could be loaded
        """

        try:
            vesicle = Vesicle.read(data)
        except PersonaNotFoundError, e:
            self.logger.info("Received Vesicle from unknown Persona, trying to retrieve Persona info.")
            resp, errors = self.electrical.persona_info(e[0])
            if errors:
                self.logger.warning("Could not retrieve unknown Persona from server:\n{}".format(", ".join(errors)))
                return
            else:
                vesicle = Vesicle.read(data)

        if not vesicle:
            self.logger.error("Failed handling Vesicle due to decoding error")
            return

        if vesicle.souma_id not in self.soumamap and address is not None:
            # Test connectable
            sock = socket.socket(type=socket.SOCK_DGRAM)
            sock.connect(address)
            sock.send("")
            try:
                sock.recvfrom(1)
                connectable = True
            except socket.error:
                connectable = False

            self.soumamap[vesicle.souma_id] = {
                "host": address[0],
                "port_external": address[1],
                "port_internal": vesicle.reply_to,
                "connectable": connectable,
                "starmap": None,
                "last_seen": datetime.datetime.now()
            }

            logging.info("Encountered new souma ({})".format(self.soumamap[vesicle.souma_id][:6]))

        # Decrypt if neccessary
        if vesicle.encrypted():
            reader_persona = None
            for p in Persona.query.filter('sign_private != ""'):
                if p.id in vesicle.keycrypt.keys():
                    reader_persona = p
                    continue

            if reader_persona:
                vesicle.decrypt(p)
                self.logger.info("Decryption of {} successful: {}".format(vesicle, vesicle.data))
            else:
                self.logger.error("Could not decrypt {}. No recipient found in owned personas.".format(vesicle))
                return

        # Store locally
        myelinated = True if address is None else False
        vesicle.save(myelin=myelinated, json=data)

        # Call handler depending on message type
        if vesicle.message_type in ALLOWED_MESSAGE_TYPES:
            handler = getattr(self, "handle_{}".format(vesicle.message_type))
            handler(vesicle)

        return vesicle

    def handle_starmap(self, vesicle):
        """
        Handle received starmaps
        """

        # TODO validate response
        souma_remote_id = message.data['souma_id']
        remote_starmap = message.data['starmap']

        log_starmap = "\n".join(["- <{} {}>".format(
            orb_info['type'], orb_id[:6]) for orb_id, orb_info in remote_starmap.iteritems()])

        self.logger.info("Scanning starmap of {} orbs from {}\n{}".format(
            len(remote_starmap), self.source_format(address), log_starmap))

        # Get or create copy of remote Souma's starmap
        local_starmap = Starmap.query.get(souma_remote_id)
        if local_starmap is None:
            local_starmap = Starmap(souma_remote_id)
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
                request_objects.append((orb_type, orb_id, souma_remote_id))
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
        for orb_type, orb_id, souma_remote_id in request_objects:
            self.message_pool.spawn(self.request_object, orb_type, orb_id, souma_remote_id)

    def handle_starmap_request(self, vesicle):
        """
        Handle received starmap requests
        """

        vesicle = Vesicle("starmap", data={
            'souma_id': app.config['SOUMA_ID'],
            'starmap': self._create_starmap()
        })

        self.logger.info("Sending requested starmap of {} orbs to {}".format(
            len(data), self.source_format(address)))
        self.message_pool.spawn(self._send_vesicle, vesicle, address, signed=True)

    def on_new_contact(self, sender, message):
        logging.warning("New contact signal received from {}: Not implemented.\n{}".format(sender, message))

    def on_star_created(self, sender, message):
        """
        React to star_created signal
        """
        star = message

        # Update starmap
        orb = Orb("Star", star.id, star.modified, star.creator.id)
        self.starmap.add(orb)

        # distribute star in vesicle
        data = dict({
            "object": star.export(),
            "object_type": "Star"
        })

        vesicle = Vesicle(message_type="object", data=data)
        vesicle.author_id = star.creator.id

        self._distribute_vesicle(vesicle, signed=True, recipients=star.creator.contacts)

    def on_star_modified(self, sender, message):
        """
        React to star-modified signal
        """
        star = message

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
            vesicle.author_id = star.creator.id

            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(vesicle, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, star))


    def on_star_deleted(self, sender, message):
        """
        React to star-deleted signal
        """
        star = message

        # Update starmap
        orb = Orb.query.get(star.id)
        if not orb:
            self.logger.error("Orb {} not found".format(orb))
        else:
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
        vesicle.author_id = star.creator.id

        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(vesicle, signed=True, recipients=star.creator.contacts)

    def on_planet_created(self, sender, message):
        """
        React to planet-created signal
        """
        planet = message

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
        vesicle.author_id = planet.creator.id

        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(vesicle, signed=True)

    def on_planet_modified(self, sender, message):
        """
        React to planet-modified signal
        """
        planet = message

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
            vesicle.author_id = planet.creator.id

            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(vesicle, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, planet))

    def on_planet_deleted(self, sender, message):
        """
        React to star-deleted signal
        """
        planet = message

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
        vesicle.author_id = planet.creator.id
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(vesicle, signed=True)

    def on_persona_created(self, sender, message):
        """
        React to persona-created signal
        """
        persona = message

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

        self._distribute_vesicle(vesicle)

    def on_persona_modified(self, sender, message):
        """
        React to persona-modified signal
        """
        persona = message

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
            vesicle.author_id = persona.id
            self.logger.debug("Distributing {}".format(vesicle))

            self._distribute_vesicle(vesicle, signed=True)
        else:
            self.logger.warning("Received modification signal from {} on non-modified {}".format(sender, persona))

    def on_persona_deleted(self, sender, message):
        """
        React to persona-deleted signal
        """
        persona = message

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
        vesicle.author_id = persona.id
        self.logger.debug("Distributing {}".format(vesicle))

        self._distribute_vesicle(vesicle, signed=True)

    def on_souma_discovered(self, sender, message):
        """
        Add new soumas to the soumamap

        souma = {
            "id": string SOUMA_ID
            "host": string IP_ADDRESS,
            "port_external": int PORT_NUMBER_OF_INCOMING_CONNECTIONS,
            "port_internal": int PORT_USED_BY_PEER_TO_SEND_VESICLES,
            "connectable": bool BEHIND_FIREWALL?,
            "last_seen": datetime LAST_SEEN
        }
        """
        souma = message

        try:
            souma_id = souma['id']
            host = souma['host']
            port_external = souma['port_external']
            port_internal = souma['port_internal']
            connectable = souma['connectable']
            last_seen = souma['last_seen']
        except KeyError, e:
            self.logger.error("Invalid souma information: {}".format(e))

        self.soumamap[souma_id] = {
            "host": host,
            "port_external": port_external,
            "port_internal": port_internal,
            "connectable": connectable,
            "starmap": None,
            "last_seen": dateutil_parse(last_seen)
        }

        self.request_starmap(souma_id)
        self.logger.info("Discovered new souma {}@{}".format(souma_id[:6], source_format(host, port)))

    def request_starmap(self, souma_id):
        """
        Request a starmap from the given @param souma_id
        """

        if not souma_id in self.soumamap:
            raise KeyError("Souma {} not found".format(souma_id[:6]))
        s = self.soumamap[souma_id]

        self.logger.info("Requesting starmap from souma {} ({})".format(souma_id[:6],
                         source_format(s['address'], s['port_external'])))

        vesicle = Vesicle("starmap_request", data=dict())
        self._send_vesicle(vesicle, souma_id)

    def request_object(self, object_type, object_id, souma_id):
        """
        Try retrieving object @param object_id of kind @param object_type from @param souma_id
        """

        self.logger.info("Requesting <{object_type} {object_id}> from {source}".format(
            object_type=object_type, object_id=object_id[:6], source=source_format(address)))

        vesicle = Vesicle("object_request", data={
            "object_type": object_type,
            "object_id": object_id
        })

        self._send_vesicle(vesicle, souma_id)

    def shutdown(self):
        self.pool.kill()
