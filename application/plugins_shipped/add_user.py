#!/usr/bin/env python3
"""
Generate User
"""
from mongoengine.errors import DoesNotExist
import click
import secrets
import string
from application import app
from application.models.user import User


@app.cli.command('sys_create_user')
@click.argument("email")
def seed_user(email):
    """Generate new user"""

    try:
        user = User.objects.get(email=email)
    except DoesNotExist:
       user = User()
       user.email = email

    alphabet = string.ascii_letters + string.digits
    passwd = ''.join(secrets.choice(alphabet) for i in range(20))
    user.set_password(passwd)
    user.global_admin = True
    user.tfa_secret = None
    user.disable = False
    user.save()
    print(f"User passwort set to: {passwd}")
