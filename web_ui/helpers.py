from flask import session
from soma.web_ui.models import Persona


def get_active_persona():
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
