"""
Script to install Souma on OsX, Windows, and Unix

Usage:
    python package.py py2app
    python package.py py2exe
"""
import ez_setup
import numpy  # important for py2exe to work
ez_setup.use_setuptools()

import sys
import os
from esky.bdist_esky import Executable
from setuptools import setup

if sys.platform == 'win32':
    import py2exe

APP = ['run.py', ]

""" Read current version identifier as recorded in `souma/__init__.py` """
with open("__init__.py", 'rb') as f:
    VERSION = f.readline().split("=")[1].strip().replace('"', '')

""" Compile list of static files """
with open(".gitignore") as f:
    ignorefiles = [l.strip() for l in f.readlines()]

DATA_FILES = [('', ['__init__.py'])]
for datadir in ['templates', 'static']:
    for root, dirs, files in os.walk(datadir):
        DATA_FILES.append((root, [os.path.join(root, fn) for fn in files if fn not in ignorefiles]))

""" Modules imported using import() need to be manually specified here """
INCLUDES = [
    "web_ui",
    "argparse",
    "jinja2.ext",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.ext.declarative",
    "wtforms.ext",
    "wtforms.ext.csrf",
    "flask",
    "flask_sqlalchemy",
    "flask.views",
    "flask.signals",
    "flask.helpers",
    "flask.ext",
    "flaskext",
    "flaskext.uploads",
    "flask_misaka",
    "flask_wtf",
    "sqlalchemy.orm",
    "sqlalchemy.event",
    "sqlalchemy.ext.declarative",
    "sqlalchemy.engine.url",
    "sqlalchemy.connectors.mxodbc",
    "sqlalchemy.connectors.mysqldb",
    "sqlalchemy.connectors.zxJDBC",
    "sqlalchemy.dialects.sqlite.base",
    "sqlalchemy.dialects.sybase.base",
    "sqlalchemy.dialects.sybase.mxodbc",
    "sqlalchemy.engine.base",
    "sqlalchemy.engine.default",
    "sqlalchemy.engine.interfaces",
    "sqlalchemy.engine.reflection",
    "sqlalchemy.engine.result",
    "sqlalchemy.engine.strategies",
    "sqlalchemy.engine.threadlocal",
    "sqlalchemy.engine.url",
    "sqlalchemy.engine.util",
    "sqlalchemy.event.api",
    "sqlalchemy.event.attr",
    "sqlalchemy.event.base",
    "sqlalchemy.event.legacy",
    "sqlalchemy.event.registry",
    "sqlalchemy.events",
    "sqlalchemy.exc",
    "sqlalchemy.ext.associationproxy",
    "sqlalchemy.ext.automap",
    "sqlalchemy.ext.compiler",
    "sqlalchemy.ext.declarative.api",
    "sqlalchemy.ext.declarative.base",
    "sqlalchemy.ext.declarative.clsregistry",
    "sqlalchemy.ext.horizontal_shard",
    "sqlalchemy.ext.hybrid",
    "sqlalchemy.ext.instrumentation",
    "sqlalchemy.ext.mutable",
    "sqlalchemy.ext.orderinglist",
    "sqlalchemy.ext.serializer",
    "sqlalchemy.inspection",
    "sqlalchemy.interfaces",
    "sqlalchemy.log",
    "sqlalchemy.orm.attributes",
    "sqlalchemy.orm.base",
    "sqlalchemy.orm.collections",
    "sqlalchemy.orm.dependency",
    "sqlalchemy.orm.deprecated_interfaces",
    "sqlalchemy.orm.descriptor_props",
    "sqlalchemy.orm.dynamic",
    "sqlalchemy.orm.evaluator",
    "sqlalchemy.orm.events",
    "sqlalchemy.orm.exc",
    "sqlalchemy.orm.identity",
    "sqlalchemy.orm.instrumentation",
    "sqlalchemy.orm.interfaces",
    "sqlalchemy.orm.loading",
    "sqlalchemy.orm.mapper",
    "sqlalchemy.orm.path_registry",
    "sqlalchemy.orm.persistence",
    "sqlalchemy.orm.properties",
    "sqlalchemy.orm.query",
    "sqlalchemy.orm.relationships",
    "sqlalchemy.orm.scoping",
    "sqlalchemy.orm.session",
    "sqlalchemy.orm.state",
    "sqlalchemy.orm.strategies",
    "sqlalchemy.orm.strategy_options",
    "sqlalchemy.orm.sync",
    "sqlalchemy.orm.unitofwork",
    "sqlalchemy.orm.util",
    "sqlalchemy.pool",
    "sqlalchemy.processors",
    "sqlalchemy.schema",
    "sqlalchemy.sql.annotation",
    "sqlalchemy.sql.base",
    "sqlalchemy.sql.compiler",
    "sqlalchemy.sql.ddl",
    "sqlalchemy.sql.default_comparator",
    "sqlalchemy.sql.dml",
    "sqlalchemy.sql.elements",
    "sqlalchemy.sql.expression",
    "sqlalchemy.sql.functions",
    "sqlalchemy.sql.naming",
    "sqlalchemy.sql.operators",
    "sqlalchemy.sql.schema",
    "sqlalchemy.sql.selectable",
    "sqlalchemy.sql.sqltypes",
    "sqlalchemy.sql.type_api",
    "sqlalchemy.sql.util",
    "sqlalchemy.sql.visitors",
    "sqlalchemy.types",
    "sqlalchemy.util._collections",
    "sqlalchemy.util.compat",
    "sqlalchemy.util.deprecations",
    "sqlalchemy.util.langhelpers",
    "sqlalchemy.util.queue",
    "sqlalchemy.util.topological",
    "flask_sqlalchemy._compat",
    "gzip",
    "gevent",
    "gevent.core",
    "logging",
    "Crypto",
    "Crypto.Hash"
]

