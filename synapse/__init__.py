import logging
import json

from dateutil.parser import parse as dateutil_parse
from gevent.pool import Pool
from uuid import uuid4

from nucleus import notification_signals, PersonaNotFoundError, UnauthorizedError, VesicleStateError
from nucleus.models import Persona, Star, Planet, Starmap
from nucleus.vesicle import Vesicle
from synapse.electrical import ElectricalSynapse
from web_ui import app, db

# These are Vesicle options which are recognized by this Synapse
ALLOWED_MESSAGE_TYPES = [
    "object",
    "object_request",
]

CHANGE_TYPES = ("insert", "update", "delete")
OBJECT_TYPES = ("Star", "Planet", "Persona", "Starmap")


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
        signal('request-objects').connect(self.on_request_objects)

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
            if vesicle.encrypted():
                # If the vesicle was already encrypted, only add those new
                # recipients that are contacts of the vesicle author
                new_keycrypt = dict()
                old_keycrypt = json.loads(vesicle.keycrypt)

                # First remove everyone from keycrypt that is not a current recipient
                old_keycrypt = json.loads(vesicle.keycrypt)
                remove_recipients = set(old_keycrypt.keys()) - set([r.id for r in recipients])
                for recipient_id in remove_recipients:
                    del old_keycrypt[recipient_id]
                vesicle.keycrypt = json.dumps(new_keycrypt)

                # Then add the new recipients
                vesicle.add_recipients(recipients)

                # new_recipients = [rec for rec in recipients if rec in vesicle.author.contacts]
                # for rec in new_recipients:
                #     new_keycrypt[rec.id] = old_keycrypt[rec.id]

                self.logger.info("{} was already encrypted.".format(self))
            else:
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

    def _find_source(self, obj):
        """Return a list of possible sources for object.

        A Persona qualifies as source if they have obj in their starmaps,
        have a controlled Persona as a contact.

        Args:
            obj (Star, Planet or Starmap): Object to find a source for

        Returns:
            list: Possible sources
        """
        # Return True if at least one of controlled personas is a contact of p
        connected_to = lambda p: len(p.contacts.filter(Persona.crypt_private != "")) > 0

        sources = list()
        if isinstance(obj, Star):
            if connected_to(obj.author):
                sources.append(obj.author)

            for starmap in obj.starmaps:
                if connected_to(starmap.author):
                    sources.append(starmap.author)

        elif isinstance(obj, Planet):
            for star in obj.stars:
                if connected_to(star.author):
                    sources.append(star.author)

                for starmap in star.starmaps:
                    if connected_to(starmap.author):
                        sources.append(starmap.author)

        elif isinstance(obj, Starmap):
            if connected_to(obj.author):
                sources.append(obj.author)

        # TODO: Sort by last seen
        return sources

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
            new_obj = handler(author, reader_persona, object_type, obj)

            if new_obj is not None:
                new_obj.vesicles.append(vesicle)
                db.session.add(new_obj)
                db.session.commit()

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

            self.logger.debug("Received {} with payload:\n{}".format(vesicle, json.dumps(vesicle.data, indent=2)))

            # Store locally
            db.session.add(vesicle)
            db.session.commit()

            # Call handler depending on message type
            if vesicle.message_type in ALLOWED_MESSAGE_TYPES:
                handler = getattr(self, "handle_{}".format(vesicle.message_type))
                handler(vesicle, reader_persona)

        return vesicle

    def object_insert(self, author, recipient, object_type, obj):
        # Handle answer
        for k in ["id", "modified"]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' in object description".format(k))

        obj_class = globals()[object_type]
        o = obj_class.query.get(obj["id"])

        try:
            obj_modified = dateutil_parse(obj["modified"])
        except ValueError:
            self.logger.error("Malformed parameter 'modified': {}".format(obj["modified"]))
            return

        if o is None:
            if hasattr(obj, "author_id") and author.id != obj["author_id"]:
                raise UnauthorizedError(
                    "Received object_insert Vesicle author {} does not match object author [{}]".format(
                        author, obj["author_id"][:6]))

            o = obj_class.create_from_changeset(obj)

            db.session.add(o)
            db.session.commit()

            self.logger.info("Inserted new {}".format(o))
        elif o.modified < obj_modified or (hasattr(o, "_stub") and o.stub is True):
            self.object_update(author, recipient, object_type, obj)
        else:
            self.logger.info("Received already existing <{} [{}]>".format(object_type, obj["id"]))

        return o

    def object_update(self, author, recipient, object_type, obj):
        # Verify message
        for k in ["id", "modified"]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' in object description".format(k))

        obj_modified = dateutil_parse(obj["modified"])

        # Retrieve local object copy
        obj_class = globals()[object_type]
        o = obj_class.query.get(obj["id"])

        if o is None:
            self.logger.info("Received update for unknown <{} [{}]>".format(object_type, obj["id"][:6]))
            self.request_object(
                object_type=object_type,
                object_id=obj["id"],
                author=recipient,
                recipient=author)
        else:
            if o.modified < obj_modified or (hasattr(o, "_stub") and o.stub is True):
                o.update_from_changeset(obj)
                db.session.add(o)
                db.session.commit()
                self.logger.info("Applied update for {}".format(o))
            else:
                self.logger.info("Received obsolete update ({})".format(obj))

        return o

    def object_delete(self, author, recipient, object_type, obj):
        # Verify message
        for k in ["id", "modified"]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' in object description".format(k))

        # Get the object's class from globals
        obj_class = globals()[object_type]
        o = obj_class.query.get(obj["id"])

        if o is None:
            self.logger.info("Request to delete unknown <{} [{}]>".format(object_type, obj["id"]))
        else:
            if o.author != author:
                raise UnauthorizedError("Deletion request not signed by original object's author.\n" +
                    "{} is not {}".format(o.author, author))

            if hasattr(o, "set_state"):
                o.set_state(-2)
                db.session.add(o)
                db.session.commit()
                self.logger.info("{} marked deleted".format(o))
            else:
                name = str(o)
                db.session.delete(o)
                o = None
                self.logger.info("Permanently deleted {}".format(name))
        return o

    def on_new_contact(self, sender, message):
        for k in["new_contact_id", "author_id"]:
            if k not in message:
                raise KeyError("Missing message parameter '{}'".format(k))

        author = Persona.query.get(message["author_id"])
        recipient = Persona.query.get(message["new_contact_id"])

        self.request_object("Persona", message["new_contact_id"], author, recipient)
        self.logger.info("Requesting new contact {}'s profile".format(recipient))

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
            "object_type": message["object_type"]
        })

        if message["action"] == "insert":
            data["object"] = obj.export()
        elif message["action"] == "update":
            data["object"] = obj.export(update=True)
        elif message["action"] == "delete":
            data["object"] = {
                "id": obj.id,
                "modified": obj.modified.isoformat()
            }

        vesicle = Vesicle(id=uuid4().hex, message_type="object", data=data)
        vesicle.author = author

        db.session.add(vesicle)
        db.session.commit()

        # Add new vesicle to db
        obj.vesicles.append(vesicle)

        self._distribute_vesicle(vesicle, signed=True, recipients=author.contacts.all())

    def on_request_objects(self, sender, message):
        """React to request-objects signal by queuing a request

        Args:
            sender (object): Sender of the signal
            message (dict): Contains keys
                type -- object type as defined in OBJECT_TYPES
                id -- 32 byte object ID
                author_id -- (optional) author of the request
                recipient_id -- (optional) recipient of the request
        """
        try:
            object_type = message["type"]
            object_id = message["id"]
        except KeyError, e:
            self.logger.warning("Missing request parameter '{}'".format(e))
            return

        if "author_id" in message:
            author = self.electrical.get_persona(message["author_id"])
        else:
            author = None

        if "recipient_id" in message:
            recipient = self.electrical.get_persona(message["recipient_id"])
        else:
            recipient = None

        self.request_object(object_type, object_id, author, recipient)

    def request_object(self, object_type, object_id, author, recipient):
        """
        Send a request for an object to a Persona

        Args:
            object_type (String): capitalized class name of the object
            object_id (String): 32 byte object ID
            author (Persona): Author of this request
            recipient (Persona): Persona to request this object from

        Raises:
            UnauthorizedError: If no source can be found that has one of the controlled Personas as a contact
        """
        obj_class = globals()[object_type]
        obj = obj_class.query.get(object_id)

        # Set state to updating
        if obj is not None and hasattr(obj, "set_state"):
            obj.set_state(3)  # updating

        # Find a source if none is specified
        if recipient is None:
            sources = self._find_source(obj)
            recipient = sources[0] if len(sources) > 0 else None

        if recipient is None:
            self.logger.info("No known source for <{} [{}]>".format(object_type, object_id[:6]))
        else:
            # Try and find a contact of source we can use as this request's author
            if author is None:
                author = recipient.contacts.filter_by(Persona.crypt_private != "").first()

            # Abort if no author was found
            if author is None:
                raise UnauthorizedError("Could not find a source for {} who you are contacts with")

            self.logger.info("Requesting <{object_type} {object_id}> as {author} from {source}".format(
                object_type=object_type, object_id=object_id[:6], author=author, source=recipient))

            data = {
                "object_type": object_type,
                "object_id": object_id
            }

            vesicle = Vesicle(
                id=uuid4().hex,
                message_type="object_request",
                author=author,
                data=data
            )

            db.session.add(vesicle)
            db.session.commit()

            self._distribute_vesicle(vesicle, signed=True, recipients=[recipient])

    def shutdown(self):
        self.pool.kill()
