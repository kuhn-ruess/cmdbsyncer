"""
Interactive Syncer Shell

Opens a REPL that dispatches directly into the registered Flask CLI commands
of the CMDB Syncer, with history and tab-completion — similar in spirit to
modern interactive coding shells, but scoped to `flask ...` subcommands.
"""
import os
import re
import json
import shlex
import atexit

import click

from application import app
from application.modules.debug import ColorCodes as CC
from application.models.account import Account


HISTORY_FILE = os.path.expanduser("~/.cmdbsyncer_shell_history")
BUILTINS = {"help", "?", "exit", "quit", ":q"}

_GROUP_RE = re.compile(
    r"app\.cli\.group\(\s*name\s*=\s*['\"]([^'\"]+)['\"]"
    r"|register_cli_group\(\s*app\s*,\s*['\"]([^'\"]+)['\"]"
)


def _scan_plugin_groups():
    """
    Walk plugin directories, locate plugin.json files (with `ident`), and grep
    sibling .py files for ``app.cli.group(name=...)`` to map a top-level CLI
    group name (e.g. ``checkmk``) to its account type ident (e.g. ``cmkv2``).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    plugin_dirs = [
        os.path.join(base_dir, 'plugins'),
        os.path.join(base_dir, 'application', 'plugins'),
    ]
    mapping = {}
    for plugin_dir in plugin_dirs:
        if not os.path.isdir(plugin_dir):
            continue
        for root, _dirs, files in os.walk(plugin_dir):
            if 'plugin.json' not in files:
                continue
            try:
                with open(os.path.join(root, 'plugin.json'), encoding='utf-8') as f:
                    data = json.load(f)
                ident = data.get('ident')
            except (OSError, json.JSONDecodeError):
                continue
            if not ident:
                continue
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                try:
                    with open(os.path.join(root, fname), encoding='utf-8') as f:
                        for line in f:
                            match = _GROUP_RE.search(line)
                            if match:
                                group_name = match.group(1) or match.group(2)
                                mapping.setdefault(group_name, ident)
                except OSError:
                    continue
    return mapping


def _resolve_click_command(tokens):
    """
    Walk ``app.cli`` according to ``tokens``. Return ``(cmd, depth_used)``
    where ``depth_used`` is how many tokens were consumed to reach ``cmd``.
    """
    cmd = app.cli
    depth = 0
    for tok in tokens:
        if isinstance(cmd, click.Group) and tok in cmd.commands:
            cmd = cmd.commands[tok]
            depth += 1
        else:
            break
    return cmd, depth


def _account_names(wanted_type):
    try:
        if wanted_type:
            qs = Account.objects(enabled=True, type=wanted_type)
        else:
            qs = Account.objects(enabled=True)
        return sorted(a.name for a in qs)
    except Exception:  # pylint: disable=broad-exception-caught
        return []


def _completions_for(line, text, group_to_type):  # pylint: disable=too-many-locals
    """
    Position-aware completion. Returns a list of full token candidates that
    start with ``text``.
    """
    try:
        tokens = shlex.split(line, posix=True)
    except ValueError:
        tokens = line.split()

    starting_new = line == '' or line[-1].isspace()
    if starting_new:
        current_idx = len(tokens)
        current_text = ''
    else:
        current_idx = max(0, len(tokens) - 1)
        current_text = tokens[-1] if tokens else ''

    if text and not current_text.endswith(text):
        current_text = text

    preceding = tokens[:current_idx]
    cmd, depth = _resolve_click_command(preceding)

    if isinstance(cmd, click.Group):
        options = list(cmd.commands.keys())
        if depth == 0:
            options += list(BUILTINS)
        return sorted(o for o in options if o.startswith(current_text))

    arg_index = current_idx - depth
    arg_params = [p for p in cmd.params if isinstance(p, click.Argument)]
    if arg_index < 0 or arg_index >= len(arg_params):
        return []

    param = arg_params[arg_index]
    if param.name and 'account' in param.name.lower():
        top_group = preceding[0] if preceding else None
        wanted_type = group_to_type.get(top_group)
        return [n for n in _account_names(wanted_type) if n.startswith(current_text)]
    return []


def _setup_readline(group_to_type):
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
        matches = _completions_for(line, text, group_to_type)
        try:
            return matches[state]
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
    click.echo("Tab completes commands and account-name arguments "
               "(filtered by the plugin's account type).")
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
    group_to_type = _scan_plugin_groups()
    _setup_readline(group_to_type)

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
