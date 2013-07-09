import logging
import blinker

# Setup Blinker namespace
notification_signals = blinker.Namespace()

# Setup logger namespace
logger = logging.getLogger('nucleus')
