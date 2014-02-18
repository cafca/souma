import lxml.html
from gensim import utils
from gevent import spawn_later
import urllib
from readability import Document


def _clean_attrib(node):
    for n in node:
        _clean_attrib(n)
    node.attrib.clear()


def remove_html(text):
    tree = lxml.html.fromstring(text)
    cleaner = lxml.html.clean.Cleaner(style=True)
    cleaner.clean_html(tree)
    _clean_attrib(tree)

    return lxml.html.tostring(tree, encoding='unicode', pretty_print=True,
                              method='text')


def tokenize(text):
    text = remove_html(text)

    return [token.encode('utf8')
            for token in utils.tokenize(text, lower=True, errors='ignore')
            if 2 <= len(token) <= 15 and not token.startswith('_')]


def get_site_content(link):
    # request link content
    req = urllib.urlopen(link)
    page = req.read()

    # extract the  (most likely) main content
    doc = Document(page, url=link)
    content = doc.summary(html_partial=True)

    return remove_html(content)


def repeated_func_schedule(time, func):
    spawn_later(0, func)
    spawn_later(time, repeated_func_schedule, time, func)
