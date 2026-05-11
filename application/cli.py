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
    # cmdbsyncer needs to find ``local_config.py`` regardless of the
    # caller's cwd. Source checkouts have it next to ``./cmdbsyncer`` and
    # were always covered by the cwd injection below; PyPI installs (and
    # any cron / systemd unit that doesn't set WorkingDirectory) drop it
    # into the install root (e.g. ``/opt/cmdbsyncer/``) but invoke the
    # binary from elsewhere — that previously left ``CRYPTOGRAPHY_KEY``
    # at ``None`` and exploded much later with a "Fernet(None)" TypeError
    # that pointed nowhere useful. Search a fixed list of well-known
    # directories and inject the first one that actually contains the
    # file; cwd stays in the list so source checkouts still win.
    _config_candidates = []
    if env_dir := os.environ.get("CMDBSYNCER_CONFIG_DIR"):
        _config_candidates.append(env_dir)
    _config_candidates.append(os.getcwd())
    # ``sys.prefix`` is the venv root (``/opt/cmdbsyncer/venv``); its
    # parent is the conventional install dir where local_config.py sits.
    _config_candidates.append(os.path.dirname(sys.prefix))
    _config_candidates.append("/etc/cmdbsyncer")
    for _candidate in _config_candidates:
        if _candidate and os.path.isfile(os.path.join(_candidate, "local_config.py")):
            if _candidate not in sys.path:
                sys.path.insert(0, _candidate)
            break
    else:
        # Nothing found. Keep the legacy cwd injection so the import
        # still attempts and the warning in ``application/__init__.py``
        # surfaces the searched paths — but tell the operator upfront.
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        print(
            "cmdbsyncer: local_config.py not found in any of "
            f"{_config_candidates!r}. Set CMDBSYNCER_CONFIG_DIR to "
            "its directory or run from there. Continuing — encrypted "
            "account passwords will fail to decrypt without "
            "CRYPTOGRAPHY_KEY.",
            file=sys.stderr,
        )
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
