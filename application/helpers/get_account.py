"""
Helper to get Account
"""
from mongoengine.errors import DoesNotExist
from application.models.account import Account


class AccountNotFoundError(Exception):
    """
    Raise if Account not found
    """


def get_account_by_name(name, is_id=False):
    """
    Get Account by Name or Return False
    """

    account_data = {}
    try:

        if is_id:
            account = dict(Account.objects.get(id=name, enabled=True).to_mongo())
        else:
            account = dict(Account.objects.get(name=name, enabled=True).to_mongo())

        if account['is_child']:
            account_data = get_account_by_name(account['parent'], is_id=True)
            account_data['is_child'] = True
        else:
            account_data = account

        for field, value  in [(x['name'], x.get('value')) for x in account['custom_fields']]:
            if not value:
                value = False
            account_data[field] = value
        account_data['settings'] = {}
        for plugin, object_filter  in [(x['plugin'],
                                        x.get('object_filter'))
                                       for x in account['plugin_settings']]:
            account_data['settings'][plugin] = {}
            account_data['settings'][plugin]['filter'] = object_filter


        account_data['id'] = str(account['_id'])
        account_data['ref'] = account['_id']
        return account_data
    except DoesNotExist as exc:
        raise AccountNotFoundError("Account not found") from exc

def get_account_variable(macro):
    """
    Replaces the given Macro with the Account data
    Example: {{ACCOUNT:mon:password}}
    """
    # @TODO: Cache
    _, account, var = macro.split(':')
    try:
        return get_account_by_name(account)[var[:-2]]
    except Exception as exc:
        raise ValueError("Account Variable not found") from exc
