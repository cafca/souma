import json
import datetime
import logging

from hashlib import sha256
from keyczar.keys import AesKey

from web_ui import app

VESICLE_VERSION = "0.1"
DEFAULT_ENCODING = VESICLE_VERSION + "-plain"
SYNAPSE_PORT = None
AES_BYTES = 256


class Vesicle(object):
    """
    Container for peer messages

    see https://github.com/ciex/glia/wiki/Vesicle

    """

    def __init__(self, message_type, data=None, payload=None, signature=None, created=None, keycrypt=None, enc=DEFAULT_ENCODING, reply_to=SYNAPSE_PORT, soma_id=app.config["SOMA_ID"]):

        self._hashcode = None
        self.created = created
        self.data = data
        self.enc = enc
        self.keycrypt = keycrypt
        self.message_type = message_type
        self.payload = payload
        self.reply_to = reply_to
        self.send_attributes = ("message_type", "payload", "reply_to", "enc", "soma_id")
        self.signature = signature
        self.soma_id = soma_id

    def __str__(self):
        """
        Return string identifier
        """
        from nucleus.models import Persona

        if hasattr(self, "author_id"):
            p = Persona.query.get(self.author_id)
            if p:
                author = p.username
            else:
                author = self.author_id[:6]
        else:
            author = "anon"
        return "<vesicle {type}@{author}>".format(type=self.message_type, author=author)

    def encrypt(self, author, recipients):
        """
        Encrypt the vesicle's data field into the payload field and set the data field to None

        @param author The persona whose encrypting key is used
        @param recipients A list of recipient personas who will be added to the keycrypt
        """

        # Validate state
        if self.data == "" or self.data is None:
            raise ValueError("Cannot encrypt empty vesicle {} (empty data field)".format(self))

        # Generate a string representation of the message data
        data = json.encode(self.data)

        # Compute its SHA256 hash code
        self._hashcode = sha256(data)

        # Generate an AES key with key=h
        key = AesKey(self._hashcode, author.hmac_key, AES_BYTES)

        # Encrypt data using the AES key
        payload = key.encrypt(data)

        self.payload = payload
        self.data = None
        self.author_id = author.id
        self.enc = self.enc.split("-")[0] + "-AES" + AES_BYTES
        self.send_attributes.union({"author_id", "keycrypt"})

        for r in recipients:
            self.add_recipient(r)

    def encrypted(self):
        return self.payload is not None and self.enc.split("-")[1] != "plain"

    def decrypt(self, reader_persona):
        """
        Decrypt the vesicle's payload field into the data field.

        This method does not remove the ciphertext from the payload field, so that encrypted() still returns True.

        @param reader_persona Persona instance used to retrieve the hash key
        """

        # Validate state
        if not self.encrypted():
            raise ValueError("Cannot decrypt {}: Already plaintext.".format(self))

        author = Persona.query.get(self.author_id)
        if not author:
            raise NameError("Author of vesicle {} could not be found: Decryption failed.".format(self))

        if not reader_persona.id in self.keycrypt.keys():
            raise KeyError("No key found decrypting {} for {}".format(self, reader_persona))

        # Retrieve hashcode
        if self._hashcode:
            h = self._hashcode
        else:
            h = reader_persona.decrypt(self.keycrypt[reader_persona.id])
            self._hashcode = h

        # Generate the AES key
        key = AesKey(h, author.hmac_key, AES_BYTES)

        # Decrypt the data
        data = key.decrypt(self.payload)

        # Decode JSON
        self.data = json.loads(data)

    def decrypted(self):
        return self.data is not None

    def sign(self, author):
        """
        Sign a vesicle

        @param author Persona instance used to created the signature
        """

        if self.author_id is not None and self.author_id != author.id:
            raise ValueError("Signing author {} does not match existing author {}".format(author, self.author_id[:6]))

        if not self.encrypted():
            self.payload = json.dumps(self.data)
            self.data = None
            self.enc = self.enc.split("-")[0] + "plain"

        self.signature = author.sign(self.payload)
        self.author_id = author.id
        self.send_attributes.union({"signature", "author_id"})

    def signed(self):
        """
        Return true if vesicle has a signature and it is valid
        """

        if not hasattr(self, "signature"):
            return False

        author = Persona.query.get(self.author_id)
        if not author:
            raise NameError("Signature of {} could not be verified: author not found.".format(self))

        return author.verify(self.payload, self.signature)

    def add_recipient(self, recipient):
        """
        Add a persona to the keycrypt

        @param recipient Persona instance to be added
        """
        if not self.encrypted():
            raise Exception("Can not add recipients to plaintext vesicles")

        if not self.decrypted():
            raise Exception("Vesicle must be decrypted for adding recipients")

        if recipient.id in self.keycrypt.keys():
            raise KeyError("Persona {} is already a recipient of {}".format(recipient, self))

        if not self._hashcode:
            raise KeyError("Hashcode not found")

        key = recipient.encrypt(self._hashcode)
        self.keycrypt[recipient.id] = key

    def remove_recipient(self, recipient):
        """
        Remove a persona from the keycrypt

        @param recipient Persona instance to be removed from the keycrypt
        """
        del self.keycrypt[recipient.id]

    def json(self):
        """
        Return JSON representation
        """

        message = dict()
        for attr in self.send_attributes:
            message[attr] = getattr(self, attr)
        message["timestamp"] = datetime.datetime.now().isoformat()
        return json.dumps(message)

    @staticmethod
    def read(data):
        """
        Create a vesicle instance from its JSON representation

        @param data JSON representation obtained from a vesicle instance's json() method
        """

        msg = json.loads(data)

        version = msg["enc"].split("-")[0]
        if version != VESICLE_VERSION:
            raise ValueError("Unknown protocol version: {} \nExpecting: {}".format(version, VESICLE_VERSION))

        try:
            vesicle = Vesicle(
                message_type=msg["message_type"],
                payload=msg["payload"],
                signature=msg["signature"],
                keycrypt=msg["keycrypt"],
                created=msg["created"],
                reply_to=msg["reply_to"],
                enc=msg["enc"])
        except KeyError, e:
            self.logger.error("Vesicle malformed: missing key\n{}".format(e))
            return None

        # Verify signature
        try:
            if vesicle.signature is not None and not vesicle.signed():
                raise Exception("Invalid signature on {}".format(vesicle))
        except NameError, e:
            logging.warning(e)

        return vesicle
