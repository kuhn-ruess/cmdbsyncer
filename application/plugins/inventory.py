"""
CLI front-end for the cross-module inventory provider registry.

`cmdbsyncer inventory ansible <provider>` honors the standard Ansible
inventory-script contract (`--list`, `--host=NAME`) so it can be wired
straight into `ansible-playbook -i …` or used as the local-mode backend
of the cmdbsyncer-inventory plugin. The same render function backs the
HTTP endpoint at `/api/v1/inventory/ansible/<provider>` — only the
transport differs.
"""
import json
import sys

import click

from application import app
from application.modules.inventory import (
    list_inventory_providers,
    render_ansible_inventory,
)


@app.cli.group(name='inventory')
def cli_inventory():
    """Cross-module inventory provider front-end"""


@cli_inventory.command(name='list-providers')
def cli_list_providers():
    """Print every registered provider name, one per line."""
    for name in list_inventory_providers():
        print(name)


@cli_inventory.command(name='ansible')
@click.argument('provider')
@click.option('--list', 'show_list', is_flag=True,
              help='Emit the full inventory (Ansible script contract).')
@click.option('--host', default=None,
              help="Emit a single host's vars dict (Ansible script contract).")
def cli_ansible_inventory(provider, show_list, host):
    """
    Render PROVIDER's inventory as Ansible JSON to stdout.

    The same function backs `/api/v1/inventory/ansible/<provider>`, so a
    cmdbsyncer-inventory plugin in local mode (which shells out to this
    command) and one in HTTP mode see identical data.
    """
    if host:
        result = render_ansible_inventory(provider, host=host)
        if result is None:
            click.echo(f"Unknown provider: {provider}", err=True)
            sys.exit(1)
        if result is False:
            click.echo(f"Host not found: {host}", err=True)
            sys.exit(1)
        print(json.dumps(result))
        return
    if show_list:
        result = render_ansible_inventory(provider)
        if result is None:
            click.echo(f"Unknown provider: {provider}", err=True)
            sys.exit(1)
        print(json.dumps(result))
        return
    click.echo("Pass --list or --host=NAME (Ansible script contract).", err=True)
    sys.exit(2)
