import datetime
import json
import iso8601

from base64 import b64encode, b64decode
from flask import url_for, session
from hashlib import sha256
from keyczar.keys import RsaPrivateKey, RsaPublicKey
from sqlalchemy import ForeignKey
from uuid import uuid4

from nucleus import ONEUP_STATES, STAR_STATES, PLANET_STATES, \
    PersonaNotFoundError, UnauthorizedError, notification_signals, CHANGE_TYPES
from web_ui import app, db
from web_ui.helpers import epoch_seconds

request_objects = notification_signals.signal('request-objects')


class Serializable():
    """ Make SQLAlchemy models json serializable

    Attributes:
        _insert_required: Default attributes to include in export
        _update_required: Default attributes to include in export with update=True
    """
    id = None
    modified = None

    _insert_required = ["id", "modified"]
    _update_required = ["id", "modified"]

    def authorize(self, action, author_id=None):
        """Return True if this object authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if action not in CHANGE_TYPES:
            return False
        return True

    def export(self, exclude=[], update=False):
        """Return this object as a dict.

        Args:
            update (Bool): Export only attributes defined in `self._update_required`

        Returns:
            Dict: The serialized object

        Raises:
            KeyError: If a key was not found
        """
        attr_names = self._update_required if update is True else self._insert_required
        attr_names = [a for a in attr_names if a not in exclude]

        return {attr: str(getattr(self, attr)) for attr in attr_names}

    def json(self, update=False):
        """Return this object JSON encoded.

        Args:
            update (Boolean): (optiona) See export docstring

        Returns:
            Str: JSON-encoded serialized instance
        """
        return json.dumps(self.export(update=update), indent=4)

    @classmethod
    def validate_changeset(cls, changeset, update=False):
        """Check whether changeset contains all keys defined as required for this class.

        Args:
            changeset(dict): See created_from_changeset, update_from_changeset
            update(Bool): If True use cls._update_required instead of cls._insert_required

        Returns:
            List: Missing keys
        """
        required_keys = cls._update_required if update else cls._insert_required
        missing = list()

        for k in required_keys:
            if k not in changeset.keys():
                missing.append(k)
        return missing

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new instance from a changeset.

        Args:
            changeset (dict): Dictionary of model values. Requires all keys
                defined in cls._insert_required with class-specific values.
            stub (Serializable): (Optional) model instance whose values will be
                overwritten with those defined in changeset.
            update_sender (Persona): (Optional) author of this changeset. Will be
                used as recipient of subsequent object requests.
            update_recipient (Persona): (Optional) recipient of this changeset.
                Will be used as sender of subsequent object requests.

        Returns:
            Serializable: Instance created from changeset

        Raises:
            KeyError: Missing key in changeset
            TypeError: Argument has wrong type
            ValueError: Argument value cannot be processed
        """
        raise NotImplementedError()

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update self with new values in changeset

        Args:
            changeset (dict): Dictionary of model values. Requires all keys
                defined in self._update_required with class-specific values.
            update_sender (Persona): (Optional) author of this changeset. Will be
                used as recipient of subsequent object requests.
            update_recipient (Persona): (Optional) recipient of this changeset.
                Will be used as sender of subsequent object requests.

        Returns:
            Serializable: Updated instance

        Raises:
            KeyError: Missing key in changeset
            TypeError: Argument has wrong type
            ValueError: Argument value cannot be processed
        """
        raise NotImplementedError()


t_identity_vesicles = db.Table(
    'identity_vesicles',
    db.Column('identity_id', db.String(32), db.ForeignKey('identity.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Identity(Serializable, db.Model):
    """Abstract identity, superclass of Persona and Group

    Attributes:
        _insert_required: Attributes that are serialized
        id: 32 byte ID generated by uuid4().hex
        username: Public username of the Identity, max 80 bytes
        crypt_private: Private encryption RSA key, JSON encoded KeyCzar export
        crypt_public: Public encryption RSA key, JSON encoded KeyCzar export
        sign_private: Private signing RSA key, JSON encoded KeyCzar export
        sign_public: Public signing RSA key, JSON encoded KeyCzar export
        modified: Last time this Identity object was modified, defaults to now
        vesicles: List of Vesicles that describe this Identity object
        profile: Starmap containing this Identity's profile page

    """

    __tablename__ = "identity"

    _insert_required = ["id", "username", "crypt_public", "sign_public", "modified", "profile_id"]
    _update_required = ["id", "modified"]

    _stub = db.Column(db.Boolean, default=False)
    id = db.Column(db.String(32), primary_key=True)
    kind = db.Column(db.String(32))
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    username = db.Column(db.String(80))
    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)

    vesicles = db.relationship(
        'Vesicle',
        secondary='identity_vesicles',
        primaryjoin='identity_vesicles.c.identity_id==identity.c.id',
        secondaryjoin='identity_vesicles.c.vesicle_id==vesicle.c.id')

    profile_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    profile = db.relationship('Starmap', primaryjoin='starmap.c.id==identity.c.profile_id')

    __mapper_args__ = {
        'polymorphic_identity': 'identity',
        'polymorphic_on': kind
    }

    def __repr__(self):
        return "<@{} [{}]>".format(str(self.username), self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Identity authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Identity ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            return (self.id == author_id)
        return False

    def controlled(self):
        """
        Return True if this Identity has private keys attached
        """
        if self.crypt_private is not None and self.sign_private is not None:
            return True
        else:
            return False

    @staticmethod
    def list_controlled():
        return Identity.query.filter('Identity.sign_private != ""')

    def generate_keys(self, password):
        """ Generate new RSA keypairs for signing and encrypting. Commit to DB afterwards! """

        # TODO: Store keys encrypted
        rsa1 = RsaPrivateKey.Generate()
        self.sign_private = str(rsa1)
        self.sign_public = str(rsa1.public_key)

        rsa2 = RsaPrivateKey.Generate()
        self.crypt_private = str(rsa2)
        self.crypt_public = str(rsa2.public_key)

    def encrypt(self, data):
        """ Encrypt data using RSA """

        key_public = RsaPublicKey.Read(self.crypt_public)
        return b64encode(key_public.Encrypt(data))

    def decrypt(self, cypher):
        """ Decrypt cyphertext using RSA """

        cypher = b64decode(cypher)
        key_private = RsaPrivateKey.Read(self.crypt_private)
        return key_private.Decrypt(cypher)

    def sign(self, data):
        """ Sign data using RSA """

        key_private = RsaPrivateKey.Read(self.sign_private)
        signature = key_private.Sign(data)
        return b64encode(signature)

    def verify(self, data, signature_b64):
        """ Verify a signature using RSA """

        signature = b64decode(signature_b64)
        key_public = RsaPublicKey.Read(self.sign_public)
        return key_public.Verify(data, signature)

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """See Serializable.create_from_changeset"""
        request_list = list()

        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        if stub:
            ident = stub
            ident.id = changeset["id"]
            ident.username = changeset["username"]
            ident.crypt_public = changeset["crypt_public"]
            ident.sign_public = changeset["sign_public"]
            ident.modified = modified_dt
            ident._stub = False
        else:
            ident = Identity(
                id=changeset["id"],
                username=changeset["username"],
                crypt_public=changeset["crypt_public"],
                sign_public=changeset["sign_public"],
                modified=modified_dt,
            )

        # Update profile
        profile = Starmap.query.get(changeset["profile_id"])
        if profile is None or profile.get_state() == -1:
            request_list.append({
                "type": "Starmap",
                "id": changeset["profile_id"],
                "author_id": update_recipient.id,
                "recipient_id": update_sender.id,
            })

        if profile is None:
            profile = Starmap(id=changeset["profile_id"])
            profile.state = -1

        ident.profile = profile

        app.logger.info("Created {} identity from changeset, now requesting {} linked objects".format(
            ident, len(request_list)))

        for req in request_list:
            request_objects.send(Identity.create_from_changeset, message=req)

        return ident

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """See Serializable.update_from_changeset"""
        request_list = list()

        # Update modified
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified_dt

        # Update username
        if "username" in changeset:
            self.username = changeset["username"]
            app.logger.info("Updated {}'s {}".format(self.username, "username"))

        # Update profile
        if "profile_id" in changeset:
            profile = Starmap.query.get(changeset["profile_id"])
            if profile is None or profile.get_state() == -1:
                request_list.append({
                    "type": "Starmap",
                    "id": changeset["profile_id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })
                app.logger.info("Requested {}'s {}".format(self.username, "profile starmap"))
            else:
                self.profile = profile
                app.logger.info("Updated {}'s {}".format(self.username, "profile starmap"))

        app.logger.info("Updated {} identity from changeset. Requesting {} objects.".format(self, len(request_list)))

        for req in request_list:
            request_objects.send(Identity.create_from_changeset, message=req)

#
# Setup follower relationship on Persona objects
#

t_contacts = db.Table(
    'contacts',
    db.Column('left_id', db.String(32), db.ForeignKey('persona.id')),
    db.Column('right_id', db.String(32), db.ForeignKey('persona.id'))
)


class Persona(Identity):
    """A Persona represents a user profile

    Attributes:
        email: An email address, max 120 bytes
        contacts: List of this Persona's contacts
        index: Starmap containing all Star's this Persona publishes to its contacts
        myelin_offset: Datetime of last request for Vesicles sent to this Persona

    """
    __mapper_args__ = {
        'polymorphic_identity': 'persona'
    }

    _insert_required = Identity._insert_required + ["email", "index_id", "contacts"]
    _update_required = Identity._update_required

    id = db.Column(db.String(32), db.ForeignKey('identity.id'), primary_key=True)
    email = db.Column(db.String(120))

    contacts = db.relationship(
        'Persona',
        secondary='contacts',
        lazy="dynamic",
        primaryjoin='contacts.c.left_id==persona.c.id',
        secondaryjoin='contacts.c.right_id==persona.c.id')

    index_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    index = db.relationship('Starmap', primaryjoin='starmap.c.id==persona.c.index_id')

    # Myelin offset stores the date at which the last Vesicle receieved from Myelin was created
    myelin_offset = db.Column(db.DateTime)

    def authorize(self, action, author_id=None):
        """Return True if this Persona authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Identity.authorize(self, action, author_id=author_id):
            return (self.id == author_id)
        return False

    def get_email_hash(self):
        """Return sha256 hash of this user's email address"""
        return sha256(self.email).hexdigest()

    def get_absolute_url(self):
        return url_for('persona', id=self.id)

    def export(self, update=False):
        data = Identity.export(self, exclude=["contacts", ], update=update)

        data["contacts"] = list()
        for contact in self.contacts:
            data["contacts"].append({
                "id": contact.id,
            })

        return data

    @staticmethod
    def request_persona(persona_id):
        """Return a Persona profile, loading it from Glia if neccessary

        Args:
            persona_id (String): ID of the required Persona

        Returns:
            Persona: If a record was found
            None: If no record was found
        """
        from synapse import ElectricalSynapse
        electrical = ElectricalSynapse()
        return electrical.get_persona(persona_id)

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """See Serializable.create_from_changeset"""
        p = Identity.create_from_changeset(changeset,
            stub=stub, update_sender=update_sender, update_recipient=update_recipient)

        request_list = list()

        p.email = changeset["email"]

        # Update index
        index = Starmap.query.get(changeset["index_id"])
        if index is None or index.get_state() == -1:
            request_list.append({
                "type": "Starmap",
                "id": changeset["index_id"],
                "author_id": update_recipient.id,
                "recipient_id": update_sender.id,
            })

        if index is None:
            index = Starmap(id=changeset["index_id"])
            index.state = -1

        p.index = index

        # Update contacts
        missing_contacts = p.update_contacts(changeset["contacts"])
        for mc in missing_contacts:
            request_list.append({
                "type": "Persona",
                "id": mc["id"],
                "author_id": update_recipient.id,
                "recipient_id": update_sender.id,
            })

        app.logger.info("Made {} a Persona object, now requesting {} linked objects".format(
            p, len(request_list)))

        for req in request_list:
            request_objects.send(Persona.create_from_changeset, message=req)

        return p

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """See Serializable.update_from_changeset"""
        Identity.update_from_changeset(self, changeset,
            update_sender=update_sender, update_recipient=update_recipient)

        app.logger.info("Now applying Persona-specific updates for {}".format(self))

        request_list = list()

        # Update email
        if "email" in changeset:
            if isinstance(changeset["email"], str):
                self.email = changeset["email"]
                app.logger.info("Updated {}'s {}".format(self.username, "email"))
            else:
                app.logger.warning("Invalid `email` supplied in update for {}\n\n".format(
                    self, changeset))

        # Update index
        if "index_id" in changeset:
            index = Starmap.query.get(changeset["index_id"])
            if index is None or index.get_state() == -1:
                request_list.append({
                    "type": "Starmap",
                    "id": changeset["index_id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })
                app.logger.info("Requested {}'s new {}".format(self.username, "index starmap"))
            else:
                self.index = index
                app.logger.info("Updated {}'s {}".format(self.username, "index starmap"))

        # Update contacts
        if "contacts" in changeset:
            missing_contacts = self.update_contacts(changeset["contacts"])
            for mc in missing_contacts:
                request_list.append({
                    "type": "Persona",
                    "id": mc["id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })

        app.logger.info("Updated {} from changeset. Requesting {} objects.".format(self, len(request_list)))

        for req in request_list:
            request_objects.send(Persona.update_from_changeset, message=req)

    def update_contacts(self, contact_list):
        """Update Persona's contacts from a list of the new contacts

        Args:
            contact_list (list): List of dictionaries with keys:
                id (String) -- 32 byte ID of the contact

        Returns:
            list: List of missing Persona IDs to be requested
        """
        updated_contacts = 0
        request_list = list()

        # remove_contacts contains all old contacts at first, all current
        # contacts get then removed so that the remaining can get deleted
        remove_contacts = set(self.contacts)

        for contact in contact_list:
            c = Persona.query.get(contact["id"])

            if c is None:
                c = Persona(id=contact["id"], _stub=True)
                request_list.append(contact["id"])
            else:
                updated_contacts += 1

                try:
                    remove_contacts.remove(c)
                except KeyError:
                    pass

            self.contacts.append(c)

        for contact in remove_contacts:
            self.contacts.remove(contact)

        app.logger.info("Updated {}'s contacts: {} added, {} removed, {} requested".format(
            self.username, updated_contacts, len(remove_contacts), len(request_list)))

        return request_list


t_star_vesicles = db.Table(
    'star_vesicles',
    db.Column('star_id', db.String(32), db.ForeignKey('star.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Star(Serializable, db.Model):
    """A Star represents a post"""

    __tablename__ = "star"

    _insert_required = ["id", "text", "created", "modified", "author_id", "planet_assocs"]
    _update_required = ["id", "text", "modified"]

    id = db.Column(db.String(32), primary_key=True)
    text = db.Column(db.Text)
    kind = db.Column(db.String(32))

    created = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())

    state = db.Column(db.Integer, default=0)

    author = db.relationship('Identity',
        backref=db.backref('stars'),
        primaryjoin="identity.c.id==star.c.author_id")
    author_id = db.Column(db.String(32), db.ForeignKey('identity.id'))

    planet_assocs = db.relationship("PlanetAssociation",
        backref="star",
        lazy="dynamic")

    vesicles = db.relationship('Vesicle',
        secondary='star_vesicles',
        primaryjoin='star_vesicles.c.star_id==star.c.id',
        secondaryjoin='star_vesicles.c.vesicle_id==vesicle.c.id')

    parent = db.relationship('Star',
        primaryjoin='and_(Star.id==Star.parent_id, Star.state>=0)',
        backref=db.backref('children', lazy="dynamic"),
        remote_side='Star.id')
    parent_id = db.Column(db.String(32), db.ForeignKey('star.id'))

    __mapper_args__ = {
        'polymorphic_identity': 'star',
        'polymorphic_on': kind
    }

    def __repr__(self):
        try:
            ascii_text = self.text.encode('utf-8')
        except AttributeError:
            ascii_text = "No text content"
        return "<Star {}: {}>".format(
            self.id[:6],
            (ascii_text[:24] if len(ascii_text) <= 24 else ascii_text[:22] + ".."))

    def authorize(self, action, author_id=None):
        """Return True if this Star authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            return author_id == self.author.id
        return False

    @property
    def comments(self):
        return self.children.filter_by(kind="star")

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """See Serializable.create_from_changeset"""
        created_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        if stub is not None:
            star = stub
            star.text = changeset["text"]
            star.author = None
            star.created = created_dt
            star.modified = modified_dt
        else:
            star = Star(
                id=changeset["id"],
                text=changeset["text"],
                author=None,
                created=created_dt,
                modified=modified_dt,
            )

        author = Persona.query.get(changeset["author_id"])
        if author is None:
            # TODO: Send request for author
            star.author_id = changeset["author_id"]
        else:
            star.author = author

        app.logger.info("Created new Star from changeset")

        # Append planets to new Star
        for planet_assoc in changeset["planet_assocs"]:
            if not PlanetAssociation.validate_changeset(planet_assoc):
                app.logger.warning("Invalid changeset for planet associated with {}\n\n{}".format(star, changeset))
            else:
                author = Persona.request_persona(planet_assoc["author_id"])
                pid = planet_assoc["planet"]["id"]

                # TODO: Better lookup method for planet classes
                if planet_assoc["planet"]["kind"] == "link":
                    planet_cls = LinkPlanet
                elif planet_assoc["planet"]["kind"] == "linkedpicture":
                    planet_cls = LinkedPicturePlanet

                planet = planet_cls.query.get(pid)
                if planet is None:
                    planet = planet_cls.create_from_changeset(planet_assoc["planet"])
                else:
                    planet.update_from_changeset(planet_assoc["planet"])

                assoc = PlanetAssociation(author=author, planet=planet)
                star.planet_assocs.append(assoc)
                app.logger.info("Added {} to new {}".format(planet, star))

        return star

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a Star from a changeset (See Serializable.update_from_changeset)"""
        # Update modified
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified_dt

        # Update text
        self.text = changeset["text"]

        for planet_assoc in changeset["planet_assocs"]:
            if not PlanetAssociation.validate_changeset(planet_assoc):
                app.logger.warning("Invalid changeset for planet associated with {}\n{}".format(self, changeset))
            else:
                author = Persona.request_persona(planet_assoc["author_id"])
                pid = planet_assoc["planet"]["id"]

                assoc = PlanetAssociation.filter_by(star_id=self.id).filter_by(planet_id=pid).first()
                if assoc is None:
                    planet = Planet.query.get(pid)
                    if planet is None:
                        planet = Planet.create_from_changeset(planet_assoc["planet"])
                    else:
                        planet.update_from_changeset(planet_assoc["planet"])

                    assoc = PlanetAssociation(author=author, planet=planet)
                    self.planet_assocs.append(assoc)
                    app.logger.info("Added {} to {}".format(planet, self))

        app.logger.info("Updated {} from changeset".format(self))

    def export(self, update=False):
        """See Serializable.export"""

        data = Serializable.export(self, exclude=["planets", ], update=update)

        data["planet_assocs"] = list()
        for planet_assoc in self.planet_assocs:
            data["planet_assocs"].append({
                "planet": planet_assoc.planet.export(),
                "author_id": planet_assoc.author_id
            })

        return data

    def get_state(self):
        """
        Return publishing state of this star.

        Returns:
            Integer:
                -2 -- deleted
                -1 -- unavailable
                0 -- published
                1 -- draft
                2 -- private
                3 -- updating
        """
        return STAR_STATES[self.state][0]

    def set_state(self, new_state):
        """
        Set the publishing state of this star

        Parameters:
            new_state (int) code of the new state as defined in nucleus.STAR_STATES

        Raises:
            ValueError: If new_state is not an Int or not a valid state of this object
        """
        new_state = int(new_state)
        if new_state not in STAR_STATES.keys():
            raise ValueError("{} ({}) is not a valid star state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    def get_absolute_url(self):
        return url_for('star', id=self.id)

    def hot(self):
        """i reddit"""
        from math import log
        # Uncomment to assign a score with analytics.score
        #s = score(self)
        s = 1.0
        order = log(max(abs(s), 1), 10)
        sign = 1 if s > 0 else -1 if s < 0 else 0
        return round(order + sign * epoch_seconds(self.created) / 45000, 7)

    @property
    def oneups(self):
        """Returns a query for all oneups, including disabled ones"""
        return self.children.filter_by(kind="oneup")

    def oneupped(self):
        """
        Return True if active Persona has 1upped this Star
        """

        oneup = self.oneups.filter_by(author_id=session["active_persona"]).first()

        if oneup is None or oneup.state < 0:
            return False
        else:
            return True

    def oneup_count(self):
        """
        Return the number of verified upvotes this Star has receieved

        Returns:
            Int: Number of upvotes
        """
        return self.oneups.filter(Oneup.state >= 0).count()

    def comment_count(self):
        """
        Return the number of comemnts this Star has receieved

        Returns:
            Int: Number of comments
        """
        return self.comments.filter_by(state=0).count()

    def toggle_oneup(self, author_id=None):
        """
        Toggle 1up for this Star on/off

        Args:
            author_id (String): Optional Persona ID that issued the 1up. Defaults to active Persona.

        Returns:
            Oneup: The toggled oneup object

        Raises:
            PersonaNotFoundError: 1up author not found
            UnauthorizedError: Author is a foreign Persona
        """

        if author_id is None:
            author = Persona.query.get(session["active_persona"])
        else:
            author = Persona.query.get(author_id)

        if author is None:
            raise PersonaNotFoundError("1up author not found")

        if not author.controlled():
            raise UnauthorizedError("Can't toggle 1ups with foreign Persona {}".format(author))

        # Check whether 1up has been previously issued
        oneup = self.oneups.filter_by(author=author).first()
        if oneup is not None:
            old_state = oneup.get_state()
            oneup.set_state(-1) if oneup.state == 0 else oneup.set_state(0)
        else:
            old_state = False
            oneup = Oneup(id=uuid4().hex, author=author, parent=self)
            self.children.append(oneup)

        # Commit 1up
        db.session.add(self)
        db.session.commit()
        app.logger.info("{verb} {obj}".format(verb="Toggled" if old_state else "Added", obj=oneup, ))

        return oneup

    def link_url(self):
        """Return URL if this Star has a Link-Planet

        Returns:
            String: URL of the first associated Link
            Bool: False if no link was found
        """
        # planet_assoc = self.planet_assocs.join(PlanetAssociation.planet.of_type(LinkPlanet)).first()

        for planet_assoc in self.planet_assocs:
            if planet_assoc.planet.kind == "link":
                return planet_assoc.planet.url
        return None

    def has_picture(self):
        """Return True if this Star has a Picture-Planet"""
        count = self.planet_assocs.join(PlanetAssociation.planet.of_type(LinkedPicturePlanet)).count()
        return count > 0


class PlanetAssociation(db.Model):
    """Associates Planets with Stars, defining an author for the connection"""

    __tablename__ = 'planet_association'
    star_id = db.Column(db.String(32), db.ForeignKey('star.id'), primary_key=True)
    planet_id = db.Column(db.String(32), db.ForeignKey('planet.id'), primary_key=True)
    planet = db.relationship("Planet", backref="star_assocs")
    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))
    author = db.relationship("Persona", backref="planet_assocs")

    @classmethod
    def validate_changeset(cls, changeset):
        """Return True if `changeset` is a valid PlanetAssociation changeset"""

        if "author_id" not in changeset or changeset["author_id"] is None:
            app.logger.warning("Missing `author_id` in changeset")
            return False

        if "planet" not in changeset or changeset["planet"] is None or "kind" not in changeset["planet"]:
            app.logger.warning("Missing `planet` or `planet.kind` in changeset")
            return False

        p_cls = LinkPlanet if changeset["planet"]["kind"] == "link" else LinkedPicturePlanet
        return p_cls.validate_changeset(changeset)


t_planet_vesicles = db.Table(
    'planet_vesicles',
    db.Column('planet_id', db.String(32), db.ForeignKey('planet.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Planet(Serializable, db.Model):
    """A Planet represents an attachment"""

    __tablename__ = 'planet'

    _insert_required = ["id", "title", "created", "modified", "source", "kind"]
    _update_required = ["id", "title", "modified", "source"]

    id = db.Column(db.String(32), primary_key=True)
    title = db.Column(db.Text)
    kind = db.Column(db.String(32))
    created = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    source = db.Column(db.String(128))
    state = db.Column(db.Integer, default=0)

    vesicles = db.relationship(
        'Vesicle',
        secondary='planet_vesicles',
        primaryjoin='planet_vesicles.c.planet_id==planet.c.id',
        secondaryjoin='planet_vesicles.c.vesicle_id==vesicle.c.id')

    __mapper_args__ = {
        'polymorphic_identity': 'planet',
        'polymorphic_on': kind
    }

    def __repr__(self):
        return "<Planet:{} [{}]>".format(self.kind, self.id[:6])

    def get_state(self):
        """
        Return publishing state of this planet.

        Returns:
            Integer:
                -2 -- deleted
                -1 -- unavailable
                0 -- published
                1 -- draft
                2 -- private
                3 -- updating
        """
        return PLANET_STATES[self.state][0]

    def set_state(self, new_state):
        """
        Set the publishing state of this planet

        Parameters:
            new_state (int) code of the new state as defined in nucleus.PLANET_STATES

        Raises:
            ValueError: If new_state is not an Int or not a valid state of this object
        """
        new_state = int(new_state)
        if new_state not in PLANET_STATES.keys():
            raise ValueError("{} ({}) is not a valid planet state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    def export(self, update=False):
        return Serializable.export(self, update=update)

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        created_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        if stub is not None:
            if not isinstance(stub, Planet):
                raise ValueError("Invalid stub of type {}".format(type(stub)))

            new_planet = stub
            new_planet.id = changeset["id"]
            new_planet.title = changeset["title"]
            new_planet.source = changeset["source"]
            new_planet.created = created_dt
            new_planet.modified = modified_dt
        else:
            new_planet = Planet(
                id=changeset["id"],
                title=changeset["title"],
                created=created_dt,
                modified=modified_dt,
                source=changeset["source"]
            )

        app.logger.info("Created new {} from changeset".format(new_planet))
        return new_planet

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        self.title = changeset["title"]
        self.source = changeset["source"]
        self.modifed = modified_dt

        return self


class PicturePlanet(Planet):
    """A Picture attachment"""

    _insert_required = ["id", "title", "created", "modified", "source", "filename", "kind"]
    _update_required = ["id", "title", "modified", "source", "filename"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    filename = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'picture'
    }

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        stub = PicturePlanet()

        new_planet = Planet.create_from_changeset(changeset,
            stub=stub, update_sender=update_sender, update_recipient=update_recipient)

        new_planet.filename = changeset["filename"]

        return new_planet

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


class LinkedPicturePlanet(Planet):
    """A linked picture attachment"""

    _insert_required = ["id", "title", "created", "modified", "source", "url", "kind"]
    _update_required = ["id", "title", "modified", "source", "url"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    url = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'linkedpicture'
    }

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        if stub is None:
            stub = LinkedPicturePlanet()

        new_planet = Planet.create_from_changeset(changeset,
            stub=stub, update_sender=update_sender, update_recipient=update_recipient)

        new_planet.url = changeset["url"]

        return new_planet

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


class LinkPlanet(Planet):
    """A URL attachment"""

    _insert_required = ["id", "title", "kind", "created", "modified", "source", "url", "kind"]
    _update_required = ["id", "title", "modified", "source", "url"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    url = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'link'
    }

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        if stub is None:
            stub = LinkPlanet()

        new_planet = Planet.create_from_changeset(changeset,
            stub=stub, update_sender=update_sender, update_recipient=update_recipient)

        new_planet.url = changeset["url"]

        return new_planet

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


class Oneup(Star):
    """A 1up is a vote that signals interest in its parent Star"""

    _insert_required = ["id", "created", "modified", "author_id", "parent_id", "state"]
    _update_required = ["id", "modified", "state"]

    __mapper_args__ = {
        'polymorphic_identity': 'oneup'
    }

    def __repr__(self):
        if ["author_id", "parent_id"] in dir(self):
            return "<1up <Persona {}> -> <Star {}> ({})>".format(
                self.author_id[:6], self.parent_id[:6], self.get_state())
        else:
            return "<1up ({})>".format(self.get_state())

    def get_state(self):
        """
        Return publishing state of this 1up.

        Returns:
            Integer:
                -1 -- (disabled)
                 0 -- (active)
                 1 -- (unknown author)
        """
        return ONEUP_STATES[self.state][0]

    def set_state(self, new_state):
        """
        Set the publishing state of this 1up

        Parameters:
            new_state (int) code of the new state as defined in nucleus.ONEUP_STATES

        Raises:
            ValueError: If new_state is not an Int or not a valid state of this object
        """
        new_state = int(new_state)
        if new_state not in ONEUP_STATES.keys():
            raise ValueError("{} ({}) is not a valid 1up state".format(
                new_state, type(new_state)))
        else:
            self.state = new_state

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Oneup object from a changeset (See Serializable.create_from_changeset). """
        created_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        if stub is not None:
            oneup = stub
            oneup.created = created_dt
            oneup.modified = modified_dt
            oneup.author = None
            oneup.source = changeset["source"],
            oneup.parent_id = None
        else:
            oneup = Oneup(
                id=changeset["id"],
                created=created_dt,
                modified=modified_dt,
                author=None,
                parent=None,
            )

        oneup.set_state(int(changeset["state"]))

        author = Persona.query.get(changeset["author_id"])
        if author is None:
            # TODO: Send request for author
            oneup.author_id = changeset["author_id"]
            if oneup.get_state() >= 0:
                oneup.set_state(1)
        else:
            oneup.author = author

        star = Star.query.get(changeset["parent_id"])
        if star is None:
            app.logger.warning("Parent Star for Oneup not found")
            oneup.parent_id = changeset["parent_id"]
        else:
            star.children.append(oneup)

        return oneup

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a new Oneup object from a changeset (See Serializable.update_from_changeset). """
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified_dt

        self.set_state(changeset["state"])

        app.logger.info("Updated {} from changeset".format(self))


class Souma(Serializable, db.Model):
    """A physical machine in the Souma network"""

    __tablename__ = "souma"

    _insert_required = ["id", "modified", "crypt_public", "sign_public", "starmap_id"]
    id = db.Column(db.String(32), primary_key=True)

    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)

    starmap_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    starmap = db.relationship('Starmap')

    def __str__(self):
        return "<Souma [{}]>".format(self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Souma authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        return False

    def generate_keys(self):
        """ Generate new RSA keypairs for signing and encrypting. Commit to DB afterwards! """

        # TODO: Store keys encrypted
        rsa1 = RsaPrivateKey.Generate()
        self.sign_private = str(rsa1)
        self.sign_public = str(rsa1.public_key)

        rsa2 = RsaPrivateKey.Generate()
        self.crypt_private = str(rsa2)
        self.crypt_public = str(rsa2.public_key)

    def encrypt(self, data):
        """ Encrypt data using RSA """

        if self.crypt_public == "":
            raise ValueError("Error encrypting: No public encryption key found for {}".format(self))

        key_public = RsaPublicKey.Read(self.crypt_public)
        return key_public.Encrypt(data)

    def decrypt(self, cypher):
        """ Decrypt cyphertext using RSA """

        if self.crypt_private == "":
            raise ValueError("Error decrypting: No private encryption key found for {}".format(self))

        key_private = RsaPrivateKey.Read(self.crypt_private)
        return key_private.Decrypt(cypher)

    def sign(self, data):
        """ Sign data using RSA """
        from base64 import urlsafe_b64encode

        if self.sign_private == "":
            raise ValueError("Error signing: No private signing key found for {}".format(self))

        key_private = RsaPrivateKey.Read(self.sign_private)
        signature = key_private.Sign(data)
        return urlsafe_b64encode(signature)

    def verify(self, data, signature_b64):
        """ Verify a signature using RSA """
        from base64 import urlsafe_b64decode

        if self.sign_public == "":
            raise ValueError("Error verifying: No public signing key found for {}".format(self))

        signature = urlsafe_b64decode(signature_b64)
        key_public = RsaPublicKey.Read(self.sign_public)
        return key_public.Verify(data, signature)

t_starmap = db.Table(
    'starmap_index',
    db.Column('starmap_id', db.String(32), db.ForeignKey('starmap.id')),
    db.Column('star_id', db.String(32), db.ForeignKey('star.id'))
)

t_starmap_vesicles = db.Table(
    'starmap_vesicles',
    db.Column('starmap_id', db.String(32), db.ForeignKey('starmap.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Starmap(Serializable, db.Model):
    """
    Starmaps are collections of objects with associated layout information.

    Atributes:
        id: 32 byte ID generated by uuid4().hex
        modified: Datetime of last recorded modification
        author: Persona that created this Starmap
        kind: For what kind of context is this Starmap used
        index: List of Stars that are contained in this Starmap
        vesicles: List of Vesicles that describe this Starmap
    """
    __tablename__ = 'starmap'

    _insert_required = ["id", "modified", "author_id", "kind", "state"]
    _update_required = ["id", "modified", "index"]

    id = db.Column(db.String(32), primary_key=True)
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    kind = db.Column(db.String(16))
    state = db.Column(db.Integer, default=0)

    author_id = db.Column(
        db.String(32),
        db.ForeignKey('persona.id', use_alter=True, name="fk_author_id"))
    author = db.relationship('Persona',
        backref=db.backref('starmaps'),
        primaryjoin="Persona.id==Starmap.author_id",
        post_update=True)

    index = db.relationship(
        'Star',
        secondary='starmap_index',
        backref="starmaps",
        lazy="dynamic",
        primaryjoin='starmap_index.c.starmap_id==starmap.c.id',
        secondaryjoin='starmap_index.c.star_id==star.c.id')

    vesicles = db.relationship(
        'Vesicle',
        secondary='starmap_vesicles',
        primaryjoin='starmap_vesicles.c.starmap_id==starmap.c.id',
        secondaryjoin='starmap_vesicles.c.vesicle_id==vesicle.c.id')

    def __contains__(self, key):
        """Return True if the given key is contained in this Starmap.

        Args:
            key: db.model.key to look for
        """
        return (key in self.index)

    def __repr__(self):
        if self.kind == "persona_profile":
            name = "Persona-Profile"
        elif self.kind == "group_profile":
            name = "Group-Profile"
        else:
            name = "Starmap"

        return "<{} (by {}) [{}]>".format(name, self.author, self.id[:6])

    def __len__(self):
        return self.index.paginate(1).total

    def authorize(self, action, author_id=None):
        """Return True if this Starmap authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            if self.kind == "persona_profile":
                p = Persona.request_persona(self.author_id)
                return p.id == author_id
            elif self.kind == "group_profile":
                # Everyone can update
                if action == "update":
                    return True
                # Only author can insert and delete
                elif self.author_id == author_id:
                    return True

            elif self.kind == "index":
                p = Persona.query.filter(Persona.index_id == self.id)
                return p.id == author_id
        return False

    def get_state(self):
        """
        Return publishing state of this star.

        Returns:
            Integer:
                -2 -- deleted
                -1 -- unavailable
                0 -- published
                1 -- draft
                2 -- private
                3 -- updating
        """
        return STAR_STATES[self.state][0]

    def set_state(self, new_state):
        """
        Set the publishing state of this star

        Parameters:
            new_state (int) code of the new state as defined in nucleus.STAR_STATES

        Raises:
            ValueError: If new_state is not an Int or not a valid state of this object
        """
        new_state = int(new_state)
        if new_state not in STAR_STATES.keys():
            raise ValueError("{} ({}) is not a valid star state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    def get_absolute_url(self):
        """Return URL for this Starmap depending on kind"""
        if self.kind == "persona_profile":
            p = Persona.query.filter(Persona.profile_id == self.id).first()
            return url_for("persona", id=p.id)
        elif self.kind == "group_profile":
            g = Group.query.filter(Group.profile_id == self.id).first()
            return url_for("group", id=g.id)
        elif self.kind == "index":
            p = Persona.query.filter(Persona.index_id == self.id).first()
            return url_for("persona", id=p.id)

    def export(self, update=False):
        data = Serializable.export(self, exclude=["index", ], update=update)

        data["index"] = list()
        for star in self.index.filter('Star.state >= 0'):
            data["index"].append({
                "id": star.id,
                "modified": star.modified.isoformat(),
                "author_id": star.author.id
            })

        return data

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Starmap object from a changeset

        Args:
            changeset (dict): Contains all keys from self._insert_required

        Returns:
            Starmap: The new object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        author = Persona.query.get(changeset["author_id"])
        if author is None:
            raise PersonaNotFoundError("Starmap author not known")

        if stub is not None:
            new_starmap = stub
            new_starmap.modified = modified_dt
            new_starmap.author = author
            new_starmap.kind = changeset["kind"]
        else:
            new_starmap = Starmap(
                id=changeset["id"],
                modified=modified_dt,
                author=author,
                kind=changeset["kind"]
            )

        request_list = list()
        for star_changeset in changeset["index"]:
            star = Star.query.get(star_changeset["id"])
            star_changeset_modified = iso8601.parse_date(star_changeset["modified"]).replace(tzinfo=None)

            if star is None or star.get_state() == -1 or star.modified < star_changeset_modified:
                request_list.append({
                    "type": "Star",
                    "id": star_changeset["id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })

                if star is None:
                    star_author = Persona.query.get(star_changeset["author_id"])
                    if star_author is not None:
                        star = Star(
                            id=star_changeset["id"],
                            modified=star_changeset_modified,
                            author=star_author
                        )
                        star.set_state(-1)
                        db.session.add(star)
                        db.session.commit()

            new_starmap.index.append(star)

        db.session.add(new_starmap)
        db.session.commit()

        for req in request_list:
            request_objects.send(Starmap.create_from_changeset, message=req)

        return new_starmap

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update the Starmap's index using a changeset

        Args:
            changeset (dict): Contains a key for every attribute to update

        Raises:
            ValueError: If a value in the changeset is invalid
        """
        # Update modified
        modified = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified

        # Update index
        remove_stars = set([s.id for s in self.index if s is not None])
        added_stars = list()
        request_list = list()
        for star_changeset in changeset["index"]:
            star = Star.query.get(star_changeset["id"])
            star_changeset_modified = iso8601.parse_date(star_changeset["modified"]).replace(tzinfo=None)

            if star is not None and star.id in remove_stars:
                remove_stars.remove(star.id)

            if star is None or star.get_state() == -1 or star.modified < star_changeset_modified:
                # No copy of Star available or copy is outdated

                request_list.append({
                    "type": "Star",
                    "id": star_changeset["id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })

                if star is None:
                    star_author = Persona.query.get(star_changeset["author_id"])
                    if star_author is not None:
                        star = Star(
                            id=star_changeset["id"],
                            modified=star_changeset_modified,
                            author=star_author
                        )
                        star.set_state(-1)
                        db.session.add(star)
                        db.session.commit()

            self.index.append(star)
            added_stars.append(star)

        for s_id in remove_stars:
            s = Star.query.get(s_id)
            self.index.remove(s)

        app.logger.info("Updated {}: {} stars added, {} requested, {} removed".format(
            self, len(added_stars), len(request_list), len(remove_stars)))

        for req in request_list:
            request_objects.send(Starmap.create_from_changeset, message=req)

t_group_vesicles = db.Table(
    'group_vesicles',
    db.Column('group_id', db.String(32), db.ForeignKey('group.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Group(Identity):
    """Represents an entity that is comprised of users collaborating on stars

    Attributes:
        id (String): 32 byte ID of this group
        description (String): Text decription of what this group is about
        admin (Persona): Person that is allowed to make structural changes to the group_id

    """

    __tablename__ = "group"
    __mapper_args__ = {'polymorphic_identity': 'group'}

    _insert_required = Identity._insert_required + ["admin_id", "description", "profile_id", "state"]
    _update_required = Identity._update_required + ["state"]

    id = db.Column(db.String(32), db.ForeignKey('identity.id'), primary_key=True)
    description = db.Column(db.Text)

    state = db.Column(db.Integer, default=0)

    admin_id = db.Column(db.String(32), db.ForeignKey('persona.id'))
    admin = db.relationship("Persona", primaryjoin="persona.c.id==group.c.admin_id")

    profile_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    profile = db.relationship('Starmap', primaryjoin='starmap.c.id==group.c.profile_id')

    def __repr__(self):
        try:
            name = " {} ".format(self.username.encode('utf-8'))
        except AttributeError:
            name = ""
        return "<Group @{} [{}]>".format(name, self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Group authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            return self.admin_id == author_id
        return False

    def get_state(self):
        """
        Return publishing state of this Group. (temporarily uses planet states)

        Returns:
            Integer:
                -2 -- deleted
                -1 -- unavailable
                0 -- published
                1 -- draft
                2 -- private
                3 -- updating
        """
        return PLANET_STATES[self.state][0]

    def set_state(self, new_state):
        """
        Set the publishing state of this Group (temporarily uses planet states)

        Parameters:
            new_state (int) code of the new state as defined in nucleus.PLANET_STATES

        Raises:
            ValueError: If new_state is not an Int or not a valid state of this object
        """
        new_state = int(new_state)
        if new_state not in PLANET_STATES.keys():
            raise ValueError("{} ({}) is not a valid planet state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new group from changeset"""
        group = Identity.create_from_changeset(changeset,
            stub=stub, update_sender=update_sender, update_recipient=update_recipient)

        group.description = changeset["description"]
        group.set_state(changeset["state"])
        request_list = list()

        # Update admin
        admin = Persona.query.get(changeset["admin_id"])
        if admin is None or admin._stub:
            request_list.append({
                "type": "Persona",
                "id": changeset["admin_id"],
                "author_id": update_recipient.id if update_recipient else None,
                "recipient_id": update_sender.id if update_sender else None,
            })

        if admin is None:
            admin = Persona(
                id=changeset["admin_id"],
            )
            admin._stub = True

        group.admin = admin

        for req in request_list:
            request_objects.send(Group.create_from_changeset, message=req)

        return group

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update group. See Serializable.update_from_changeset"""
        Identity.update_from_changeset(self, changeset,
            update_sender=update_sender, update_recipient=update_recipient)

        app.logger.info("Now applying Group-specific updates for {}".format(self))

        request_list = list()

        self.set_state(changeset["state"])

        if "description" in changeset:
            self.description = changeset["description"]
            app.logger.info("Updated {}'s description".format(self))

        if "admin_id" in changeset:
            admin = Persona.query.get(changeset["admin_id"])
            if admin is None or admin._stub:
                request_list.append({
                    "type": "Persona",
                    "id": changeset["admin_id"],
                    "author_id": update_recipient.id if update_recipient else None,
                    "recipient_id": update_sender.id if update_sender else None,
                })

            if admin is None:
                admin = Persona(
                    id=changeset["admin_id"],
                )
                admin._stub = True

            self.admin = admin

        app.logger.info("Updated {} from changeset. Requesting {} objects.".format(self, len(request_list)))

        for req in request_list:
            request_objects.send(Group.update_from_changeset, message=req)
