"""
Interactive Syncer Shell

Opens a REPL that dispatches directly into the registered Flask CLI commands
of the CMDB Syncer, with history and tab-completion — similar in spirit to
modern interactive coding shells, but scoped to `flask ...` subcommands.
"""
import os
import shlex
import atexit

import click

from application import app
from application.modules.debug import ColorCodes as CC


HISTORY_FILE = os.path.expanduser("~/.cmdbsyncer_shell_history")
BUILTINS = {"help", "?", "exit", "quit", ":q"}


def _iter_command_paths(cmd, prefix=()):
    """
    Yield tuples of command-path tokens for every leaf command and every
    intermediate group reachable from `cmd`.
    """
    if isinstance(cmd, click.Group):
        for name in sorted(cmd.commands):
            sub = cmd.commands[name]
            path = prefix + (name,)
            yield path
            yield from _iter_command_paths(sub, path)


def _collect_completions():
    """
    Build a flat list of command invocations like
    ``["cron list_jobs", "rules export_rules", ...]`` used for tab-completion.
    """
    paths = []
    for name, sub in sorted(app.cli.commands.items()):
        paths.append((name,))
        if isinstance(sub, click.Group):
            for p in _iter_command_paths(sub, (name,)):
                paths.append(p)
    return [" ".join(p) for p in paths] + sorted(BUILTINS)


def _setup_readline(completions):
    try:
        import readline  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None

    if os.path.exists(HISTORY_FILE):
        try:
            readline.read_history_file(HISTORY_FILE)
        except OSError:
            pass
    readline.set_history_length(1000)
    atexit.register(lambda: _safe_write_history(readline))

    def completer(text, state):
        line = readline.get_line_buffer()
        matches = [c for c in completions if c.startswith(line)]
        remainders = []
        for m in matches:
            tail = m[len(line) - len(text):]
            remainders.append(tail)
        try:
            return remainders[state]
        except IndexError:
            return None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    return readline


def _safe_write_history(readline_mod):
    try:
        readline_mod.write_history_file(HISTORY_FILE)
    except OSError:
        pass


def _print_help():
    click.echo(f"{CC.HEADER}CMDB Syncer Shell{CC.ENDC}")
    click.echo("Type a syncer command without the leading 'flask', e.g.:")
    click.echo("  rules export_all_rules")
    click.echo("  cron list_jobs")
    click.echo("Built-ins: help, exit (Ctrl-D also exits)")
    click.echo("Available top-level groups/commands:")
    for name in sorted(app.cli.commands):
        obj = app.cli.commands[name]
        kind = "group" if isinstance(obj, click.Group) else "cmd"
        short = (obj.help or obj.short_help or "").strip().splitlines()[0:1]
        short = short[0] if short else ""
        click.echo(f"  {CC.OKBLUE}{name:<24}{CC.ENDC} [{kind}] {short}")


def _dispatch(line):
    try:
        argv = shlex.split(line)
    except ValueError as exc:
        click.echo(f"{CC.FAIL}Parse error:{CC.ENDC} {exc}")
        return
    if not argv:
        return
    try:
        app.cli.main(
            args=argv,
            prog_name="flask",
            standalone_mode=False,
        )
    except click.exceptions.UsageError as exc:
        click.echo(f"{CC.FAIL}Usage:{CC.ENDC} {exc.format_message()}")
    except click.exceptions.Abort:
        click.echo("Aborted.")
    except SystemExit:
        pass
    except Exception as exc:  # pylint: disable=broad-exception-caught
        click.echo(f"{CC.FAIL}Error:{CC.ENDC} {exc}")


@app.cli.command("cli")
def cli_syncer_shell():
    """
    Open an interactive REPL for syncer commands (history + tab-completion).
    """
    completions = _collect_completions()
    _setup_readline(completions)

    click.echo(f"{CC.OKGREEN}CMDB Syncer interactive shell{CC.ENDC} "
               f"— type 'help' or 'exit'.")

    while True:
        try:
            line = input("syncer> ").strip()
        except EOFError:
            click.echo()
            break
        except KeyboardInterrupt:
            click.echo("^C")
            continue

        if not line:
            continue
        if line in ("exit", "quit", ":q"):
            break
        if line in ("help", "?"):
            _print_help()
            continue

        _dispatch(line)
