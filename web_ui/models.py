import datetime
import os

from flask import url_for
from hashlib import sha256
from keyczar.keys import RsaPrivateKey, RsaPublicKey
from web_ui import db
from web_ui.helpers import Serializable, epoch_seconds
from sqlalchemy import ForeignKey
from sqlalchemy.exc import OperationalError

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
    soma_id = db.Column(db.String(32), db.ForeignKey('starmap.id'))
    soma = db.relationship('Starmap', backref="personas", primaryjoin='starmap.c.id==persona.c.soma_id')

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
        return key_public.Encrypt(data)

    def decrypt(self, cypher):
        """ Decrypt cyphertext using RSA """

        key_private = RsaPrivateKey.Read(self.crypt_private)
        return key_private.Decrypt(cypher)

    def sign(self, data):
        """ Sign data using RSA """
        from base64 import b64encode

        key_private = RsaPrivateKey.Read(self.sign_private)
        signature = key_private.Sign(data)
        return b64encode(signature)

    def verify(self, data, signature_b64):
        """ Verify a signature using RSA """
        from base64 import b64decode

        signature = b64decode(signature_b64)
        key_public = RsaPublicKey.Read(self.sign_public)
        return key_public.Verify(data, signature)


class Star(Serializable, db.Model):
    """A Star represents a post"""

    __tablename__ = "star"
    id = db.Column(db.String(32), primary_key=True)
    text = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    modified = db.Column(db.DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())

    planets = db.relationship(
        'Planet',
        secondary='satellites',
        backref=db.backref('starmap'),
        primaryjoin="satellites.c.star_id==star.c.id",
        secondaryjoin="satellites.c.planet_id==planet.c.id")

    creator = db.relationship(
        'Persona',
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


class Notification(db.Model):
    """Represents a stored notification to the user"""
    id = db.Column(db.String(32), primary_key=True)
    kind = db.Column(db.String(32))
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    to_persona_id = db.Column(db.String(32))

    def __init__(self, kind, to_persona_id):
        from uuid import uuid4
        self.id = uuid4().hex
        self.kind = kind
        self.to_persona_id = to_persona_id
