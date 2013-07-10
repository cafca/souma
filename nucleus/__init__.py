import logging
import blinker

# Setup Blinker namespace
notification_signals = blinker.Namespace()

# Setup logger namespace
logger = logging.getLogger('nucleus')

# Source formatting helper
source_format = lambda address: None if address is None else \
    "{host}:{port}".format(host=address[0], port=address[1])
