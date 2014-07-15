import sys

from esky import Esky
from gevent import spawn_later

from web_ui import app


def update_souma():
    """Check for updates and install if available"""
    esk = Esky(sys.executable, app.config["UPDATE_URL"])
    try:
        esk.auto_update()

    # Exception kinds are badly documented for the Esky auto_update method,
    # that's why I'm using a catch-all except here.
    # Esky advises for writing custom auto_update routines anyway, which is
    # probably a good idea before we start public beta testing. Btw..
    # TODO: Custum update routine
    except Exception, e:
        app.logger.error("Error updating Souma: {}".format(e))


def timed_update_check():
    """Repeatedly check for updates and install if any are available"""
    delay = app.config["UPDATE_CHECK_INTERVAL"]
    spawn_later(0, update_souma)
    spawn_later(delay, timed_update_check)
