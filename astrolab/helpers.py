import lxml.html
import requests

from gensim import utils
from gevent import spawn_later
from readability import Document
from lxml.etree import XMLSyntaxError

from web_ui import app


def _clean_attrib(node):
    for n in node:
        _clean_attrib(n)
    node.attrib.clear()


def remove_html(text):
    rv = ""

    try:
        tree = lxml.html.fromstring(text)
    except XMLSyntaxError:
        app.logger.error("Error getting XML tree")
        import pdb; pdb.set_trace()
    else:
        cleaner = lxml.html.clean.Cleaner(style=True)
        cleaner.clean_html(tree)
        _clean_attrib(tree)

        rv = lxml.html.tostring(tree, encoding='unicode', pretty_print=True,
                              method='text')
    return rv


def tokenize(text):
    text = remove_html(text)

    return [token.encode('utf8')
            for token in utils.tokenize(text, lower=True, errors='ignore')
            if 2 <= len(token) <= 15 and not token.startswith('_')]


def valid_request(request):
    """Return True if request was successfull and contains text content"""
    if request is None:
        return False

    if request.status_code >= 400:
        return False

    if not request.headers["content-type"]:
        return False

    if not request.headers["content-type"][:9] in ["text/html", "text/plain"]:
        return False

    return True


def get_site_content(link):
    """Try and extract site content from url"""
    rv = ""

    try:
        r = requests.get(link, timeout=15.0)
    except requests.exceptions.RequestException, e:
        app.logger.warning("Failed loading URL '{}': {}".format(link, e))
    else:
        if valid_request(r):
            # extract the  (most likely) main content
            doc = Document(r.text, url=link)
            content = doc.summary(html_partial=True)
            rv = remove_html(content)
        else:
            app.logger.info("Invalid request {} for url '{}'".format(r, link))

    return rv


def repeated_func_schedule(time, func):
    spawn_later(0, func)
    spawn_later(time, repeated_func_schedule, time, func)
