import datetime
import logging
import gevent
import requests

from dateutil.parser import parse as dateutil_parse
from gevent.pool import Pool

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


class Synapse():
    """
    A Synapse reacts to local changes in the database and transmits
    them to each Persona's peers using the Myelin API. It also keeps 
    Glia up to date on all Persona's managed by this Souma.
    """

    def __init__(self):
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

        signal('local-model-changed').connect(self.on_local_model_change)
        signal('new-contact').connect(self.on_new_contact)

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

        return vesicle


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
        Parse received vesicles and call handler

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

        author = Persona.query.get(message["author_id"])

        # Send Vesicle
        data = dict({
            "action": message["action"],
            "object": obj.export(),
            "object_type": message["object_type"]
        })

        vesicle = Vesicle(message_type="object", data=data)
        vesicle.author_id = message["author_id"]

        self._distribute_vesicle(vesicle, signed=True, recipients=author.contacts)

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
