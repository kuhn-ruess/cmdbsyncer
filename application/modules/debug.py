#!/usr/bin/env python3
"""
Debug Helpers
"""

from rich.console import Console
from rich.table import Table
from rich import box

def attribute_table(title, data):
    """
    Write a nice Table
    """
    table = Table(title=title, box=box.ASCII_DOUBLE_HEAD, header_style="bold blue", title_style="yellow")
    table.add_column("Attribute Name", style="cyan")
    table.add_column("Attribute Value", style="magenta")
    for key, value in data.items():
        table.add_row(key, str(value))

    console = Console()
    console.print(table)
    print()


class ColorCodes(): #pylint: disable=too-few-public-methods
    """
    Color Defentions (found in Stack Overflow)
    https://stackoverflow.com/questions/287871/how-do-i-print-colored-text-to-the-terminal
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

def debug(debug_mode, text):
    """
    Simple Debug Print wrapper
    """
    if debug_mode:
        print(f"{ColorCodes.WARNING} * {ColorCodes.ENDC} {text}")
