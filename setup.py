"""
Script to install Souma on OsX, Windows, and Unix

Usage:
    python setup.py py2app
"""
import ez_setup
ez_setup.use_setuptools()

import sys
import shutil
from setuptools import setup

APP = ['run.py']


""" Platform specific options """
if sys.platform == 'darwin':
    extra_options = dict(
        app=['run.py'],
    )
elif sys.platform == 'win32':
    extra_options = dict(
        setup_requires=['py2exe'],
        app=APP,
    )
else:
    extra_options = dict(
        scripts=APP)

print 'Deleting build dirs...'
try:
    shutil.rmtree('../build')
    shutil.rmtree('../dist')
except OSError:
    pass

setup(
    name="Souma",
    version="0.2.1",
    author="Cognitive Networks Group",
    author_email="cognitive-networks@googlegroups.com",
    url="https://github.com/ciex/souma/",
    scripts=["run.py", "set_hosts.py"],
    packages=["nucleus", "web_ui", "synapse", "astrolab"],
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README").read(),
    install_requires=open("requirements.txt").read(),
    **extra_options
)
