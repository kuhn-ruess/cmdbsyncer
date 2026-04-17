"""Gunicorn config for the Docker image.

Binds and worker counts match the previous ``uwsgi_docker.ini``. The
``post_fork`` hook resets every MongoEngine/pymongo connection inherited
from the master process so each worker opens its own sockets after
``fork()``. This keeps us safe even if someone later enables ``preload_app``.
"""
# Gunicorn reads these module-level names as setting names — they are not
# Python constants and must stay lower-case.
# pylint: disable=invalid-name

bind = "0.0.0.0:9090"
workers = 2
threads = 2
accesslog = "-"
errorlog = "-"


def post_fork(server, worker):  # pylint: disable=unused-argument
    """Drop parent-inherited Mongo sockets and reconnect inside the worker."""
    import mongoengine  # pylint: disable=import-outside-toplevel
    from application import app, db  # pylint: disable=import-outside-toplevel
    mongoengine.disconnect()
    db.init_app(app)
