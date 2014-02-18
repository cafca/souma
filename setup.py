"""
Script to install Souma on OsX, Windows, and Unix

Usage:
    python setup.py py2app
"""
import ez_setup
ez_setup.use_setuptools()

import sys
from setuptools import setup

APP = ['run.py']

if sys.platform == 'darwin':
    extra_options = dict(
        setup_requires=['py2app'],
        app=APP,
        options=dict(py2app={
            "argv_emulation": True,
            "bdist_base": "../build",
            "dist_dir": "../dist"
        }),
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
    version="0.2",
    author="Cognitive Networks Group",
    author_email="cognitive-networks@googlegroups.com",
    packages=["nucleus", "web_ui", "synapse", "astrolab"],
    scripts=["run.py"],
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README.md").read(),
    install_requires=[],
    **extra_options
)
