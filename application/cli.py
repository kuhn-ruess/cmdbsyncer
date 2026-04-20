"""Entry point for the ``cmdbsyncer`` console script.

Registered via ``[project.scripts]`` in ``pyproject.toml`` so the command is
available on ``PATH`` after ``pip install cmdbsyncer``. Delegates to Flask's
Click CLI on the app instance.
"""
import os
import sys
import warnings


def main():
    """Run the cmdbsyncer Flask Click CLI."""
    os.environ.setdefault("config", "prod")
    # cmdbsyncer expects to be run from a working directory that contains
    # ``local_config.py``; in source checkouts that file is next to
    # ``./cmdbsyncer``, so cwd is already on sys.path. PyPI console scripts do
    # not add cwd automatically — inject it so ``from local_config import ...``
    # works the same in both layouts.
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Fields missing from ruleset", UserWarning)
        try:
            from application import app, VERSION  # pylint: disable=import-outside-toplevel
            from flask.cli import ScriptInfo  # pylint: disable=import-outside-toplevel
        except Exception as exp:  # pylint: disable=broad-except
            print("Cannot load application. Is MongoDB reachable and local_config.py present?")
            print(exp)
            sys.exit(1)

        if len(sys.argv) == 1:
            print(f"CMDB Syncer Version: {VERSION}")
            return
        # AppGroup commands re-resolve the app via ScriptInfo.load_app(), which
        # otherwise scans for FLASK_APP / app.py / wsgi.py. PyPI installs have
        # none of those in the cwd, so hand Click a ScriptInfo that returns the
        # already-imported app instance directly.
        app.cli(obj=ScriptInfo(create_app=lambda: app))


if __name__ == "__main__":
    main()
