"""
Run the real `application` package against a scratch local_config.py.

The package-level test bootstrap stubs `application` out in `sys.modules`,
so a test that needs the genuine import-time ordering — the config merge,
the logging pipeline, everything derived from the merged config — has to
import it in a subprocess instead. More than one test module does, so the
runner lives here once.
"""
import os
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_with_local_config(local_config, snippet, extra_files=None):
    """
    Write `local_config` into a scratch directory, import `application`
    from there and run `snippet`. `{workdir}` is substituted with the
    scratch path in both, and in every file of `extra_files` (a mapping of
    relative path to content, for stub packages the import has to find).
    Returns the CompletedProcess.

    The scratch directory is also the working directory: the repo root
    usually carries its own `local_config.py`, and cwd wins on sys.path.
    """
    with tempfile.TemporaryDirectory() as workdir:
        with open(os.path.join(workdir, "local_config.py"), "w",
                  encoding="utf-8") as config_file:
            config_file.write(local_config.replace("{workdir}", workdir))
        for relative_path, content in (extra_files or {}).items():
            target = os.path.join(workdir, relative_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as extra_file:
                extra_file.write(content.replace("{workdir}", workdir))
        env = dict(os.environ)
        env["PYTHONPATH"] = _REPO_ROOT
        # CLI mode keeps the import light — no blueprints, no Flask-Admin
        # scaffolding, and therefore no live MongoDB needed.
        env["CMDBSYNCER_CLI"] = "1"
        env["CMDBSYNCER_CONFIG_DIR"] = workdir
        return subprocess.run(
            [sys.executable, "-c", snippet.replace("{workdir}", workdir)],
            cwd=workdir, env=env, capture_output=True, text=True, check=False,
        )
