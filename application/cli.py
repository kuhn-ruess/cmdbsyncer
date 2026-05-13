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
    # Mark the process as a CLI invocation before importing the app factory.
    # ``application/__init__.py`` and ``application/enterprise.py`` check this
    # to suppress their startup banner / ECS JSON log pipeline — none of that
    # noise belongs in front of command output like ``checkmk export_hosts``.
    os.environ["CMDBSYNCER_CLI"] = "1"
    # ``application/__init__.py`` resolves the local_config.py location at
    # *import* time (it must, because the import line further down runs
    # before this function does). Nothing to do here.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Fields missing from ruleset", UserWarning)
        try:
            from application import app, DISPLAY_VERSION  # pylint: disable=import-outside-toplevel
            from flask.cli import ScriptInfo  # pylint: disable=import-outside-toplevel
        except Exception as exp:  # pylint: disable=broad-except
            print("Cannot load application. Is MongoDB reachable and local_config.py present?")
            print(exp)
            sys.exit(1)

        if len(sys.argv) == 1:
            print(f"CMDB Syncer Version: {DISPLAY_VERSION}")
            sys.argv.append("--help")
        # AppGroup commands re-resolve the app via ScriptInfo.load_app(), which
        # otherwise scans for FLASK_APP / app.py / wsgi.py. PyPI installs have
        # none of those in the cwd, so hand Click a ScriptInfo that returns the
        # already-imported app instance directly.
        app.cli(obj=ScriptInfo(create_app=lambda: app))


if __name__ == "__main__":
    main()
