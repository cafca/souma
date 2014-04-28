import os
import logging
import json

from gevent import sleep

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
    from web_ui import app

    return '.' in filename and \
           filename.rsplit('.', 1)[1] in app.config['ALLOWED_EXTENSIONS']


def reset_userdata():
    """Reset all userdata files"""
    from web_ui import app

    for fileid in ["DATABASE", "SECRET_KEY_FILE", "PASSWORD_HASH_FILE"]:
        try:
            os.remove(app.config[fileid])
        except OSError:
            app.logger.warning("RESET: {} not found".format(fileid))
        else:
            app.logger.warning("RESET: {} deleted".format(fileid))


def compile_less(filenames=None):
    """Compile all less files that are newer than their css counterparts.

    Args:
        filenames (list): List of .less files in `static/css/` dir
    """
    if filenames is None:
        from web_ui import app
        filenames = app.config["LESS_FILENAMES"]

    for fn in filenames:
        logging.info("Compiling {}.less".format(fn))

        rv = os.system("touch static/css/{}.css".format(fn))
        rv += os.system("lesscpy static/css/{fn}.less > static/css/{fn}.css".format(fn=fn))

    if rv > 0:
        logging.error("Compilation of LESS stylesheets failed.")


def watch_layouts():
    from web_ui import app

    mtime_last = 0
    layout_filename = os.path.join(os.path.abspath("."), 'web_ui', 'layouts.json')
    while True:
        sleep(1)
        mtime_cur = os.path.getmtime(layout_filename)
        if mtime_cur != mtime_last:
            app.logger.info("Loading new layout definitions")
            try:
                with open(layout_filename) as f:
                    app.config['LAYOUT_DEFINITIONS'] = json.load(f)
            except IOError:
                app.logger.error("Failed loading layout definitions")
                app.config['LAYOUT_DEFINITIONS'] = dict()
        mtime_last = mtime_cur
