from web_ui import app
from flask import session
from datetime import datetime


# For calculating scores
epoch = datetime.utcfromtimestamp(0)
epoch_seconds = lambda dt: (dt - epoch).total_seconds() - 1356048000


def score(star_object):
    import random
    return random.random() * 100 - random.random() * 10


def get_active_persona():
    from nucleus.models import Persona
    """ Return the currently active persona or 0 if there is no controlled persona. """

    if 'active_persona' not in session or session['active_persona'] is None:
        controlled_personas = Persona.query.filter('sign_private != ""')

        if controlled_personas.first() is None:
            return ""
        else:
            session['active_persona'] = controlled_personas.first().id

    return session['active_persona']


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in app.config['ALLOWED_EXTENSIONS']
