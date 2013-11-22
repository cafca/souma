import json
import datetime
import logging
import iso8601

from base64 import b64encode, b64decode
from hashlib import sha256
from keyczar.keys import AesKey, HmacKey
from uuid import uuid4

from nucleus import PersonaNotFoundError, InvalidSignatureError
from nucleus.models import Persona, DBVesicle
from web_ui import app, db

VESICLE_VERSION = "0.1"
DEFAULT_ENCODING = "{version}-{encoding}".format(version=VESICLE_VERSION, encoding="plain")
SYNAPSE_PORT = None
AES_BYTES = 256


class Vesicle(object):
    """
    Container for peer messages

    see https://github.com/ciex/souma/wiki/Vesicle

    """

    def __init__(self, message_type, id=None, data=None, payload=None, signature=None, author_id=None, created=None, keycrypt=None, enc=DEFAULT_ENCODING, reply_to=SYNAPSE_PORT, souma_id=app.config["SOUMA_ID"]):
        self.id = id if id is not None else uuid4().hex
        self._hashcode = None
        self.created = created
        self.data = data  # The data contained in the vesicle as a Python Dict object
        self.enc = enc
        self.keycrypt = keycrypt
        self.message_type = message_type
        self.payload = payload  # The data contained in the vesicle in JSON encoded firn
        self.reply_to = reply_to
        self.send_attributes = set(["message_type", "id", "payload", "reply_to", "enc", "souma_id"])
        self.signature = signature
        self.author_id = author_id
        self.souma_id = souma_id

    def __str__(self):
        """
        Return string identifier
        """

        if hasattr(self, "author_id") and self.author_id is not None:
            p = Persona.query.get(self.author_id)
            if p is not None:
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
        if self.encrypted():
            raise ValueError("Cannot encrypt already encrypted {}".format(self))

        # Retrieve a string representation of the message data
        if self.payload is not None:
            payload = self.payload
        else:
            if self.data == "" or self.data is None:
                raise ValueError("Cannot encrypt empty {} (`data` and `payload` fields are empty)".format(self))
            payload = json.dumps(self.data)

        # Compute its SHA256 hash code
        self._hashcode = sha256(payload).hexdigest()[:32]

        # Generate an AES key with key=h

        # AES uses HMAC to authenticate its output. Usually this requires a key different from the
        # AES encryption key. Here I derive it from the AES key because authentication is already 
        # provided by the separate RSA signature.
        # TODO: Ask someone whether this is a good idea
        key = AesKey(self._hashcode, HmacKey(self._hashcode), AES_BYTES)

        # Encrypt payload using the AES key
        payload_encrypted = b64encode(key.Encrypt(payload))

        self.payload = payload_encrypted
        self.data = None
        self.author_id = author.id
        self.enc = "{version}-AES-{bytes}".format(version=self.enc.split("-")[0], bytes=AES_BYTES)
        self.send_attributes = self.send_attributes.union(set(["author_id", "keycrypt"]))

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

        if not reader_persona.id in self.keycrypt.keys():
            raise KeyError("No key found decrypting {} for {}".format(self, reader_persona))

        # Retrieve hashcode
        if self._hashcode:
            h = self._hashcode
        else:
            h = reader_persona.decrypt(self.keycrypt[reader_persona.id])
            self._hashcode = h

        # Generate the AES key (see encrypt() above)
        key = AesKey(h, HmacKey(self._hashcode), AES_BYTES)

        # Decrypt the data
        data = key.Decrypt(b64decode(self.payload))

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
            self.enc = self.enc.split("-")[0] + "-plain"

        self.signature = author.sign(self.payload)
        self.author_id = author.id
        self.send_attributes = self.send_attributes.union(set(["signature", "author_id"]))

    def signed(self):
        """
        Return true if vesicle has a signature and it is valid
        """

        if not hasattr(self, "signature"):
            return False

        author = Persona.query.get(self.author_id)
        if not author:
            raise PersonaNotFoundError(self.author_id)

        return author.verify(self.payload, self.signature)

    def add_recipient(self, recipient):
        """
        Add a persona to the keycrypt

        @param recipient Persona instance to be added
        """
        if not self.encrypted():
            raise Exception("Can not add recipients to plaintext vesicles")

        if not self._hashcode:
            raise KeyError("Hashcode not found")

        if not hasattr(self, "keycrypt") or self.keycrypt is None:
            self.keycrypt = dict()

        if recipient.id not in self.keycrypt.keys():
            key = recipient.encrypt(self._hashcode)
            self.keycrypt[recipient.id] = key
            app.logger.info("Added {} as a recipient of {}".format(recipient, self))
        else:
            app.logger.info("{} is already a recipient of {}".format(recipient, self))

    def remove_recipient(self, recipient):
        """
        Remove a persona from the keycrypt

        @param recipient Persona instance to be removed from the keycrypt
        """
        del self.keycrypt[recipient.id]
        app.logger.info("Removed {} as a recipient of {}".format(recipient, self))

    def json(self):
        """
        Return JSON representation
        """
        # Temporarily encode data if this is a plaintext message
        if self.payload is None:
            plainenc = True
            self.payload = json.dumps(self.data)
        else:
            plainenc = False

        message = dict()
        for attr in self.send_attributes:
            message[attr] = getattr(self, attr)
        message["created"] = datetime.datetime.now().isoformat()
        r = json.dumps(message)

        if plainenc:
            self.payload = None
        return r

    @staticmethod
    def read(data):
        """
        Create a vesicle instance from its JSON representation

        Args:
            data (String): JSON representation of a Vesicle

        Returns:
            Vesicle: The newly read Vesicle object

        Raises:
            ValueError: Unknown protocol version or malformed created timestamp
            KeyError: Missing key in vesicle JSON
            InvalidSignatureError: Does not match author_id's pubkey
        """

        msg = json.loads(data)

        version, encoding = msg["enc"].split("-", 1)
        if version != VESICLE_VERSION:
            raise ValueError("Unknown protocol version: {} \nExpecting: {}".format(version, VESICLE_VERSION))

        try:
            if encoding == "plain":
                vesicle = Vesicle(
                    message_type=msg["message_type"],
                    id=msg["id"],
                    payload=msg["payload"],
                    created=iso8601.parse_date(msg["created"]).replace(tzinfo=None),
                    reply_to=msg["reply_to"],
                    enc=msg["enc"])
            else:
                vesicle = Vesicle(
                    message_type=msg["message_type"],
                    id=msg["id"],
                    payload=msg["payload"],
                    keycrypt=msg["keycrypt"],
                    created=iso8601.parse_date(msg["created"]).replace(tzinfo=None),
                    reply_to=msg["reply_to"],
                    enc=msg["enc"])

            if "signature" in msg:
                vesicle.signature = msg["signature"]
                vesicle.author_id = msg["author_id"]
        except KeyError, e:
            app.logger.error("Vesicle malformed: missing key\n{}".format(e))
            return KeyError(e)
        except iso8601.ParseError, e:
            app.logger.error("Vesicle malformed: Error parsing date ({})".format(e))
            return ValueError("Vesicle malformed: Error parsing date ({})".format(e))

        # Verify signature
        if vesicle.signature is not None and not vesicle.signed():
            raise InvalidSignatureError("Invalid signature on {}".format(vesicle))

        return vesicle

    @staticmethod
    def load(self, id):
        """Read a Vesicle back from the local database"""
        v = DBVesicle.query.get(id)
        if v:
            return Vesicle.read(v.json)
        else:
            raise KeyError("<Vesicle [{}]> could not be found".format(id[:6]))

    def save(self, myelin=False, json=None):
        
        """
        Save this Vesicle to the local Database, overwriting any previous versions

        Parameters:
            myelin (Bool): Set True if this was received from Myelin
            json (String): Value to store as JSON instead of automatically generated JSON
        """

        if self.payload is None:
            raise TypeError("Cannot store Vesicle without payload ({}). Please encrypt or sign.".format(self))

        if json is None:
            json = self.json()

        v = DBVesicle.query.get(self.id)
        if v is None:
            app.logger.info("Storing {} in database".format(self))
            v = DBVesicle(
                id=self.id,
                json=json,
                source_id=self.souma_id if not myelin else "myelin",
                author_id=self.author_id if 'author_id' in dir(self) else None
            )
            db.session.add(v)
            db.session.commit()
        else:
            app.logger.info("Didn't save {}. Already existing in database.".format(self))
