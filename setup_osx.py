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
        options=dict(py2app={
            "argv_emulation": True,
            "bdist_base": "../build",
            "dist_dir": "../dist",
            "iconfile": "static/images/icon_osx.icns",
            "includes": [
                "jinja2.ext",
                "sklearn",
                "sklearn.utils",
                "sqlalchemy.dialects.sqlite",
                "sqlalchemy.ext.declarative",
                "wtforms.ext",
                "wtforms.ext.csrf",
                "flask",
                # "flask_restful",
                "flask_sqlalchemy",
                "flask.views",
                "flask.signals",
                # "flask_restful.utils",
                "flask.helpers",
                # "flask_restful.representations",
                # "flask_restful.representations.json",
                "flaskext",
                "flaskext.wtf",
                "flask.ext",
                "flask.ext.wtf",
                "sqlalchemy.orm",
                "sqlalchemy.event",
                "sqlalchemy.ext.declarative",
                "sqlalchemy.engine.url",
                "sqlalchemy.connectors.mxodbc",
                "sqlalchemy.connectors.mysqldb",
                "sqlalchemy.connectors.zxJDBC",
                # "sqlalchemy.connectorsodbc.py",
                "sqlalchemy.dialects.sqlite.base",
                # "sqlalchemy.dialects.sqlitesqlite.py",
                "sqlalchemy.dialects.sybase.base",
                "sqlalchemy.dialects.sybase.mxodbc",
                # "sqlalchemy.dialects.sybaseodbc.py",
                # "sqlalchemy.dialects.sybasesybase.py",
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
                "flask_sqlalchemy._compat"],
            "packages": ["nucleus", "web_ui", "synapse", "astrolab"],
            "plist": {
                "CFBundleShortVersionString": "0.2",
                "LSBackgroundOnly": True,
                "LSUIElement": True
            },
            "site_packages": True,
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
    version="0.2.1",
    author="Cognitive Networks Group",
    author_email="cognitive-networks@googlegroups.com",
    url="https://github.com/ciex/souma/",
    scripts=["run.py"],
    packages=["nucleus", "web_ui", "synapse", "astrolab"],
    data_files=DATA_FILES,
    license="Apache License 2.0",
    description="A Cognitive Network for Groups",
    long_description=open("README.md").read(),
    install_requires=open("requirements.txt").read(),
    **extra_options
)
