import logging
import json

from dateutil.parser import parse as dateutil_parse
from uuid import uuid4

from nucleus import create_session, notification_signals, PersonaNotFoundError, UnauthorizedError, VesicleStateError, CHANGE_TYPES
from nucleus.models import Persona, Star, Planet, Starmap, Group
from nucleus.vesicle import Vesicle
from synapse.electrical import ElectricalSynapse
from web_ui import app

# These are Vesicle options which are recognized by this Synapse
ALLOWED_MESSAGE_TYPES = [
    "object",
    "object_request",
]

OBJECT_TYPES = ("Star", "Planet", "Persona", "Starmap", "Group")


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
        signal('group-created').connect(self.on_group_created)

    def _distribute_vesicle(self, vesicle, recipients=None):
        """
        Encrypt, sign and distribute vesicle to `recipients` using Myelin

        Args:
            vesicle (Vesicle): The message to transmit.
            recipients (List): List of Persona objects. If recipients is not
                empty, the Vesicle is encrypted and the key is transmitted for
                this list of Personas.

        Returns:
            Vesicle: The (signed and encrypted) Vesicle object
        """
        self.logger.debug("Distributing {} to {} recipients {}".format(
            vesicle,
            len(recipients) if recipients is not None else "0",
            "via Myelin" if app.config["ENABLE_MYELIN"] else ""))

        if not hasattr(vesicle, "author"):
            raise ValueError("Can't send Vesicle without defined author")

        if vesicle.encrypted():
            keycrypt = json.loads(vesicle.keycrypt)

            # First remove everyone from keycrypt that is not a current recipient
            keycrypt = json.loads(vesicle.keycrypt)
            remove_recipients = set(keycrypt.keys()) - set([r.id for r in recipients])
            for recipient_id in remove_recipients:
                if recipient_id != vesicle.author_id:  # Don't remove author!
                    del keycrypt[recipient_id]
            vesicle.keycrypt = json.dumps(keycrypt)

            # Then add the new recipients
            vesicle.add_recipients(recipients)

            self.logger.debug("{} was already encrypted: Modified keycrypt.".format(vesicle))
        else:
            vesicle.encrypt(recipients=recipients)

        try:
            vesicle.sign()
        except VesicleStateError:
            self.logger.info("{} was already signed".format(vesicle))

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

    def handle_object(self, vesicle, reader_persona, session):
        """
        Handle received object updates by verifying the request and calling
        an appropriate handler

        Args:
            vesicle (Vesicle): Vesicle containing the object changeset
            reader_persona (Persona): Persona used for decrypting the Vesicle
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
            new_obj = handler(author, reader_persona, object_type, obj, session)

            if new_obj is not None:
                vesicle.handled = True
                new_obj.vesicles.append(vesicle)

                session.add(new_obj)
                session.add(vesicle)
                session.commit()

    def handle_object_request(self, vesicle, reader_persona, session):
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

            elif hasattr(obj, "author") and recipient not in obj.author.contacts:
                    self.logger.info("Requested {} not published for request author {}".format(obj, recipient))
            elif isinstance(obj, Persona) and recipient not in obj.contacts:
                    self.logger.info("Requested {} does not have requesting {} as a contact.".format(obj, recipient))
            else:
                for v in obj.vesicles:
                    # Send response
                    # Modified vesicles (re-encrypted) don't get saved to DB
                    self._distribute_vesicle(v, recipients=[recipient, ])
                self.logger.info("Sent {}'s {} vesicles to {}".format(
                    obj, len(obj.vesicles), recipient
                ))

        vesicle.handled = True
        session.add(vesicle)
        session.commit()

    def handle_vesicle(self, data):
        """
        Parse received vesicles and call handler

        Args:
            data (String): JSON encoded Vesicle

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

        if vesicle is None:
            self.logger.error("Failed handling Vesicle due to decoding error")
        else:
            old_vesicle = Vesicle.query.get(vesicle.id)
            if old_vesicle is not None:
                vesicle = old_vesicle

            # Vesicle is loaded and has not yet been handled, start processing..
            session = create_session()

            # Decrypt if neccessary
            import keyczar
            if not vesicle.decrypted():
                try:
                    reader_persona = vesicle.decrypt()
                except UnauthorizedError:
                    self.logger.info("Not authorized to decrypt {}".format(vesicle))
                except keyczar.errors.InvalidSignatureError:
                    self.logger.warning("Failed decrypting {}: id={} h={}".format(vesicle, vesicle.id, vesicle._get_hashcode()))
                    return vesicle

            if old_vesicle is None:
                session.add(vesicle)
                session.commit()

            if not vesicle.decrypted():
                self.logger.debug("{} has encrypted payload.".format(vesicle))
            else:
                self.logger.info("{} has payload:\n{}".format(vesicle, json.dumps(vesicle.data, indent=2)))

            # Call handler depending on message type
            try:
                if vesicle is not None and not vesicle.handled and vesicle.message_type in ALLOWED_MESSAGE_TYPES:
                    handler = getattr(self, "handle_{}".format(vesicle.message_type))
                    try:
                        handler(vesicle, reader_persona, session)
                    except UnauthorizedError, e:
                        self.logger.error("Error handling {}: {}".format(vesicle, e))
            except:
                session.rollback()
                raise
            finally:
                session.flush()

        return vesicle

    def object_insert(self, author, recipient, object_type, obj, session):
        # Handle answer
        obj_class = globals()[object_type]
        missing_keys = obj_class.validate_changeset(obj)
        if len(missing_keys) > 0:
            raise KeyError("Missing '{}' for creating {} from changeset".format(
                ", ".join(missing_keys), obj_class.__name__))

        if hasattr(obj, "author_id") and author.id != obj["author_id"]:
            raise UnauthorizedError(
                "Received object_insert Vesicle author {} does not match object author [{}]".format(
                    author, obj["author_id"][:6]))

        o = obj_class.query.get(obj["id"])
        if o is None or (hasattr(o, "get_state") and o.get_state() == -1) or (isinstance(o, Persona) and o._stub is True):
            o = obj_class.create_from_changeset(obj, stub=o, update_sender=author, update_recipient=recipient)
            session.add(o)
            if isinstance(o, Persona):
                o.stub = False
            else:
                o.set_state(0)
            self.logger.info("Inserted new {}".format(o))

        return o

    def object_update(self, author, recipient, object_type, obj, session):
        # Verify message
        obj_class = globals()[object_type]
        missing_keys = obj_class.validate_changeset(obj, update=True)
        if len(missing_keys) > 0:
            raise KeyError("Missing '{}' for updating {} from changeset".format(obj_class.__name__))

        obj_modified = dateutil_parse(obj["modified"])

        # Retrieve local object copy
        o = obj_class.query.get(obj["id"])

        if o is None:
            self.logger.warning("Received update for unknown <{} [{}]>".format(object_type, obj["id"][:6]))

            o = obj_class(id=obj["id"])
            o.set_state(-1)
            session.add(o)

            self.request_object(
                object_type=object_type,
                object_id=obj["id"],
                author=recipient,
                recipient=author,
                session=session)
        else:
            if o.authorize("update", author.id):
                if o.modified <= obj_modified or (hasattr(o, "_stub") and o._stub is True):
                    o.update_from_changeset(obj, update_sender=author, update_recipient=recipient)
                    if isinstance(o, Persona):
                        o.stub = False
                    else:
                        o.set_state(0)
                    session.add(o)
                    self.logger.info("Applied update for {}".format(o))
                else:
                    self.logger.info("Received obsolete update ({})".format(obj))
            else:
                self.logger.warning("{} is not authorized to update {} - update canceled.".format(author, o))

        return o

    def object_delete(self, author, recipient, object_type, obj, session):
        # Verify message
        obj_class = globals()[object_type]
        for k in ["id", "modified"]:
            if k not in obj.keys():
                raise KeyError("Missing '{}' for deleting {} from changeset".format(k, obj_class.__name__))

        # Get the object's class from globals
        o = obj_class.query.get(obj["id"])

        if o is None:
            self.logger.info("Request to delete unknown <{} [{}]>".format(object_type, obj["id"]))
        else:
            if o.authorize("delete", author.id):
                if hasattr(o, "set_state"):
                    o.set_state(-2)
                    o.text = None
                    session.add(o)
                    self.logger.info("{} marked deleted".format(o))
                else:
                    name = str(o)
                    session.delete(o)
                    o = None
                    self.logger.info("Permanently deleted {}".format(name))
            else:
                self.logger.warning("Object deletion not authorized!")
        return o

    def on_new_contact(self, sender, message):
        for k in["new_contact_id", "author_id"]:
            if k not in message:
                raise KeyError("Missing message parameter '{}'".format(k))

        author = Persona.query.get(message["author_id"])
        recipient = Persona.query.get(message["new_contact_id"])

        session = create_session()

        if recipient._stub is True:
            self.logger.info("Requesting profile of new contact {}".format(recipient))
            self.request_object("Persona", message["new_contact_id"], author, recipient, session)

        session.commit()

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

        if obj is None:
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

        vesicle = Vesicle(
            id=uuid4().hex,
            message_type="object",
            data=data,
            author=author,
            handled=True
        )
        obj.vesicles.append(vesicle)

        session = create_session()

        try:
            session.add(vesicle)
            session.commit()
        except:
            session.rollback()
            raise
        else:
            self.logger.info("Local {} changed: Distributing {}".format(obj, vesicle))
            vesicle = self._distribute_vesicle(vesicle, recipients=author.contacts.all())

        session.add(vesicle)
        session.commit()

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

        session = create_session()

        if "author_id" in message:
            author = self.electrical.get_persona(message["author_id"])
        else:
            author = None

        if "recipient_id" in message:
            recipient = self.electrical.get_persona(message["recipient_id"])
        else:
            recipient = None

        try:
            self.request_object(object_type, object_id, author, recipient, session)
        except:
            session.rollback()
            raise
        finally:
            session.flush()

    def on_group_created(self, sender, message):
        # TODO: Implement how to react on blinker notification
        pass

    def request_object(self, object_type, object_id, author, recipient, session):
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

        # Find a source if none is specified
        if recipient is None:
            sources = self._find_source(obj)
            recipient = sources[0] if len(sources) > 0 else None

        if recipient is None:
            self.logger.error("No known source for <{} [{}]>".format(object_type, object_id[:6]))
        else:
            # Try and find a contact of source we can use as this request's author
            if author is None:
                author = recipient.contacts.filter_by(Persona.crypt_private!="").first()

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
            session.add(vesicle)
            session.commit()
            session.refresh(vesicle)

            vesicle = self._distribute_vesicle(vesicle, recipients=[recipient])
            session.add(vesicle)
            session.commit()

    def shutdown(self):
        self.pool.kill()
