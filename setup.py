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
DATA_FILES = ['templates', 'static']

if sys.platform == 'darwin':
    extra_options = dict(
        setup_requires=['py2app'],
        app=['run.py'],
        options=dict(py2app={
            "argv_emulation": True,
            "bdist_base": "../build",
            "dist_dir": "../dist",
            "site_packages": True,
            "includes": ["sqlalchemy.dialects.sqlite", "sqlalchemy.ext.declarative", "wtforms.ext", "jinja2.ext", "wtforms.ext.csrf"],
            "packages": ["nucleus", "web_ui", "synapse", "astrolab"],
            "plist": {
                "LSBackgroundOnly": True,
                "LSUIElement": True
            }
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

print 'Deleting build dirs...'
try:
    shutil.rmtree('../build')
    shutil.rmtree('../dist')
except OSError:
    pass

setup(
    name="Souma",
    version="0.2",
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
