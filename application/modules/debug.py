#!/usr/bin/env python3
"""
Debug Helpers
"""
from pprint import pformat

from rich.console import Console
from rich.table import Table
from rich import box


def attribute_table(title, data):
    """
    Print nice looking Debug  Table

    Args:
        title (string): Title of Table
        data (dict): Key Value Pairs
    """
    table = Table(title=title, box=box.ASCII_DOUBLE_HEAD,
                    header_style="bold blue", title_style="yellow", width=90)
    table.add_column("Attribute Name", style="cyan")
    table.add_column("Attribute Value", style="magenta")
    for key, value in data.items():
        table.add_row(key, pformat(value)[:10000])

    console = Console()
    console.print(table)
    print()


class ColorCodes():  # pylint: disable=too-few-public-methods
    """
    Color Definitions

    Methods:
        - HEADER: Print Header
        - OKBLUE: Blue Color
        - OKGREEN: Green Color
        - OKCYAN: Cyan Color
        - WARNING: Warning
        - FAIL: Failure
        - BOLD: Bold
        - UNDERLINE: Underline
        - ENDC: End String

    """
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def apply_debug_rules(syncer, rules):
    """Enable debug mode on syncer and all its rule objects."""
    syncer.debug = True
    if rules.get('filter'):
        rules['filter'].debug = True
    syncer.filter = rules.get('filter', False)
    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']
    rules['actions'].debug = True
    syncer.actions = rules['actions']


def clear_host_debug_cache(hostname, prefix):
    """Load a host, clear its debug-relevant cache entries, and return it.

    Returns the Host object or None if not found.
    """
    from mongoengine.errors import DoesNotExist  # pylint: disable=import-outside-toplevel
    from application.models.host import Host  # pylint: disable=import-outside-toplevel
    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return None
    for key in list(db_host.cache.keys()):
        if key.lower().startswith(prefix):
            del db_host.cache[key]
    if 'CustomAttributeRule' in db_host.cache:
        del db_host.cache['CustomAttributeRule']
    db_host.save()
    return db_host


def debug(debug_mode, text):
    """
    Debug Print Wrapper

    Args:
       debug_mode (bool): Defines if the ouput should be printed
       text (string): Output Text
    """
    if debug_mode:
        print(f"{ColorCodes.WARNING} * {ColorCodes.ENDC} {text}")
