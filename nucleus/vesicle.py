import json
import datetime
import iso8601

from base64 import b64encode, b64decode
from hashlib import sha256
from keyczar.keys import AesKey, HmacKey

from nucleus import PersonaNotFoundError, InvalidSignatureError, UnauthorizedError, VesicleStateError
from nucleus.models import Persona
from web_ui import app, db

VESICLE_VERSION = "0.1"
DEFAULT_ENCODING = "{version}-{encoding}".format(version=VESICLE_VERSION, encoding="plain")
SYNAPSE_PORT = None
AES_BYTES = 256


class Vesicle(db.Model):
    """
    Container for peer messages

    see https://github.com/ciex/souma/wiki/Vesicle

    """
    __tablename__ = "vesicle"
    id = db.Column(db.String(32), primary_key=True)
    message_type = db.Column(db.String(32))
    payload = db.Column(db.Text)
    signature = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.datetime.now())
    keycrypt = db.Column(db.PickleType())
    enc = db.Column(db.String(16), default=DEFAULT_ENCODING)

    author_id = db.Column(db.String(32), db.ForeignKey('persona.id', use_alter=True, name="fk_author_id"))
    author = db.relationship('Persona', primaryjoin="Persona.id==Vesicle.author_id", post_update=True)

    _hashcode = None
    _send_attributes = set(["message_type", "id", "payload", "enc"])
    data = None

    def __str__(self):
        """
        Return string identifier

        Returns:
            String: Identifier
        """

        if hasattr(self, "author_id") and self.author_id is not None:
            if self.author is not None:
                author = self.author
            else:
                author = self.author_id[:6]
        else:
            author = "anon"
        return "<vesicle {type}@{author}>".format(type=self.message_type, author=author)

    def encrypt(self, recipients):
        """
        Encrypt the vesicle's data field into the payload field using self.author and set the data field to None

        Args:
            recipients (list): A list of recipient Persona objects who will be added to the keycrypt

        Raises:
            VesicleStateError: If this Vesicle is already encrypted
        """

        # Validate state
        if self.encrypted():
            raise VesicleStateError("Cannot encrypt already encrypted {}".format(self))

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
        self.enc = "{version}-AES-{bytes}".format(version=self.enc.split("-")[0], bytes=AES_BYTES)
        self._send_attributes = self._send_attributes.union(set(["author_id", "keycrypt"]))

        for r in recipients:
            self.add_recipient(r)

    def encrypted(self):
        """
        Return True if this Vesicle is encrypted

        Returns:
            Boolean: if encrypted
        """
        return self.payload is not None and self.enc.split("-")[1] != "plain"

    def decrypt(self, reader_persona=None):
        """
        Decrypt the vesicle's payload field into the data field.

        This method does not remove the ciphertext from the payload field, so that encrypted() still returns True.

        Args:
            reader_persona (Persona): Persona instance used to retrieve the hash key

        Returns:
            Persona: reader_persona used for decryption

        Raises:
            ValueError: If this Vesice is already plaintext
            KeyError: If no Key was found for decrypting with reader_persona
            UnauthorizedError: If no Persona was found for decrypting
        """
        if reader_persona is None:
            for p in Persona.query.filter('sign_private != ""'):
                if p.id in self.keycrypt.keys():
                    reader_persona = p
                    continue

            if reader_persona is None:
                raise UnauthorizedError("Could not decrypt {}. No recipient found in owned personas.".format(self))

        # Validate state
        if not self.encrypted():
            raise VesicleStateError("Cannot decrypt {}: Already plaintext.".format(self))

        if not reader_persona.id in self.keycrypt.keys():
            raise UnauthorizedError("No key found decrypting {} for {}".format(self, reader_persona))

        # Retrieve hashcode
        if self._hashcode is not None:
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

        return reader_persona

    def decrypted(self):
        """
        Return True if this Vesice is decrypted

        Returns:
            Boolean: if decrypted
        """
        return self.data is not None

    def sign(self):
        """
        Sign a vesicle using vesicle.author's signing key

        Raises:
            KeyError: If no author is defined
        """
        if self.author is None:
            raise KeyError("Vesicle defines no author for signing")

        if not self.encrypted():
            self.payload = json.dumps(self.data)
            self.data = None
            self.enc = self.enc.split("-")[0] + "-plain"

        self.signature = self.author.sign(self.payload)
        self._send_attributes = self._send_attributes.union(set(["signature", "author_id"]))

    def signed(self):
        """
        Return True if vesicle has a signature and it is valid

        Returns:
            Boolean: If signed
        """

        if not hasattr(self, "signature"):
            return False

        if not self.author:
            raise PersonaNotFoundError(self.author_id)

        return self.author.verify(self.payload, self.signature)

    def add_recipient(self, recipient):
        """
        Add a persona to the keycrypt

        Args:
            recipient (Persona): Persona instance to be added

        Raises:
            VesicleStateError: When trying to add recipients to a plaintext Vesicle
            KeyError: If no hashcode was found
        """
        if not self.encrypted():
            raise VesicleStateError("Can not add recipients to plaintext vesicles")

        if not self._hashcode:
            raise KeyError("Hashcode not found")

        if self.keycrypt is None:
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

        Args:
            recipient (Persona): Persona to be removed from the keycrypt
        """
        del self.keycrypt[recipient.id]
        app.logger.info("Removed {} as a recipient of {}".format(recipient, self))

    def json(self):
        """
        Generate JSON representation of this Vesicle, including all attributes defined in self._send_attributes.

        Returns:
            String: JSON encoded Vesicle contents
        """
        # Temporarily encode data if this is a plaintext message
        if self.payload is None:
            plainenc = True
            self.payload = json.dumps(self.data)
        else:
            plainenc = False

        message = dict()
        for attr in self._send_attributes:
            message[attr] = getattr(self, attr)
        message["created"] = datetime.datetime.now().isoformat()
        message["souma_id"] = app.config["SOUMA_ID"]
        r = json.dumps(message)

        if plainenc:
            self.payload = None
        return r

    @staticmethod
    def read(data):
        """
        Create a vesicle instance from its JSON representation. Checks signature validity.

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
                    id=msg["id"],
                    message_type=msg["message_type"],
                    payload=msg["payload"],
                    created=iso8601.parse_date(msg["created"]).replace(tzinfo=None),
                    enc=msg["enc"])
            else:
                vesicle = Vesicle(
                    id=msg["id"],
                    message_type=msg["message_type"],
                    payload=msg["payload"],
                    keycrypt=msg["keycrypt"],
                    created=iso8601.parse_date(msg["created"]).replace(tzinfo=None),
                    enc=msg["enc"])
                vesicle._send_attributes = vesicle._send_attributes.union(set(["keycrypt"]))

            author = Persona.query.get(msg["author_id"])
            if author is not None:
                vesicle.author = author
            else:
                app.logger.warning("Vesicle author '{}' not found in local DB".format(msg["author_id"]))
                vesicle.author_id = msg["author_id"]

            if "signature" in msg:
                vesicle.signature = msg["signature"]
                vesicle.author_id = msg["author_id"]
                vesicle._send_attributes = vesicle._send_attributes.union(set(["author_id", "signature"]))
        except KeyError, e:
            raise KeyError(e)
        except iso8601.ParseError, e:
            raise ValueError("Vesicle malformed: Error parsing date ({})".format(e))

        # Verify signature
        if vesicle.signature is not None and not vesicle.signed():
            raise InvalidSignatureError("Invalid signature on {}".format(vesicle))

        return vesicle
