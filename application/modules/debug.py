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


class ColorCodes(): #pylint: disable=too-few-public-methods
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

def debug(debug_mode, text):
    """
    Debug Print Wrapper

    Args:
       debug_mode (bool): Defines if the ouput should be printed
       text (string): Output Text
    """
    if debug_mode:
        print(f"{ColorCodes.WARNING} * {ColorCodes.ENDC} {text}")
