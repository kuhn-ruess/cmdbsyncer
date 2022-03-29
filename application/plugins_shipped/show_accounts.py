#!/usr/bin/env python3
"""
Show all Accounts
"""
from application import app
from application.models.account import Account


@app.cli.command('show_accounts')
def show_accounts():
    """Print list of all active accounts"""

    for account in Account.objects(enabled=True):
        print(f"- Name: {account.name}, Type: {account.typ}, Address: {account.address}")
