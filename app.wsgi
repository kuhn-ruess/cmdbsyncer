#!/usr/bin/env python3
"""
WSGI entry point for CMDBsyncer.

Used by:
- gunicorn  (Docker image: `gunicorn ... app:app`)
- Apache + mod_wsgi (`WSGIScriptAlias / .../app.wsgi`, expects `application`)
- uWSGI (`wsgi-file = .../app.wsgi`, `callable = app`)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if 'config' not in os.environ:
    os.environ['config'] = 'prod'

from application import app  # noqa: E402  pylint: disable=wrong-import-position
application = app
