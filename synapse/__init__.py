import datetime
import logging
import gevent
import requests

from dateutil.parser import parse as dateutil_parse
from gevent.pool import Pool
from gevent.server import DatagramServer

from nucleus import notification_signals, source_format, UnauthorizedError, PersonaNotFoundError
from nucleus.models import Persona, Star, Planet
from nucleus.vesicle import Vesicle, PersonaNotFoundError
from synapse.electrical import ElectricalSynapse
from synapse.models import Starmap, Orb
from web_ui import app, db

# These are Vesicle options which are recognized by this Synapse
ALLOWED_MESSAGE_TYPES = [
    "object",
    "object_request"
]

CHANGE_TYPES = ("insert", "update", "delete")
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


    def _connect_signals(self):
        """
        Connect to Blinker signals which are registered in nucleus.__init__
        """

        signal = notification_signals.signal

        signal('model-changed').connect(self.on_local_model_change)
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

    def handle_object(self, vesicle):
        """
        Handle received object updates by verifying the request and calling
        an appropriate handler

        Args:
            vesicle (Vesicle): Vesicle containing the object changeset
        """

        # Validate response
        errors = list()

        try:
            action = vesicle.data["action"]
            object_type = vesicle.data["object_type"]
            obj = vesicle.data["object"]
            author_id = vesicle.author_id
        except KeyError, e:
            errors.append("Missing key: {}".format(e))

        if object_type not in OBJECT_TYPES:
            errors.append("Unknown object type: {}".format(object_type))

        if action not in CHANGE_TYPES:
            errors.append("Unknown action type '{}'".format(action))

        author = Persona.query.get(author_id)
        if not author:
            errors.append("Author {} not found".format(author_id))

        if errors:
            self.logger.error("Malformed object received\n{}".format("\n".join(errors)))
        else:
            handler = getattr(self, "object_{}".format(action))
            handler(author, action, object_type, obj)

    def object_insert(self, author, action, object_type, obj):
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

    def object_update(self, author, action, object_type, obj):
        # Verify message
        for k in ["id", "modified"]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' in object description".format(k))

        try:
            change_time = dateutil_parse(obj["modified"])
        except ValueError:
            self.logger.error("Malformed change time: {}".format(obj["modified"]))
            return

        # Retrieve local object copy

        # Get the object's class from globals
        obj_class = globals()[object_type]
        o = obj_class.query.get(obj["id"])

        if o is None:
            self.logger.info("Received update for nonexistent object")
        else:
            if o.modified < change_time:
                # TODO: Handle update
                self.logger.info("Received update - not applied({})".format(obj))
            else:
                self.logger.info("Received obsolete update ({})".format(obj))

    def object_delete(self, author, action, object_type, obj):
        # Verify message
        for k in ["id", ]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' in object description".format(k))

        # Get the object's class from globals
        obj_class = globals()[object_type]
        o = obj_class.query.get(obj["id"])

        if object_type == "Star":
                if o is None:
                    deleted_star = Star(id=obj["id"], text=None, creator=None)
                    deleted_star.set_state(-2)
                    db.session.add(deleted_star)
                    db.session.commit()
                    self.logger.info("<Star [{}]> marked deleted (no local copy available)".format(obj["id"][:6]))
                elif o.state == -2:
                    self.logger.info("<Star [{}]> is already deleted".format(obj["id"][:6]))
                else:
                    o.set_state(-2)
                    db.session.add(o)
                    db.session.commit()
                    self.logger.info("Deleted {}".format(o))
            else:
                if o is None:
                    self.logger.info("<{} [{}]> deleted (no local copy)".format(
                        object_type, obj["id"][:6]))
                else:
                    db.session.delete(o)
                    self.logger.info("<{} {}> deleted".format(
                        object_type, object_id[:6]))

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

    def on_local_model_change(self, sender, message):
        """
        React to model changes reported from the web-ui by transmitting
        appropriate messages to peers

        Args:
            sender(object): Sender of the Blinker signal
            message(dict): Changeset containing keys in CHANGESET_REQUIRED_FIELDS

        Raises:
            KeyError: Missing key from Changeset
            ValueError: Changeset contains illegal value
        """
        CHANGESET_REQUIRED_FIELDS = ["author_id", "action", "object_id", "object_type"]

        # Verify changeset
        for k in CHANGESET_REQUIRED_FIELDS:
            if k not in message.keys():
                raise KeyError("Missing key: '{}'".format(k))

        if message["action"] not in CHANGE_TYPES:
            raise ValueError("Unknown action: '{}'".format(message["action"]))

        if message["object_type"] not in OBJECT_TYPES:
            raise ValueError("Object type {} not supported".format(message["object_type"]))

        # Get the object's class from globals
        obj_class = globals()[message["object_type"]]
        obj = obj_class.query.get(message["object_id"])

        if not obj:
            # TODO: Use different exception type
            raise Exception("Could not find {} {}".format(obj_class, message["object_id"]))

        # Send Vesicle
        data = dict({
            "action": message["action"],
            "object": obj.export(),
            "object_type": message["object_type"]
        })

        vesicle = Vesicle(message_type="object", data=data)
        vesicle.author_id = message["author_id"]

        self._distribute_vesicle(vesicle, signed=True, recipients=message["author"].contacts)

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
