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
    PersonaNotFoundError, UnauthorizedError, notification_signals
from web_ui import app, db
from web_ui.helpers import epoch_seconds

request_objects = notification_signals.signal('request-objects')


class Serializable():
    """ Make SQLAlchemy models json serializable

    Attributes:
        _export_include: Default attributes to include in export
        _update_include: Default attributes to include in export with update=True
    """

    _export_include = []
    _update_include = []

    def export(self, update=False, exclude=[], include=None):
        """Return this object as a dict.

        Precedence is on the `include` parameter.

        Args:
            update (Bool): Export only attributes defined in `self._update_include`
            exclude (List): Export only those attributes from `self._export_include`
                (or `self._update_include` if update=True) that are not in `exclude`
            include (List): Export only those attributes from `self._export_include`
                (or `self._update_include` if update=True) that are in `include`

        Returns:
            Dict: The serialized object

        Raises:
            KeyError: If a key was not found
        """
        attr_names = self._update_include if update is True else self._export_include

        if include:
            return {
                attr: str(getattr(self, attr)) for attr in attr_names if attr in include}
        else:
            return {
                attr: str(getattr(self, attr)) for attr in attr_names if attr not in exclude}

    def json(self, update=False, exclude=[], include=None):
        """Return this object JSON encoded."""
        return json.dumps(self.export(update=update, exclude=exclude, include=include), indent=4)

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
        _export_include: Attributes that are serialized
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

    _export_include = ["id", "username", "email", "crypt_public",
        "sign_public", "modified", "profile_id", "index_id"]
    _update_include = ["username", "email", "profile_id", "index_id"]

    _stub = db.Column(db.Boolean, default=False)
    id = db.Column(db.String(32), primary_key=True)
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))
    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())

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

    # Myelin offset stores the date at which the last Vesicle receieved from Myelin was created
    myelin_offset = db.Column(db.DateTime)

    def __repr__(self):
        return "<{} [{}]>".format(str(self.username), self.id[:6])

    def controlled(self):
        """
        Return True if this Persona has private keys attached
        """
        if self.crypt_private is not None and self.sign_private is not None:
            return True
        else:
            return False

    def get_email_hash(self):
        """Return sha256 hash of this user's email address"""
        return sha256(self.email).hexdigest()

    def get_absolute_url(self):
        return url_for('persona', id=self.id)

    def export(self, exclude=[], include=[]):
        data = Serializable.export(self, exclude=exclude, include=include)

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

    def update_from_changeset(self, changeset):
        """Update this Persona profile using a changeset

        Args:
            changeset (dict): Dictionary containing keys from self._update_include

        Returns:
            Persona: The updated Persona

        Raises:
            ValueError: One of the update values is invalid
            NotImplementedError: If trying to update a value not in self._update_include
        """
        for k in changeset.keys():
            if k not in self._update_include:
                app.logger.warning("Updating '{}' is not implemented".format(k))
                del changeset[k]

        if "username" in changeset:
            self.username = changeset["username"]

        if "email" in changeset:
            self.email = changeset["email"]

        if "profile_id" in changeset:
            profile = Starmap.query.get(changeset["profile_id"])
            if profile is None or profile.get_state() == -1:
                request_objects.send(self.update_from_changeset, message={
                    "type": "Starmap",
                    "id": changeset["profile_id"]
                })
            else:
                self.profile = profile

        if "index_id" in changeset:
            index = Starmap.query.get(changeset["index_id"])
            if index is None or index.get_state() == -1:
                request_objects.send(self.update_from_changeset, message={
                    "type": "Starmap",
                    "id": changeset["index_id"]
                })
            else:
                self.index = index

        app.logger.info("Updated {}'s {}".format(self.username, ", ".join(changeset)))


