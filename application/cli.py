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
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Fields missing from ruleset", UserWarning)
        try:
            from application import app, VERSION  # pylint: disable=import-outside-toplevel
        except Exception as exp:  # pylint: disable=broad-except
            print("Cannot load application. Is MongoDB reachable and local_config.py present?")
            print(exp)
            sys.exit(1)

        if len(sys.argv) == 1:
            print(f"CMDB Syncer Version: {VERSION}")
            return
        app.cli()


if __name__ == "__main__":
    main()
