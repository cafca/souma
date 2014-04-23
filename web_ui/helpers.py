import os

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
    """ Return the currently active persona or 0 if there is no controlled persona. """
    from nucleus.models import Persona

    if 'active_persona' not in session or session['active_persona'] is None:
        """Activate first Persona with a private key"""
        controlled_persona = Persona.query.filter('sign_private != ""').first()

        if controlled_persona is None:
            return ""
        else:
            session['active_persona'] = controlled_persona.id

    return session['active_persona']


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in app.config['ALLOWED_EXTENSIONS']


def compile_less():
    """Compile all less files that are newer than their css counterparts"""
    filenames = app.config["LESS_FILENAMES"]
    for fn in filenames:
        app.logger.info("Compiling {}.less".format(fn))

        os.system("touch static/main/{}.css".format(fn))
        os.system("lesscpy static/css/{fn}.less > static/css/{fn}.css".format(fn=fn))
