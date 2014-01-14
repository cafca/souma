import datetime
import os

from base64 import b64encode, b64decode
from flask import url_for, session
from hashlib import sha256
from keyczar.keys import RsaPrivateKey, RsaPublicKey
from sqlalchemy import ForeignKey
from sqlalchemy.exc import OperationalError
from uuid import uuid4

from nucleus import ONEUP_STATES, STAR_STATES
from web_ui import app, db
from web_ui.helpers import epoch_seconds


class Serializable():
    """ Make SQLAlchemy models json serializable"""
    def export(self, exclude=[], include=None):
        """Return this object as a dict"""
        if include:
            return {
                field: str(getattr(self, field)) for field in include}
        else:
            return {
                c.name: str(getattr(self, c.name)) for c in self.__table__.columns if c not in exclude}

    def json(self, exclude=[], include=None):
        """Return this object JSON encoded"""
        import json
        return json.dumps(self.export(exclude=exclude, include=include), indent=4)


#
# Setup follower relationship on Persona objects
#

t_contacts = db.Table(
    'contacts',
    db.Column('left_id', db.String(32), db.ForeignKey('persona.id')),
    db.Column('right_id', db.String(32), db.ForeignKey('persona.id'))
)


class Persona(Serializable, db.Model):
    """A Persona represents a user profile"""

    __tablename__ = "persona"
    id = db.Column(db.String(32), primary_key=True)
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))
    contacts = db.relationship(
        'Persona',
        secondary='contacts',
        primaryjoin='contacts.c.left_id==persona.c.id',
        secondaryjoin='contacts.c.right_id==persona.c.id')
    crypt_private = db.Column(db.Text)
    crypt_public = db.Column(db.Text)
    sign_private = db.Column(db.Text)
    sign_public = db.Column(db.Text)
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())

    # TODO: Is this needed?
    souma_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    souma = db.relationship('Starmap', backref="personas", primaryjoin='starmap.c.id==persona.c.souma_id')

    # Myelin offset stores the date at which the last Vesicle receieved from Myelin was created
    myelin_offset = db.Column(db.DateTime)

    def __init__(self, id, username, email=None, sign_private=None, sign_public=None,
                 crypt_private=None, crypt_public=None):

        self.id = id
        self.username = username
        self.email = email
        self.sign_private = sign_private
        self.sign_public = sign_public
        self.crypt_private = crypt_private
        self.crypt_public = crypt_public

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

class Oneup(Serializable, db.Model):
    """A 1up is a vote that signals interest in a Star"""

    __tablename__ = "oneup"
    id = db.Column(db.String(32), primary_key=True, default=uuid4().hex)
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    state = db.Column(db.Integer, default=0)

    creator = db.relationship("Persona",
        backref=db.backref('oneups'),
        primaryjoin="Persona.id==Oneup.creator_id")
    creator_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    star_id = db.Column(db.String(32), db.ForeignKey('star.id'))

    def __repr__(self):
        return "<1up <Persona {}> -> <Star {}> ({})>".format(self.creator_id[:6], self.star_id[:6], self.get_state())

    def get_state(self):
        """
        Return publishing state of this star.

        Returns:
            One of:
                "disabled"
                "active"
                "unknown creator"
        """
        return ONEUP_STATES[self.state]

    def set_state(self, new_state):
        """
        Set the publishing state of this star

        Parameters:
            new_state (int) code of the new state as defined in nucleus.STAR_STATES
        """
        if not isinstance(new_state, int) or new_state not in ONEUP_STATES.keys():
            raise ValueError("{} ({}) is not a valid oneup state").format(
                new_state, type(new_state))
        else:
            self.state = new_state


class Star(Serializable, db.Model):
    """A Star represents a post"""

    __tablename__ = "star"
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
        backref=db.backref('starmap'),
        primaryjoin="satellites.c.star_id==star.c.id",
        secondaryjoin="satellites.c.planet_id==planet.c.id")

    creator = db.relationship('Persona',
        backref=db.backref('starmap'),
        primaryjoin="Persona.id==Star.creator_id")

    creator_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    def __init__(self, id, text, creator):
        self.id = id
        # TODO: Attach multiple items as 'planets'
        self.text = text

        if not isinstance(creator, Persona):
            self.creator_id = creator
        else:
            self.creator_id = creator.id

    def __repr__(self):
        ascii_text = self.text.encode('utf-8')
        return "<Star {}: {}>".format(
            self.creator_id[:6],
            (ascii_text[:24] if len(ascii_text) <= 24 else ascii_text[:22] + ".."))

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
        oneup = self.oneups.filter_by(creator=active_persona).first()
        if oneup is None or oneup.state < 0:
            return False
        else:
            return True

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
        oneup = self.oneups.filter_by(creator=author).first()
        if oneup is not None:
            old_state = oneup.get_state()
            oneup.set_state(-1) if oneup.state == 0 else oneup.set_state(0)
        else:
            old_state = False
            oneup = Oneup(star=self, creator=author)

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


class Planet(Serializable, db.Model):
    """A Planet represents an attachment"""

    __tablename__ = 'planet'
    id = db.Column(db.String(32), primary_key=True)
    title = db.Column(db.Text)
    kind = db.Column(db.String(32))
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    source = db.Column(db.String(128))

    __mapper_args__ = {
        'polymorphic_identity': 'planet',
        'polymorphic_on': kind
    }

    def __repr__(self):
        return "<Planet:{} [{}]>".format(self.kind, self.id[:6])


class PicturePlanet(Planet):
    """A Picture attachment"""

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    filename = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'picture'
    }


class LinkPlanet(Planet):
    """A URL attachment"""

    id = db.Column(db.String(32), ForeignKey('planet.id'), primary_key=True)
    url = db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity': 'link'
    }


class Souma(Serializable, db.Model):
    """A physical machine in the Souma network"""

    __tablename__ = "souma"
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

class DBVesicle(db.Model):
    """Store the representation of a Vesicle"""

    __tablename__ = "dbvesicle"
    id = db.Column(db.String(32), primary_key=True)
    json = db.Column(db.Text)
    created = db.Column(db.DateTime)
    author_id = db.Column(db.String(32))
    source_id = db.Column(db.String(32))