class Oneup(Serializable, db.Model):
    """A 1up is a vote that signals interest in a Star"""

    __tablename__ = "oneup"
    id = db.Column(db.String(32), primary_key=True, default=uuid4().hex)
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
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
            One of:
                "disabled"
                "active"
                "unknown author"
        """
        return ONEUP_STATES[self.state]

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

    _export_include = ["id", "text", "created", "modified", "author_id"]
    _update_include = ["text", "modified"]

    id = db.Column(db.String(32), primary_key=True)
    text = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    state = db.Column(db.Integer, default=0)

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

    author = db.relationship('Persona',
        backref=db.backref('starmap'),
        primaryjoin="Persona.id==Star.author_id")

    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    def __init__(self, id, text, author, created, modified):
        self.id = id
        self.text = text
        self.created = created
        self.modifed = modified

        if not isinstance(author, Persona):
            self.author_id = author
        else:
            self.author_id = author.id

    def __repr__(self):
        ascii_text = self.text.encode('utf-8')
        return "<Star {}: {}>".format(
            self.author_id[:6],
            (ascii_text[:24] if len(ascii_text) <= 24 else ascii_text[:22] + ".."))

    @staticmethod
    def create_from_changeset(changeset):
        """Create a new Star object from a changeset.

        Args:
            changeset (dict): Contains a key for every value in Star._export_include

        Returns:
            Star: The new Star object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        for k in (Star._export_include):
            if k not in changeset.keys():
                raise KeyError("Missing value '{}' in changeset".format(k))

        created_dt = iso8601.parse_date(changeset["modified"])
        modified_dt = iso8601.parse_date(changeset["modified"])

        star = Star(
            id=changeset["id"],
            text=changeset["text"],
            author=None,
            created=created_dt,
            modified=modified_dt,
        )

        author = Persona.query.get(changeset["author_id"])
        if author is None:
            star.author_id = changeset["author_id"]
        else:
            star.author = author

        return star

    def export(self, exclude=[], include=[]):
        data = Serializable.export(self, exclude=exclude, include=include)

        for planet in self.planets:
            data["planets"].append(planet.export())

        return data

    def get_state(self):
        """
        Return publishing state of this star.

        Returns:
            One of:
                (-2, "deleted")
                (-1, "unavailable")
                (0, "published")
                (1, "draft")
                (2, "private")
                (3, "updating")
        """
        return STAR_STATES[self.state]

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

    _export_include = ["id", "title", "created", "modified", "source"]
    _update_include = ["title", "modified", "source"]

    id = db.Column(db.String(32), primary_key=True)
    title = db.Column(db.Text)
    kind = db.Column(db.String(32))
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
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
            One of:
                (-2, "deleted")
                (-1, "unavailable")
                (0, "published")
                (1, "draft")
                (2, "private")
                (3, "updating")
        """
        return PLANET_STATES[self.state]

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

    def export(self, exclude=[], include=[]):
        return Serializable.export(self, exclude=exclude, include=include)

    @staticmethod
    def create_from_changeset(changeset):
        """Create a new Planet object from a changeset.

        Args:
            changeset (dict): Contains a key for every value in Planet._export_include

        Returns:
            Planet: The new Planet object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        raise NotImplementedError

    def update_from_changeset(changeset):
        raise NotImplementedError


class PicturePlanet(Planet):
    """A Picture attachment"""

    _export_include = ["id", "title", "created", "modified", "source", "filename"]
    _update_include = ["title", "modified", "source", "filename"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    filename = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'picture'
    }

    @staticmethod
    def create_from_changeset(changeset):
        """Create a new PicturePlanet object from a changeset.

        Args:
            changeset (dict): Contains a key for every value in PicturePlanet._export_include

        Returns:
            PicturePlanet: The new PicturePlanet object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        for k in (PicturePlanet._export_include):
            if k not in changeset.keys():
                raise KeyError("Missing value '{}' in changeset".format(k))

        created_dt = iso8601.parse_date(changeset["modified"])
        modified_dt = iso8601.parse_date(changeset["modified"])

        pplanet = PicturePlanet(
            id=changeset["id"],
            title=changeset["title"],
            created=created_dt,
            modified=modified_dt,
            source=changeset["source"],
            filename=changeset["filename"]
        )

        return pplanet


class LinkPlanet(Planet):
    """A URL attachment"""

    _export_include = ["id", "title", "kind", "created", "modified", "source", "url"]
    _update_include = ["title", "modified", "source", "url"]

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    url = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'link'
    }

    @staticmethod
    def create_from_changeset(changeset):
        """Create a new LinkPlanet object from a changeset.

        Args:
            changeset (dict): Contains a key for every value in LinkPlanet._export_include

        Returns:
            LinkPlanet: The new LinkPlanet object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        for k in (LinkPlanet._export_include):
            if k not in changeset.keys():
                raise KeyError("Missing value '{}' in changeset".format(k))

        created_dt = iso8601.parse_date(changeset["modified"])
        modified_dt = iso8601.parse_date(changeset["modified"])

        lplanet = LinkPlanet(
            id=changeset["id"],
            title=changeset["title"],
            created=created_dt,
            modified=modified_dt,
            source=changeset["source"],
            url=changeset["url"]
        )

        return lplanet


