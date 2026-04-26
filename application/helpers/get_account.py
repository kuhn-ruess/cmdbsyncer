"""
Helper to get Account
"""
import copy

from mongoengine import signals
from mongoengine.errors import DoesNotExist

from application.enterprise import has_feature, run_hook
from application.models.account import Account


# String values in custom_fields that should round-trip as real booleans.
_BOOL_TRUE = {'True', 'true'}
_BOOL_FALSE = {'False', 'false'}

# Fields the child must keep — the parent's value never wins for these.
_CHILD_OWNED_FIELDS = ('typ', 'username', 'password', 'address', 'object_type')

# Internal serialisation artefacts that never leave this layer.
_INTERNAL_FIELDS = ('custom_fields', 'password_crypted', 'plugin_settings')

# In-process cache: ``{(lookup_key, is_id): account_dict}``. Sync runs read
# the same handful of accounts for every host/rule, so caching keeps Mongo
# and the secrets-manager hook off the hot path. Invalidated on Account
# save/delete via mongoengine signals so the web app picks up edits
# without a process restart.
_account_cache = {}


class AccountNotFoundError(Exception):
    """
    Raise if Account not found
    """


def clear_account_cache(*_args, **_kwargs):
    """Drop all cached account dicts. Wired to Account save/delete."""
    _account_cache.clear()


signals.post_save.connect(clear_account_cache, sender=Account)
signals.post_delete.connect(clear_account_cache, sender=Account)


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


def _coerce_custom_value(value):
    """Treat falsy / 'true' / 'false' strings as actual booleans."""
    if not value:
        return False
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    return value


def _flatten_account(account):
    """Project a Mongo Account document into a flat dict for callers."""
    data = dict(account.to_mongo())
    for entry in data.get('custom_fields', []):
        data[entry['name']] = _coerce_custom_value(entry.get('value'))
    data['settings'] = {
        entry['plugin']: {'filter': entry.get('object_filter')}
        for entry in data.get('plugin_settings', [])
    }
    data['id'] = str(data['_id'])
    data['ref'] = data['_id']
    for field in _INTERNAL_FIELDS:
        data.pop(field, None)
    return data


def _build_account_dict(name, is_id):
    """Resolve and compose the dict — without consulting the cache."""
    lookup = {'id': name} if is_id else {'name': name}
    try:
        account = Account.objects.get(enabled=True, **lookup)
    except DoesNotExist as exc:
        raise AccountNotFoundError("Account not found") from exc

    if not account.is_child:
        data = _flatten_account(account)
        data['password'] = _resolve_password(account)
        return data

    # Child: parent is the base, child overrides where it set a value —
    # except for the child-owned fields, which the parent must not shadow.
    child_data = _flatten_account(account)
    for field in _CHILD_OWNED_FIELDS:
        child_data.pop(field, None)
    child_data['is_child'] = True
    parent_data = get_account_by_name(account.parent.id, is_id=True)
    parent_data.update(child_data)
    return parent_data


def get_account_by_name(name, is_id=False):
    """
    Get Account by Name or Return False
    """
    cache_key = (str(name), is_id)
    cached = _account_cache.get(cache_key)
    if cached is None:
        cached = _build_account_dict(name, is_id)
        _account_cache[cache_key] = cached
    # Defensive copy — callers must not mutate the cached entry.
    return copy.deepcopy(cached)


def get_account_variable(macro):
    """
    Replaces the given Macro with the Account data
    Example: {{ACCOUNT:mon:password}}
    """
    try:
        _, account, var = macro.split(':')
        return get_account_by_name(account)[var.removesuffix('}}')]
    except (ValueError, KeyError, AccountNotFoundError) as exc:
        raise ValueError("Account Variable not found") from exc
