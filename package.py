"""
Script to install Souma on OsX, Windows, and Unix

Usage:
    python package.py py2app
    python package.py py2exe
"""
import ez_setup
ez_setup.use_setuptools()

from setuptools import setup
import sys
import shutil
import py2exe

APP = ['run.py']
DATA_FILES = ['templates', 'static']

# might need to explicitly include dll:
# data_files=[('.', 'libmmd.dll')
# also:
# http://stackoverflow.com/questions/10060765/create-python-exe-without-msvcp90-dll
WIN_OPTIONS = {
    "dist_dir": "../dist",
    "includes": ["sqlalchemy.dialects.sqlite", "sqlalchemy.ext.declarative", "wtforms.ext", "jinja2.ext", "wtforms.ext.csrf", "sklearn", "sklearn.utils"],
    "packages": ["nucleus", "web_ui", "synapse", "astrolab"],
    "dll_excludes": ["libmmd.dll", "libifcoremd.dll", "libiomp5md.dll", "MSVCP90.dll"],
}

DARWIN_OPTIONS = {
    "argv_emulation": True,
    "bdist_base": "../build",
    "dist_dir": "../dist",
    "iconfile": "static/images/icon_osx.icns",
    "includes": ["sqlalchemy.dialects.sqlite", "sqlalchemy.ext.declarative", "wtforms.ext", "jinja2.ext", "wtforms.ext.csrf", "sklearn", "sklearn.utils"],
    "packages": ["nucleus", "web_ui", "synapse", "astrolab"],
    "site_packages": True,
    "plist": {
        "CFBundleShortVersionString": "0.2",
        "LSBackgroundOnly": True,
        "LSUIElement": True
    },
}



""" Platform specific options """
if sys.platform == 'darwin':
    class SklearnRecipe(object):
        """ Recipe for using sklearn in py2app """
        def check(self, dist, mf):
            m = mf.findNode('sklearn')
            if m is None:
                return None
            # Don't put sklearn in the site-packages.zip file
            return dict(
                packages=['sklearn']
            )
    import py2app.recipes
    py2app.recipes.sklearn = SklearnRecipe()

    """ Patch gevent implicit loader """
    patched = False
    with open("../lib/python2.7/site-packages/gevent/os.py", "r+") as f:
        patch = "\n# make os.path available here\nmy_os = __import__('os')\npath = my_os.path\n"
        for line in f.readlines():
            if line == "# make os.path available here":
                patched = True
        if not patched:
            f.write(patch)

    extra_options = dict(
        setup_requires=['py2app'],
        app=['run.py'],
        options=dict(py2app=DARWIN_OPTIONS))

elif sys.platform == 'win32':
    extra_options = dict(
        setup_requires=['py2exe'],
        app=APP,
        options=dict(py2exe=WIN_OPTIONS)
    )
else:
    extra_options = dict(
        scripts=APP)

setup(
    name="Souma",
    version="0.2.1",
    author="Cognitive Networks Group",
    author_email="cognitive-networks@googlegroups.com",
    url="https://github.com/ciex/souma/",
    scripts=["run.py", "set_hosts.py"],
    packages=["nucleus", "web_ui", "synapse", "astrolab"],
    data_files=DATA_FILES,
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README.md").read(),
    install_requires=open("requirements.txt").read(),
    **extra_options
)