class Souma(Serializable, db.Model):
    """A physical machine in the Souma network"""

    __tablename__ = "souma"

    _export_include = ["id", "crypt_public", "sign_public", "starmap_id"]
    id = db.Column(db.String(32), primary_key=True)

    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)

    starmap_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    starmap = db.relationship('Starmap')

    def __str__(self):
        return "<Souma [{}]>".format(self.id[:6])

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

t_planet_vesicles = db.Table(
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

    _export_include = ["id", "modified", "author_id", "kind"]
    _update_include = ["modified"]

    id = db.Column(db.String(32), primary_key=True)
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    kind = db.Column(db.String(16))

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
        return "<Starmap {} by {}>".format(self.id[:6], self.author)

    def __len__(self):
        return self.index.paginate(1).total

    def export(self, update=False, exclude=[], include=[]):
        data = Serializable.export(self, exclude=exclude, include=include)

        for star in self.index.filter('Star.state > 0'):
            data["index"].append(star.export())

        return data

    @staticmethod
    def create_from_changeset(changeset):
        """Create a new Starmap object from a changeset

        Args:
            changeset (dict): Contains all keys from self._export_include

        Returns:
            Starmap: The new object

        Raises:
            ValueError: If a value is invalid
            KeyError: If a required Value is missing
        """
        for k in (Starmap._export_include + "index"):
            if k not in changeset.keys():
                raise KeyError("Missing value '{}' in changeset".format(k))

        modified_dt = iso8601.parse_date(changeset["modified"])

        author = Persona.query.get(changeset["author_id"])
        if author is None:
            raise PersonaNotFoundError("Starmap author not known")

        new_starmap = Starmap(
            id=changeset["id"],
            modified=modified_dt,
            author=author,
            kind=changeset["kind"]
        )

        request_objects = list()
        for star_changeset in changeset["index"]:
            star = Star.query.get(star_changeset["id"])

            if star is None:
                star = Star.create_from_changeset(star_changeset)
                db.session.add(star)
                db.session.commit()

            elif star.get_state() == -1 or star.modified < star_changeset["modified"]:
                request_objects.append({
                    "type": "Star",
                    "id": star_changeset["id"]
                })

            new_starmap.index.append(star)

            if len(star_changeset["planets"]) > 0:
                for planet_changeset in star_changeset["planets"]:
                    planet = Planet.query.get(planet_changeset["id"])

                    if planet is None:
                        planet = Planet.create_from_changeset(planet_changeset)

                        db.session.add(planet)
                        db.session.commit()

                    elif planet.get_state() == -1 or planet.modified < planet_changeset["modified"]:
                        request_objects.append({
                            "type": "Planet",
                            "id": planet_changeset["id"]
                        })

                    star.planets.append(planet)
                db.session.add(star)
                db.session.commit()

        db.session.add(new_starmap)
        db.session.commit()

        request_objects.send(Starmap.create_from_changeset, request_objects)

    def update_from_changeset(self, changeset):
        """Update the Starmap's index using a changeset

        Args:
            changeset (dict): Contains a key for every attribute to update

        Raises:
            ValueError: If a value in the changeset is invalid
        """
        raise NotImplementedError("Updating Starmap not implemented")
