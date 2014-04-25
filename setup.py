"""
Script to install Souma on OsX, Windows, and Unix

Usage:
    python setup.py py2app
"""

try:
    from ez_setup import use_setuptools
    use_setuptools()
except ImportError:
    print("Not using ez_setup")
    pass

try:
    from setuptools import setup
except ImportError:
    print("Not using setuptools")
    from distutils.core import setup

import sys

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

setup(
    name="Souma",
    version="0.2.1",
    author="Cognitive Networks Group",
    author_email="cognitive-networks@googlegroups.com",
    url="https://github.com/ciex/souma/",
    scripts=["run.py", "set_hosts.py", "ez_setup.py"],
    packages=["nucleus", "web_ui", "synapse", "astrolab"],
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README").read(),
    install_requires=open("requirements_osx.txt").read(),
    **extra_options
)