# might need to explicitly include dll:
# data_files=[('.', 'libmmd.dll')
# also:
# http://stackoverflow.com/questions/10060765/create-python-exe-without-msvcp90-dll

WIN_OPTIONS = {
    "dist_dir": "../dist",
    "includes": INCLUDES,
    "iconfile": "static/images/icon_win.ico",
    "packages": ["nucleus", "web_ui", "synapse", "requests"],
    "dll_excludes": [],
    'bundle_files': 1
}

DARWIN_OPTIONS = {
    "argv_emulation": True,
    "bdist_base": "../build",
    "dist_dir": "../dist",
    "iconfile": "static/images/icon_osx.icns",
    "includes": INCLUDES,
    "packages": ["nucleus", "web_ui", "synapse", "requests"],
    "site_packages": True,
    "plist": {
        "CFBundleVersion": VERSION,
        "LSBackgroundOnly": True,
        "LSUIElement": True
    },
}

""" Platform specific options """
if sys.platform == 'darwin':
    # Compile .less files
    filenames = ["main", ]
    for fn in filenames:
        rv = os.system("touch ./static/css/{}.css".format(fn))
        rv += os.system("lesscpy ./static/css/{fn}.less > ./static/css/{fn}.css".format(fn=fn))

    """ Patch gevent implicit loader """
    patched = False
    with open("../lib/python2.7/site-packages/gevent/os.py", "r+") as f:
        patch = "\n# make os.path available here\nmy_os = __import__('os')\npath = my_os.path\n"
        for line in f.readlines():
            if line == "# make os.path available here":
                patched = True
        if not patched:
            f.write(patch)

    """ Setup Esky Executable """
    exe = Executable("run.py",
        description="Souma App",
        gui_only=True,
        icon=DARWIN_OPTIONS["iconfile"],
        name="run")

    extra_options = dict(
        setup_requires=['py2app'],
        app=['run.py'],
        options=dict(
            bdist_esky=dict(
                freezer_module="py2app",
                freezer_options=DARWIN_OPTIONS
            )
        ),
        scripts=[exe, ]
    )

    install_requires = open('requirements.txt').read()

elif sys.platform == 'win32':
    """ Setup Esky Executable """
    exe = Executable("run.py",
        description="Souma App",
        gui_only=True,
        icon=WIN_OPTIONS["iconfile"],
        name="run")

    extra_options = dict(
        setup_requires=['py2exe'],
        options=dict(
            bdist_esky=dict(
                freezer_module="py2exe",
                freezer_options=WIN_OPTIONS
            )
        ),
        scripts=[exe, ],
        zipfile=None
    )

    #Some little hacks for making py2exe work
    #Create empty __init__.py in flaskext directory
    #so py2exe recognizes it as module
    import flaskext
    try:
        flaskext.__file__
    except:
        flaskext_init = open(flaskext.__path__[0] + '\\__init__.py', 'w')
        flaskext_init.close()

    with open('requirements.txt') as f:
        install_requires = [req.strip() for req in f.readlines()]
else:
    extra_options = dict(
        scripts=APP)

    install_requires = open('requirements.txt').read()

setup(
    name="Souma",
    version=VERSION,
    author="Cognitive Networks Group",
    author_email="team@souma.io",
    url="https://github.com/ciex/souma/",
    packages=["nucleus", "web_ui", "synapse"],
    data_files=DATA_FILES,
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README.md").read(),
    install_requires=install_requires,
    **extra_options
)
