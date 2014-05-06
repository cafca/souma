import sys
from esky import Esky
from web_ui import app as souma_app


def update_souma():
    """Check for updates and install if available"""
    app = Esky(sys.executable, souma_app.config["UPDATE_URL"])
    try:
        app.auto_update()

    # Exception kinds are badly documented for the Esky auto_update method,
    # that's why I'm using a catch-all except here.
    # Esky advises for writing custom auto_update routines anyway, which is
    # probably a good idea before we start public beta testing.
    except Exception, e:
        souma_app.logger.error("Error updating Souma: {}".format(e))
