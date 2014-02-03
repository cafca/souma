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

#
# Setup follower relationship on Persona objects
#

t_contacts = db.Table(
    'contacts',
    db.Column('left_id', db.String(32), db.ForeignKey('persona.id')),
    db.Column('right_id', db.String(32), db.ForeignKey('persona.id'))
)

t_persona_vesicles = db.Table(
    'persona_vesicles',
    db.Column('persona_id', db.String(32), db.ForeignKey('persona.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Persona(Serializable, db.Model):
    """A Persona represents a user profile

    Attributes:
        _insert_required: Attributes that are serialized
        id: 32 byte ID generated by uuid4().hex
        username: Public username of the Persona, max 80 bytes
        email: An email address, max 120 bytes
        crypt_private: Private encryption RSA key, JSON encoded KeyCzar export
        crypt_public: Public encryption RSA key, JSON encoded KeyCzar export
        sign_private: Private signing RSA key, JSON encoded KeyCzar export
        sign_public: Public signing RSA key, JSON encoded KeyCzar export
        modified: Last time this Persona object was modified, defaults to now
        contacts: List of this Persona's contacts
        vesicles: List of Vesicles that describe this Persona object
        profile: Starmap containing this Persona's profile page
        index: Starmap containing all Star's this Persona publishes to its contacts
        myelin_offset: Datetime of last request for Vesicles sent to this Persona

    """

    __tablename__ = "persona"

    _insert_required = ["id", "username", "email", "crypt_public",
        "sign_public", "modified", "profile_id", "index_id", "contacts"]
    _update_required = ["id", "username", "email", "profile_id", "index_id", "modified", "contacts"]

    _stub = db.Column(db.Boolean, default=False)
    id = db.Column(db.String(32), primary_key=True)
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))
    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())

    contacts = db.relationship(
        'Persona',
        secondary='contacts',
        lazy="dynamic",
        primaryjoin='contacts.c.left_id==persona.c.id',
        secondaryjoin='contacts.c.right_id==persona.c.id')

    vesicles = db.relationship(
        'Vesicle',
        secondary='persona_vesicles',
        primaryjoin='persona_vesicles.c.persona_id==persona.c.id',
        secondaryjoin='persona_vesicles.c.vesicle_id==vesicle.c.id')

    profile_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    profile = db.relationship('Starmap', primaryjoin='starmap.c.id==persona.c.profile_id')

    index_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    index = db.relationship('Starmap', primaryjoin='starmap.c.id==persona.c.index_id')

    # Group membership

    # groups = db.relationship(
    # 'Group',
    # secondary='groups',
    # primaryjoin='groups.c.left_id==persona.c.id',
    # secondaryjoin='groups.c.right_id==group.c.id')

    # Myelin offset stores the date at which the last Vesicle receieved from Myelin was created
    myelin_offset = db.Column(db.DateTime)

    def __repr__(self):
        return "<{} [{}]>".format(str(self.username), self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Persona authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            return (self.id == author_id)
        return False

    def controlled(self):
        """
        Return True if this Persona has private keys attached
        """
        if self.crypt_private is not None and self.sign_private is not None:
            return True
        else:
            return False

    @staticmethod
    def list_controlled():
        return Persona.query.filter('Persona.sign_private != ""')

    def get_email_hash(self):
        """Return sha256 hash of this user's email address"""
        return sha256(self.email).hexdigest()

    def get_absolute_url(self):
        return url_for('persona', id=self.id)

    def export(self, update=False):
        data = Serializable.export(self, exclude=["contacts", ], update=update)

        data["contacts"] = list()
        for contact in self.contacts:
            data["contacts"].append({
                "id": contact.id,
            })

        return data

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
            p = stub
            p.id = changeset["id"]
            p.username = changeset["username"]
            p.email = changeset["email"]
            p.crypt_public = changeset["crypt_public"]
            p.sign_public = changeset["sign_public"]
            p.modified = modified_dt
        else:
            p = Persona(
                id=changeset["id"],
                username=changeset["username"],
                email=changeset["email"],
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

        p.profile = profile

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
        for contact in changeset["contacts"]:
            c = Persona.query.get(contact["id"])

            if c is None:
                c = Persona(id=contact["id"], _stub=True)
                request_list.append({
                    "type": "Persona",
                    "id": contact["id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })

            p.contacts.append(c)

        app.logger.info("Created {} from changeset, now requesting {} linked objects".format(
            p, len(request_list)))

        for req in request_list:
            request_objects.send(Persona.create_from_changeset, message=req)

        return p

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """See Serializable.update_from_changeset"""
        request_list = list()

        # Update modified
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified_dt

        # Update username
        self.username = changeset["username"]
        app.logger.info("Updated {}'s {}".format(self.username, "username"))

        # Update email
        self.email = changeset["email"]
        app.logger.info("Updated {}'s {}".format(self.username, "email"))

        # Update contacts
        updated_contacts = list()
        requested_contacts = list()

        # remove_contacts contains all old contacts at first, all current
        # contacts get then removed so that the remaining can get deleted
        remove_contacts = set(self.contacts)

        for contact in changeset["contacts"]:
            c = Persona.query.get(contact["id"])

            if c is None:
                c = Persona(id=contact["id"], _stub=True)
                request_list.append({
                    "type": "Persona",
                    "id": contact["id"],
                    "author_id": update_recipient.id,
                    "recipient_id": update_sender.id,
                })
                requested_contacts.append(c)
            else:
                updated_contacts.append(c)

                try:
                    remove_contacts.remove(c)
                except KeyError:
                    pass

            self.contacts.append(c)

        for contact in remove_contacts:
            self.contacts.remove(contact)

        app.logger.info("Updated {}'s contacts: {} added, {} removed, {} requested".format(
            self.username, len(updated_contacts), len(remove_contacts), len(requested_contacts)))

        # Update profile
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

        # Update index
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

        app.logger.info("Updated {} from changeset. Requesting {} objects.".format(self, len(request_list)))

        for req in request_list:
            request_objects.send(Persona.create_from_changeset, message=req)


class Oneup(Serializable, db.Model):
    """A 1up is a vote that signals interest in a Star"""

    __tablename__ = "oneup"
    id = db.Column(db.String(32), primary_key=True)
    created = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    state = db.Column(db.Integer, default=0)

    author = db.relationship("Persona",
        backref=db.backref('oneups'),
        primaryjoin="Persona.id==Oneup.author_id")
    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    star_id = db.Column(db.String(32), db.ForeignKey('star.id'))

    def __repr__(self):
        return "<1up <Persona {}> -> <Star {}> ({})>".format(self.author_id[:6], self.star_id[:6], self.get_state())

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
        """
        if not isinstance(new_state, int) or new_state not in ONEUP_STATES.keys():
            raise ValueError("{} ({}) is not a valid 1up state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

t_star_vesicles = db.Table(
    'star_vesicles',
    db.Column('star_id', db.String(32), db.ForeignKey('star.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Star(Serializable, db.Model):
    """A Star represents a post"""

    __tablename__ = "star"

    _insert_required = ["id", "text", "created", "modified", "author_id", "planets"]
    _update_required = ["id", "text", "modified"]

    id = db.Column(db.String(32), primary_key=True)
    text = db.Column(db.Text)

    created = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())

    state = db.Column(db.Integer, default=0)

    author = db.relationship('Persona',
        backref=db.backref('starmap'),
        primaryjoin="Persona.id==Star.author_id")
    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    oneups = db.relationship('Oneup',
        backref='star',
        lazy='dynamic')

    planets = db.relationship('Planet',
        secondary='satellites',
        backref=db.backref('stars'),
        primaryjoin="satellites.c.star_id==star.c.id",
        secondaryjoin="satellites.c.planet_id==planet.c.id")

    vesicles = db.relationship(
        'Vesicle',
        secondary='star_vesicles',
        primaryjoin='star_vesicles.c.star_id==star.c.id',
        secondaryjoin='star_vesicles.c.vesicle_id==vesicle.c.id')

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

        return star

    def update_from_changeset(self, changeset, update_sender=None, update_recipient=None):
        """Update a Star from a changeset (See Serializable.update_from_changeset)"""
        # Update modified
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)
        self.modified = modified_dt

        # Update text
        self.text = changeset["text"]

        app.logger.info("Updated {} from changeset".format(self))

    def export(self, update=False):
        """See Serializable.export"""

        data = Serializable.export(self, exclude=["planets", ], update=update)

        data["planets"] = list()
        for planet in self.planets:
            data["planets"].append(planet.export())

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
        """
        if not isinstance(new_state, int) or new_state not in STAR_STATES.keys():
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

    def oneupped(self):
        """
        Return True if active Persona has 1upped this Star
        """
        active_persona = Persona.query.get(session["active_persona"])
        oneup = self.oneups.filter_by(author=active_persona).first()
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
        return self.oneups.filter_by(state=0).paginate(1).total

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
            author = Persona.query.get(session['active_persona'])
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
            oneup = Oneup(id=uuid4().hex, star=self, author=author)

        # Commit 1up
        db.session.add(oneup)
        db.session.commit()
        app.logger.info("{verb} {obj}".format(verb="Toggled" if old_state else "Added", obj=oneup, ))

        return oneup


t_satellites = db.Table(
    'satellites',
    db.Column('star_id', db.String(32), db.ForeignKey('star.id')),
    db.Column('planet_id', db.String(32), db.ForeignKey('planet.id'))
)

t_planet_vesicles = db.Table(
    'planet_vesicles',
    db.Column('planet_id', db.String(32), db.ForeignKey('planet.id')),
    db.Column('vesicle_id', db.String(32), db.ForeignKey('vesicle.id'))
)


class Planet(Serializable, db.Model):
    """A Planet represents an attachment"""

    __tablename__ = 'planet'

    _insert_required = ["id", "title", "created", "modified", "source"]
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
        """
        if not isinstance(new_state, int) or new_state not in PLANET_STATES.keys():
            raise ValueError("{} ({}) is not a valid planet state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    def export(self, update=False):
        return Serializable.export(self, update=update)

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        raise NotImplementedError

    def update_from_changeset(changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


class PicturePlanet(Planet):
    """A Picture attachment"""

    _insert_required = ["id", "title", "created", "modified", "source", "filename"]
    _update_required = ["id", "title", "modified", "source", "filename"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    filename = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'picture'
    }

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        raise NotImplementedError

    def update_from_changeset(changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


class LinkPlanet(Planet):
    """A URL attachment"""

    _insert_required = ["id", "title", "kind", "created", "modified", "source", "url"]
    _update_required = ["id", "title", "modified", "source", "url"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    url = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'link'
    }

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new Planet object from a changeset (See Serializable.create_from_changeset). """
        raise NotImplementedError

    def update_from_changeset(changeset, update_sender=None, update_recipient=None):
        """Update a new Planet object from a changeset (See Serializable.update_from_changeset). """
        raise NotImplementedError


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
                p = Persona.query.filter(Persona.profile_id == self.id)
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
        """
        if not isinstance(new_state, int) or new_state not in STAR_STATES.keys():
            raise ValueError("{} ({}) is not a valid star state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    def get_absolute_url(self):
        """Return URL for this Starmap depending on kind"""
        # import pdb; pdb.set_trace()
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


class Group(Serializable, db.Model):
    """
        Represents an entity that is comprised of users collaborating on
        stars
    """

    __tablename__ = "group"
    _insert_required = ["id", "modified", "author_id", "groupname", "description", "profile_id", "state"]
    _update_required = ["id", "modified", "state"]

    id = db.Column(db.String(32), primary_key=True)
    modified = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    groupname = db.Column(db.String(80))
    description = db.Column(db.Text)

    state = db.Column(db.Integer, default=0)

    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))
    author = db.relationship("Persona", primaryjoin="persona.c.id==group.c.author_id")

    profile_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    profile = db.relationship('Starmap', primaryjoin='starmap.c.id==group.c.profile_id')

    vesicles = db.relationship(
        'Vesicle',
        secondary='group_vesicles',
        primaryjoin='group_vesicles.c.group_id==group.c.id',
        secondaryjoin='group_vesicles.c.vesicle_id==vesicle.c.id')

    # Make this work if needed!
    """
    members = db.relationship(
        "Persona",
        backref="groups",
        primaryjoin='group.c.id==persona.c.?????_id' # TODO:How to HBTM?!
    )"""

    def __repr__(self):
        try:
            name = " {} ".format(self.groupname.encode('utf-8'))
        except AttributeError:
            name = ""
        return "<Group{}[{}]>".format(name, self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Group authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.CHANGE_TYPES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Serializable.authorize(self, action, author_id=author_id):
            return self.author_id == author_id
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
        """
        if not isinstance(new_state, int) or new_state not in PLANET_STATES.keys():
            raise ValueError("{} ({}) is not a valid planet state").format(
                new_state, type(new_state))
        else:
            self.state = new_state

    @staticmethod
    def create_from_changeset(changeset, stub=None, update_sender=None, update_recipient=None):
        """Create a new group from changeset"""
        modified_dt = iso8601.parse_date(changeset["modified"]).replace(tzinfo=None)

        if stub is not None:
            group = stub
            group.id = changeset["id"]
            group.author = None
            group.profile = None
            group.modified = modified_dt
            group.groupname = changeset["groupname"]
            group.description = changeset["description"]
        else:
            group = Group(
                id=changeset["id"],
                modified=modified_dt,
                author=None,
                profile=None,
                groupname=changeset["groupname"],
                description=changeset["description"]
            )

        group.set_state(int(changeset["state"]))
        request_list = list()

        # Update profile
        profile = Starmap.query.get(changeset["profile_id"])
        if profile is None or profile.get_state() == -1:
            request_list.append({
                "type": "Starmap",
                "id": changeset["profile_id"],
                "author_id": update_recipient.id if update_recipient else None,
                "recipient_id": update_sender.id if update_sender else None,
            })

        if profile is None:
            profile = Starmap(
                id=changeset["profile_id"],
                kind="group_profile"
            )
            profile.state = -1

        group.profile = profile

        # Update author
        author = Persona.query.get(changeset["author_id"])
        if author is None or author._stub:
            request_list.append({
                "type": "Persona",
                "id": changeset["author_id"],
                "author_id": update_recipient.id if update_recipient else None,
                "recipient_id": update_sender.id if update_sender else None,
            })

        if author is None:
            author = Persona(
                id=changeset["author_id"],
            )
            author._stub = True

        group.author = author
        return group
