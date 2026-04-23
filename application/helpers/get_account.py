"""
Helper to get Account
"""
from mongoengine.errors import DoesNotExist
from application.enterprise import has_feature, run_hook
from application.models.account import Account


class AccountNotFoundError(Exception):
    """
    Raise if Account not found
    """


def _resolve_password(account):
    """
    Fetch the account password, optionally via the enterprise secrets
    manager. The hook returns `None` for unbound accounts, which lets us
    fall back to the local encrypted password transparently. Community
    installs never see the feature because the hook is not registered.
    """
    if has_feature('secrets_manager'):
        resolved = run_hook('resolve_secret', account)
        if resolved is not None:
            return resolved
    return account.get_password()


def get_account_by_name(name, is_id=False):  # pylint: disable=too-many-branches
    """
    Get Account by Name or Return False
    """

    parent_account = {}
    try:
        if is_id:
            account = Account.objects.get(id=name, enabled=True)
        else:
            account = Account.objects.get(name=name, enabled=True)

        account_data = dict(account.to_mongo())

        if account.is_child:
            parent_account = get_account_by_name(account.parent.id, is_id=True)
            account_data['is_child'] = True

            # make sure to not use the following fields from the child
            for what in ['typ', 'username', 'password', 'address',
                         'object_type',
                        ]:
                if what in account_data:
                    del account_data[what]

        else:
            account_data['password'] = _resolve_password(account)

        for field, value  in [(x['name'], x.get('value')) for x in account_data['custom_fields']]:
            if not value:
                value = False
            elif value in ('True', 'true'):
                value = True
            elif value in ('False', 'false'):
                value = False
            account_data[field] = value

        account_data['settings'] = {}
        for plugin, object_filter  in [(x['plugin'],
                                        x.get('object_filter'))
                                       for x in account_data['plugin_settings']]:
            account_data['settings'][plugin] = {}
            account_data['settings'][plugin]['filter'] = object_filter

        account_data['id'] = str(account_data['_id'])
        account_data['ref'] = account_data['_id']

        if parent_account:
            # A Parent Account is the base, but the child
            # overwrites it. Account_data is in this case the child
            parent_account.update(account_data)
            account_data = parent_account

        # cleanup 2
        for what in ['custom_fields', 'password_crypted',
                     'plugin_settings']:
            if what in account_data:
                del account_data[what]

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
