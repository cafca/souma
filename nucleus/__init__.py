import logging
import blinker

ERROR = {
    "MISSING_MESSAGE_TYPE": (1, "No message type found."),
    "MISSING_PAYLOAD": (2, "No data payload found."),
    "OBJECT_NOT_FOUND": lambda name: (3, "Object does not exist: ".format(name)),
    "MISSING_KEY": lambda name: (4, "Missing data for this request: {}".format(name)),
    "INVALID_SIGNATURE": (5, "Invalid signature."),
    "INVALID_SESSION": (6, "Session invalid. Please re-authenticate."),
    "DUPLICATE_ID": lambda id: (7, "Duplicate ID: {}".format(id)),
    "SOUMA_NOT_FOUND": lambda id: (8, "Souma not found: {}".format(id)),
    "MISSING_PARAMETER": lambda name: (9, "Missing HTTP parameter: {}".format(name)),
}

# Setup Blinker namespace
notification_signals = blinker.Namespace()

# Setup logger namespace
logger = logging.getLogger('nucleus')

# Source formatting helper
source_format = lambda address: None if address is None else \
    "{host}:{port}".format(host=address[0], port=address[1])

# Possible states of stars
STAR_STATES = {
    -2: (-2, "deleted"),
    -1: (-1, "unavailable"),
    0: (0, "published"),
    1: (1, "draft"),
    2: (2, "private"),
    3: (3, "updating")
}

# Possible states of planets
PLANET_STATES = {
    -1: (-1, "unavailable"),
    0: (0, "published"),
    1: (1, "private"),
    2: (2, "updating")
}

# Possible states of 1ups
ONEUP_STATES = {
    -1: "disabled",
    0: "active",
    1: "unknown creator"
}


class InvalidSignatureError(Exception):
    """Throw this error when a signature fails authenticity checks"""
    pass


class PersonaNotFoundError(Exception):
    """Throw this error when the Persona profile specified for an action is not available"""
    pass


class UnauthorizedError(Exception):
    """Throw this error when the active Persona is not authorized for an action"""
    pass


class VesicleStateError(Exception):
    """Throw this error when a Vesicle's state does not allow for an action"""
    pass
