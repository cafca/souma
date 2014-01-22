import logging
import iso8601

from dateutil.parser import parse as dateutil_parse

from gevent.pool import Pool
from nucleus import notification_signals, PersonaNotFoundError, UnauthorizedError, VesicleStateError
from nucleus.models import Persona, Star, Planet, Starmap
from nucleus.vesicle import Vesicle
from synapse.electrical import ElectricalSynapse
from uuid import uuid4
from web_ui import app, db

# These are Vesicle options which are recognized by this Synapse
ALLOWED_MESSAGE_TYPES = [
    "object",
    "object_request",
    "starmap",
    "starmap_request"
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
        self.vesicle_pool = Pool(10)

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

        if recipients:
            vesicle.encrypt(recipients=recipients)

        if signed:
            try:
                vesicle.sign()
            except VesicleStateError:
                self.logger.info("{} was already signed".format(vesicle))

        db.session.add(vesicle)
        db.session.commit()

        if app.config["ENABLE_MYELIN"]:
            self.electrical.myelin_store(vesicle)

        return vesicle

    def _log_errors(self, msg, errors, level="error"):
        """
        Log a list of errors to the logger

        Args:
            msg(str): A message describing the error source
            errors(list): A list of error messages

        Raises:
            ValueError: If the specified log level is invalid
        """

        if level not in ["debug", "info", "warning", "error"]:
            raise ValueError("Invalid log level {}".format(level))

        call = getattr(self.logger, level)
        call("{msg}:\n{list}".format(msg=msg, list="\n* ".join(str(e) for e in errors)))

    def handle_object(self, vesicle, reader_persona):
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
            author = vesicle.author
        except KeyError, e:
            errors.append("Missing key: {}".format(e))

        if object_type not in OBJECT_TYPES:
            errors.append("Unknown object type: {}".format(object_type))

        if action not in CHANGE_TYPES:
            errors.append("Unknown action type '{}'".format(action))

        if errors:
            self.logger.error("Malformed object received\n{}".format("\n".join(errors)))
        else:
            handler = getattr(self, "object_{}".format(action))
            handler(author, action, object_type, obj)

    def handle_object_request(self, vesicle, reader_persona):
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
            recipient = vesicle.author
        except KeyError, e:
            errors.append("missing ({})".format(vesicle, e))

        if object_type not in OBJECT_TYPES:
            errors.append("invalid object_type: {}".format(object_type))

        if errors:
            self._log_errors("Received invalid object request", errors)
        else:
            # Load object
            obj_class = globals()[object_type]
            obj = obj_class.query.get(object_id)

            if obj is None:
                self.logger.error("Requested object <{type} {id}> not found".format(
                    type=object_type, id=object_id[:6]))
            else:
                for vesicle in obj.vesicles:
                    # Send response
                    self._distribute_vesicle(vesicle, recipients=[recipient, ])
                    self.logger.info("Sent {} {} to {}".format(
                        object_type, object_id, recipient
                    ))

    def handle_vesicle(self, data):
        """
        Parse received vesicles and call handler

        Args:
            data (String): JSON encoded Vesicle

        Returns:
            Vesicle: The Vesicle that was decrypted and loaded
            None: If no Vesicle could be loaded

        Raises:
            PersonaNotFoundError: If the Vesicle author cannot be retrieved
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

        if vesicle is None:
            self.logger.error("Failed handling Vesicle due to decoding error")
        elif Vesicle.query.get(vesicle.id) is not None:
            self.logger.info("Received duplicate {}".format(vesicle))
            vesicle = None
        else:
            # Decrypt if neccessary
            if vesicle.encrypted():
                reader_persona = vesicle.decrypt()

            # Store locally
            db.session.add(vesicle)
            db.session.commit()

            # Call handler depending on message type
            if vesicle.message_type in ALLOWED_MESSAGE_TYPES:
                handler = getattr(self, "handle_{}".format(vesicle.message_type))
                handler(vesicle, reader_persona)

        return vesicle

    def handle_starmap(self, vesicle, reader_persona):
        """
        Handle received starmaps

        Args:
            vesicle (Vesicle): A signed Vesicle containing a Starmap object
            reader_persona (Persona): A Persona object contained in the Vesicle's keycrypt
        """
        # Validate vesicle
        errors = list()

        remote = vesicle.data['starmap']

        for k in ["id", "modified", "author_id", "index"]:
            if k not in remote:
                errors.append("Missing '{}'".format(k))

        author = self.electrical.get_persona(remote["author_id"])
        if author is None:
            errors.append('Starmap author {} not found'.format(remote["author_id"]))

        if author != vesicle.author:
            errors.append("Vesicle does not originate from Starmap author")

        if errors:
            self._log_errors("Error handling Starmap", errors)

        log_starmap = "\n".join(["- <{} {}>".format(
            star_info['type'], star_info["id"][:6]) for star_info in remote["index"]])

        self.logger.info("Scanning starmap of {} stars received from {}\n{}".format(
            len(remote["index"]), vesicle.author, log_starmap))

        # Get or create copy of remote Souma's starmap
        local_starmap = Starmap.query.get(remote["id"])
        if local_starmap is None:
            local_starmap = Starmap(
                id=remote["id"],
                modified=remote["modified"],
                author=author
            )
            db.session.add(local_starmap)
            db.session.commit()

        # Iterate over starmap contents, checking whether objects need
        # to be downloaded
        request_objects = list()  # list of objects to be downloaded
        for star_info in remote.index():
            try:
                # Collect Star info
                star_id = star_info["id"]
                star_author_id = star_info["author_id"]
                star_modified = iso8601.parse_date(star_info['modified'])

                # Get or create local Star object
                star = Star.query.get(star_id)
                if star is None:
                    star_author = self.electrical.get(star_author_id)

                    star = Star(
                        id=star_id,
                        text=None,
                        creator=star_author,

                    )
                    star.set_state(-1)
                    db.session.add(star)
                    db.session.commit()

                    request_objects.append(("Star", star_id))

                # Request Star if outdated or state is 'unavailable'
                elif star.get_state() == -1 or star.modified < star_modified:
                    request_objects.append(("Star", star_id))

                # Iterate over Planets attached to current Star
                for planet in star_info["planets"]:
                    planet_id = planet["id"]
                    planet_modified = planet["modified"]

                    planet = Planet.query.get(planet_id)
                    if planet is None:
                        planet = Planet(
                            id=planet_id,
                            modified=planet_modified
                        )
                        planet.set_state(-1)
                        db.session.add(planet)
                        db.session.commit()

                        request_objects.append(("Planet", planet_id))

                    elif planet.get_state() == -1 or planet.modified < planet_modified:
                        request_objects.append(("Planet", planet_id))
            except KeyError, e:
                self.logger.warning("Missing '{}' in {}\nReceived: {}".format(
                    e, local_starmap, star_info))

        # Spawn requests
        for object_type, object_id in request_objects:
            self.message_pool.spawn(self.request_object, object_type, object_id, vesicle.author)

    def handle_starmap_request(self, vesicle, reader_persona):
        """
        Handle received starmap requests

        Args:
            vesicle (Vesicle): Request data
        """
        # Verify request
        errors = list()

        for k in ["starmap_id", ]:
            if not k in vesicle.data:
                errors.append("Missing '{}' in request data".format(k))

        starmap_id = vesicle.data["starmap_id"]
        starmap = Starmap.query.get(starmap_id)
        if starmap is None:
            errors.append("Starmap {} not found".format(starmap_id))

        if errors:
            self._log_errors("Error processing starmap request from {}".format(vesicle.author),
                             errors, level="warning")
            # TODO: Send error message back
        else:
            for starmap_vesicle in starmap.vesicles:
                self.logger.info("Sending requested {} to {}".format(
                    starmap_vesicle, vesicle.author))
                self._distribute_vesicle(starmap_vesicle, recipients=[vesicle.author, ])

    def object_insert(self, author, action, object_type, obj):
        # Handle answer
        # TODO: Handle updates
        if object_type == "Star":
            o = Star.query.get(obj['id'])
            if o is None:
                creator = self.electrical.get_persona(obj["creator_id"])

                if creator != author:
                    raise UnauthorizedError("Received object update is not signed by object creator")

                o = Star(
                    id=obj["id"],
                    text=obj["text"],
                    creator=creator
                )

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
                if o.creator != author:
                    raise UnauthorizedError("Received deletion request not signed by original object's creator")
                o.set_state(-2)
                db.session.add(o)
                db.session.commit()
                self.logger.info("Deleted {}".format(o))
        else:
            if o is None:
                self.logger.info("<{} [{}]> deleted (no local copy)".format(
                    object_type, obj["id"][:6]))
            else:
                # TODO: Check authority
                db.session.delete(o)
                self.logger.info("<{} {}> deleted".format(
                    object_type, obj["id"][:6]))

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

        vesicle = Vesicle(id=uuid4().hex, message_type="object", data=data)
        vesicle.author_id = message["author_id"]

        db.session.add(vesicle)
        db.session.commit()

        # Add new vesicle to db
        obj.vesicles.append(vesicle)

        signed = False if message["object_type"] == "Persona" else True

        self._distribute_vesicle(vesicle, signed=signed, recipients=author.contacts)

    def request_object(self, object_type, object_id, author, recipient):
        """
        Send a request for an object to a Persona

        Args:
            object_type (String): capitalized class name of the object
            object_id (String): 32 byte object ID
            recipient (Persona): Persona to request this object from
        """
        self.logger.info("Requesting <{object_type} {object_id}> from {source}".format(
            object_type=object_type, object_id=object_id[:6], source=recipient))

        vesicle = Vesicle(id=uuid4().hex, message_type="object_request", author=author, data={
            "object_type": object_type,
            "object_id": object_id
        })

        self._distribute_vesicle(vesicle, signed=True, recipients=[recipient])

    def shutdown(self):
        self.pool.kill()
