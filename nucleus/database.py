from sqlalchemy.exc import OperationalError


def initialize_database(app):
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
    pass
