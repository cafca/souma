import sys
from esky import Esky
from web_ui import app as souma_app


def update_souma():
    """Check for updates and install if available"""
    app = Esky(sys.executable, souma_app.config["UPDATE_URL"])
    souma_app.logger.info("Running version {}".format(app.active_version))
    app.auto_update()
    # try:
    #     app.auto_update()
    # except Exception, e:
    #     souma_app.logger.error("Error updating Souma: {}".format(e))
