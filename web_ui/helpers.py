from flask import session
from datetime import datetime


# For calculating scores
epoch = datetime.utcfromtimestamp(0)
epoch_seconds = lambda dt: (dt - epoch).total_seconds() - 1356048000


class Serializable():
    """ Make SQLAlchemy models json serializable"""
    def export(self, exclude=[], include=None):
        """Return this object as a dict"""
        if include:
            return {
                field: str(getattr(self, field)) for field in include}
        else:
            return {
                c.name: str(getattr(self, c.name)) for c in self.__table__.columns if c not in exclude}

    def json(self, exclude=[]):
        """Return this object JSON encoded"""
        import json
        return json.dumps(self.export(exclude), indent=4)


def score(star_object):
    import random
    return random.random() * 100 - random.random() * 10


def get_active_persona():
    from web_ui.models import Persona
    """ Return the currently active persona or 0 if there is no controlled persona. """

    if 'active_persona' not in session or session['active_persona'] is None:
        controlled_personas = Persona.query.filter('sign_private != ""')

        if controlled_personas.first() is None:
            return ""
        else:
            session['active_persona'] = controlled_personas.first().id

    return session['active_persona']


def score(star_object):
    import random
    return random.random() * 100 - random.random() * 10
