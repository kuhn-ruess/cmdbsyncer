"""Gunicorn config for the Docker image.

Binds and worker counts match the previous ``uwsgi_docker.ini``. Workers
import the application after ``fork()`` (``preload_app`` is left at its
default of False), so each worker opens its own Mongo connections on
first use — no parent-inherited sockets to clean up.
"""
# Gunicorn reads these module-level names as setting names — they are not
# Python constants and must stay lower-case.
# pylint: disable=invalid-name

bind = "0.0.0.0:9090"
workers = 2
threads = 2
accesslog = "-"
errorlog = "-"
