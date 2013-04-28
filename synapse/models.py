import datetime
import logging

from flask import json
from soma.web_ui.models import Persona


class Message(object):
    """ Container for peer messages """

    def __init__(self, message_type, data):
        self.message_type = message_type
        self.data = data
        self.timestamp = None
        self.send_attributes = ["message_type", "data"]
        self.verified = False

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
        message = Message(message_type=msg["message_type"], data=msg["data"])

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
