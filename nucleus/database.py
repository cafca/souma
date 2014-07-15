import logging

from sqlalchemy.exc import OperationalError

from nucleus.models import *
from astrolab import interestmodel, topicmodel


def initialize_database(app, db):
    """Inspect and create/update database

    This method uses Alembic to upgrade the database to the latest revision. If
    no database is found, it will be created and also updated to the latest
    revision.

    The method can be used to automatically upgrade the database following an
    update applied by the auto-updater.

    Args:
        app: Flask app object

    Raises:
        OperationalError: An error occurred updating the database
    """

    # Create database if access fails
    try:
        Souma.query.get(app.config["SOUMA_ID"])
    except OperationalError:
        app.logger.info("Setting up database")
        db.create_all()

    # TODO: Update database
