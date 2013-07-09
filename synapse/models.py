import datetime
import logging

from flask import json
from web_ui import app, db
from nucleus.models import Persona, Star


class Message(object):
    """ Container for peer messages """

    def __init__(self, message_type, data, reply_to=app.config['SYNAPSE_PORT']):
        self.message_type = message_type
        self.data = data
        self.timestamp = None
        self.send_attributes = ["message_type", "data", "reply_to"]
        self.verified = False
        self.reply_to = reply_to

    def __str__(self):
        if hasattr(self, "author_id"):
            author = Persona.query.get(self.author_id)
            if author:
                signed = "signed {username}<{id}>".format(
                    username=author.username, id=self.author_id)
            else:
                signed = "signed Anonymous<{id}>".format(id=self.author_id)
        else:
            signed = "unsigned"
        return "Message ({signed})".format(signed=signed)

    def json(self):
        """Return JSON representation"""
        message = dict()
        for attr in self.send_attributes:
            message[attr] = getattr(self, attr)
        message["timestamp"] = datetime.datetime.now().isoformat()
        return json.dumps(message)

    @staticmethod
    def read(data):
        """Create a Message instance from its JSON representation"""

        logger = logging.getLogger('synapse')

        # TODO Catch errors
        msg = json.loads(data)
        message = Message(message_type=msg["message_type"], data=msg["data"], reply_to=msg["reply_to"])

        if "signature" in msg:
            message.signature = msg["signature"]
            message.author_id = msg["author_id"]

            # Verify signature
            p = Persona.query.get(message.author_id)
            if p is None:
                # TODO: Try to retrieve author persona from network
                logger.warning("[{msg}] Could not verify signature. Author pubkey missing.".format(msg=message))
            else:
                is_valid = p.verify(message.data, message.signature)
                if is_valid:
                    message.verified = True
                if not is_valid:
                    logger.error("[{msg}] Signature invalid!".format(msg=message))
                    raise ValueError("Invalid signature")

            # data field needs to be decoded if the message is signed
            message.data = json.loads(message.data)
        return message

    def sign(self, author):
        """Sign a message using an author persona. Make sure not to change message data after signing"""

        if not isinstance(self.data, str):
            self.data = json.dumps(self.data)
        self.signature = author.sign(self.data)
        self.author_id = author.id
        self.send_attributes.extend(["signature", "author_id"])

t_starmap_index = db.Table(
    'starmap_index',
    db.Column('starmap_id', db.String(32), db.ForeignKey('starmap.id')),
    db.Column('orb_id', db.String(32), db.ForeignKey('orb.id'))
)


class Starmap(db.Model):
    __tablename__ = 'starmap'
    id = db.Column(db.String(32), primary_key=True)
    index = db.relationship(
        'Orb',
        secondary='starmap_index',
        primaryjoin='starmap_index.c.starmap_id==starmap.c.id',
        secondaryjoin='starmap_index.c.orb_id==orb.c.id')

    def __init__(self, id):
        self.id = id

    def __contains__(self, key):
        return (key in self.index)

    def __repr__(self):
        return "<Starmap {}>".format(self.id)

    def add(self, orb):
        """Add Orb to this starmap"""
        if orb in self.index:
            raise KeyError("{} is already part of {}.".format(orb, self))
        return self.index.append(orb)


class Orb(db.Model):
    """Stub for any object that might exist in a starmap"""

    __tablename__ = 'orb'
    id = db.Column(db.String(32), primary_key=True)
    type = db.Column(db.String(32))
    modified = db.Column(db.DateTime)
    creator = db.Column(db.String(32))

    def __init__(self, object_type, id, modified, creator=None):
        self.id = id
        self.type = object_type
        self.modified = modified
        self.creator = creator

    def __repr__(self):
        return "<Orb:{} {}>".format(self.type, self.id[:6])
