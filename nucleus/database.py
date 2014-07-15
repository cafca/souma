from sqlalchemy.exc import OperationalError

from nucleus.models import *


def initialize_database(app, db):
    """Inspect and create/update database

    This method tests whether a database is set up and creates it if not.

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
