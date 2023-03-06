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
        account_dict = dict(Account.objects.get(name=name, enabled=True).to_mongo())
        for field, value  in [(x['name'], x['value']) for x in account_dict['custom_fields']]:
            account_dict[field] = value
        return account_dict
        account_dict['id'] = str(account_dict['_id'])
    except DoesNotExist:
        return False
