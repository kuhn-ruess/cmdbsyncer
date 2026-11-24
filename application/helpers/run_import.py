"""
Run Import: one job for every source account. The role of the account
decides whether its plugin imports or inventorizes, the account type
which plugin it is.
"""
import inspect

from application import cron_register
from application.helpers.cron import import_register
from application.helpers.get_account import get_account_by_name
from application.models.account import object_types

RUN_IMPORT_JOB = 'Run Import (defined by Account)'


class RunImportError(ValueError):
    """The account can not be used with Run Import"""


def account_import_settings(account):
    """
    Type, role and import variant of an Account document, a child
    account takes type and variant of its parent where it has none.
    """
    parent = account.parent if account.is_child else None
    return {
        'name': account.name,
        'typ': account.type or (parent.type if parent else None),
        'restrict_to': account.restrict_to or '',
        'import_variant': account.import_variant
                          or (parent.import_variant if parent else '') or '',
    }


def creates(account):
    """
    What a job importing with the Account document puts into the syncer,
    for the cron group list: the job name says hosts or objects, the
    account decides it.
    """
    role = account.restrict_to or ''
    if role == 'inventorize':
        return 'inventory'
    if role == 'export':
        return 'nothing, export target'
    if not account.is_object:
        return 'hosts'
    kind = dict(object_types).get(account.object_type)
    return f'objects: {kind}' if kind and account.object_type != 'auto' else 'objects'


def is_import_job(command):
    """Whether the cron command imports or inventorizes with its account"""
    if command == RUN_IMPORT_JOB:
        return True
    function = cron_register.get(command)
    return any(function in (entry['import'], entry['inventorize'])
               for variants in import_register.values()
               for entry in variants.values())


def operation_of(settings):
    """'inventorize' for an additional source, 'import' otherwise"""
    return 'inventorize' if settings.get('restrict_to') == 'inventorize' else 'import'


def _variant_entry(settings):
    """The registered entry the variant of the account points to"""
    account_type = settings.get('typ')
    variants = import_register.get(account_type)
    if not variants:
        raise RunImportError(
            f"Account {settings['name']}: accounts of type {account_type} "
            "can not be used with Run Import, use the job of the plugin")
    variant = settings.get('import_variant') or next(iter(variants))
    if variant not in variants:
        raise RunImportError(
            f"Account {settings['name']}: Import from '{variant}' does not "
            f"exist for accounts of type {account_type}")
    return variants[variant]


def import_function(settings):
    """
    The function Run Import starts for the account, raises
    RunImportError when there is none
    """
    if settings.get('restrict_to') == 'export':
        raise RunImportError(
            f"Account {settings['name']} is an export target, it does not "
            "import or inventorize")
    entry = _variant_entry(settings)
    operation = operation_of(settings)
    function = entry[operation]
    if not function:
        other = 'Main source' if operation == 'inventorize' else 'Additional source'
        raise RunImportError(
            f"Account {settings['name']}: {entry['label'] or settings['typ']} "
            f"can not {operation}, set the role of the account to {other}")
    return function


def variant_problem(account_type, variant):
    """Why the import variant does not fit the account type, or None"""
    if not variant:
        return None
    if variant not in import_register.get(account_type, {}):
        return (f"Import from '{variant}' does not exist for accounts "
                f"of type {account_type}")
    return None


def variant_choices(account_type=None):
    """
    Choices of the Import from field: the variants of the account type,
    of all types when it is not known yet. Only the default when the
    type has no variants.
    """
    types = [account_type] if account_type else sorted(import_register)
    choices = {}
    default = 'Default'
    for typ in types:
        variants = import_register.get(typ, {})
        if len(variants) < 2:
            continue
        if account_type:
            default = f"Default ({next(iter(variants.values()))['label']})"
        for key, entry in variants.items():
            choices.setdefault(key, entry['label'])
    return [('', default)] + list(choices.items())


def run_import(account=None, debug=False):
    """
    Import or inventorize with the account, as its role says
    """
    if not account:
        raise RunImportError(f"{RUN_IMPORT_JOB} needs an account")
    function = import_function(get_account_by_name(account))
    if 'debug' in inspect.signature(function).parameters:
        function(account=account, debug=debug)
    else:
        function(account=account)
