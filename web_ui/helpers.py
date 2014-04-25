import os

from web_ui import app
from flask import session
from datetime import datetime
from gevent import sleep


# For calculating scores
epoch = datetime.utcfromtimestamp(0)
epoch_seconds = lambda dt: (dt - epoch).total_seconds() - 1356048000


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in app.config['ALLOWED_EXTENSIONS']


def get_active_persona():
    from nucleus.models import Persona
    """ Return the currently active persona or 0 if there is no controlled persona. """

    if 'active_persona' not in session or session['active_persona'] is None:
        """Activate first Persona with a private key"""
        controlled_persona = Persona.query.filter('sign_private != ""').first()

        if controlled_persona is None:
            return ""
        else:
            session['active_persona'] = controlled_persona.id

    return session['active_persona']


def host_kind():
    """Determine whether the App runs pacaged or from the command line

    Returns:
        String: Host system kind
            ``    -- Runs from the command line
            `win` -- Packaged Windows app
            `osx` -- Packaded OSX app

    """
    import sys
    frozen = getattr(sys, 'frozen', None)

    if not frozen:
        return ''
    elif frozen in ('dll', 'console_exe', 'windows_exe'):
        return 'win'
    elif frozen in ('macosx_app',):
        return 'osx'


def score(star_object):
    import random
    return random.random() * 100 - random.random() * 10


def watch_layouts(continuous=True):
    """Watch layout file and update layout definitions once they change

    Parameters:
        continuous (bool): Set False to only load definitions once

    Returns:
        dict: Layout definitions if `continuous` is False
    """
    import json

    mtime_last = 0
    layout_filename = os.path.join(app.config["RUNTIME_DIR"], 'static', 'layouts.json')
    cont = True
    while cont is True:
        mtime_cur = os.path.getmtime(layout_filename)

        if mtime_cur != mtime_last:
            try:
                with open(layout_filename) as f:
                    app.config['LAYOUT_DEFINITIONS'] = json.load(f)
            except IOError:
                app.logger.error("Failed loading layout definitions")
                app.config['LAYOUT_DEFINITIONS'] = dict()
            else:
                app.logger.info("Loaded {} layout definitions".format(len(app.config["LAYOUT_DEFINITIONS"])))
        mtime_last = mtime_cur

        cont = True if continuous is True else False
        sleep(1)

    return app.config["LAYOUT_DEFINITIONS"]
