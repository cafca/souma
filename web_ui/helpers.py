import os
import logging
import pytz

from gevent import sleep

from flask import session
from datetime import datetime

# For calculating scores
epoch = datetime.utcfromtimestamp(0)
epoch_seconds = lambda dt: (dt - epoch).total_seconds() - 1356048000


def allowed_file(filename):
    from web_ui import app

    return '.' in filename and \
           filename.rsplit('.', 1)[1] in app.config['ALLOWED_EXTENSIONS']


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


def reset_userdata():
    """Reset all userdata files"""
    from web_ui import app

    for fileid in ["DATABASE", "SECRET_KEY_FILE", "PASSWORD_HASH_FILE"]:
        try:
            os.remove(app.config[fileid])
        except OSError:
            app.logger.warning("RESET: {} {} not found".format(fileid, app.config[fileid]))
        else:
            app.logger.warning("RESET: {} {} deleted".format(fileid, app.config[fileid]))


def localtime(value, tzval="UTC"):
    """Convert tz-naive UTC datetime into tz-naive local datetime

    Args:
        value (datetime): timezone naive UTC datetime
        tz (sting): timezone e.g. 'Europe/Berlin' (see pytz references)
    """
    value = value.replace(tzinfo=pytz.utc)  # assuming value is utc time
    value = value.astimezone(pytz.timezone(tzval))  # convert to local time (tz-aware)
    value = value.replace(tzinfo=None)  # make tz-naive again
    return value


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


def find_links(text):
    """Given a text, find all alive links inside

    Args:
        text(String): The input to parse

    Returns:
        tuple:
            list: List of response objects for found URLs
            str: Text with all link occurrences removed
    """
    import re
    import requests

    from web_ui import app

    # Everything that looks remotely like a URL
    expr = "(https?://[\S]+)"
    rv = list()

    candidates = re.findall(expr, text)

    if candidates:
        for c in candidates:
            app.logger.info("Testing potential link '{}' for availability".format(c))
            try:
                res = requests.head(c, timeout=15.0)
            except requests.exceptions.RequestException:
                pass
            else:
                if res and res.status_code < 400:
                    rv.append(res)
                    text = text.replace(c, "")
    return (rv, text)


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
    from web_ui import app

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
