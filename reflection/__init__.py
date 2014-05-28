import logging
from web_ui import db, app

from sqlalchemy.orm import sessionmaker


# Import at bottom to avoid circular imports
# Import all models to allow querying db binds
from nucleus.models import *

# _Session is a custom sessionmaker that returns a session prefconfigured with the
# model bindings from Nucleus
_Session = sessionmaker(bind=db.get_engine(app))


def create_session():
    """Return a session to be used for database connections

    Returns:
        Session: SQLAlchemy session object
    """
    # Produces integrity errors!
    # return _Session()

    # db.session is managed by Flask-SQLAlchemy and bound to a request
    return db.session
