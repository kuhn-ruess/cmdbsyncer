"""
Helper to get Account
"""
from application.models.account import Account
from mongoengine.errors import DoesNotExist


def get_account_by_name(name):
    """
    Get Account by Name or Return False
    """

    try:
        return dict(Account.objects.get(name=name, enabled=True).to_mongo())
    except DoesNotExist:
        return False
