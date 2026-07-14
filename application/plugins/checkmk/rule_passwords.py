"""
Bridge Checkmk rule secrets to the syncer's own Checkmk password store.

Checkmk masks an ``explicit_password`` in a rule value as ``******`` on every
read, so a rule imported from one Checkmk instance carries no usable secret and
would overwrite the target's password with ``******`` on deploy. Instead we
rewrite every ``explicit_password`` into a ``stored_password`` reference backed
by a syncer :class:`CheckmkPassword`. The reference is a Jinja macro
``{{ cmk_password("name") }}`` that resolves to the entry's stable ident
``cmdbsyncer_<id>`` at export time — the same ident the password export writes
into every Checkmk instance, so a rule deployed to test and prod resolves each
instance's own stored secret.
"""
import ast
import re

from application import logger

# Checkmk 2.3+ tags password values in a rule's ``value_raw`` as
# ``('cmk_postprocessed', <kind>, (<ident>, <value>))``. ``explicit_password``
# inlines the (masked) secret; ``stored_password`` only references a password
# store ident and carries no secret.
POSTPROCESSED = 'cmk_postprocessed'
EXPLICIT_PASSWORD = 'explicit_password'
STORED_PASSWORD = 'stored_password'

# ``{{ cmk_password("name") }}`` — tolerant of surrounding whitespace and either
# quote style, matching how the macro may be hand-edited on the rule.
_MACRO_RE = re.compile(r'\{\{\s*cmk_password\([^)]*\)\s*\}\}')
_MACRO_NAME_RE = re.compile(r'cmk_password\(\s*["\']([^"\']+)["\']\s*\)')


def password_ident(name):
    """
    Resolve a syncer password name to its Checkmk password-store ident.

    Returns ``cmdbsyncer_<id>`` for the :class:`CheckmkPassword` named ``name``.
    A missing name is logged and resolved to a clearly-invalid ident so only the
    one affected rule fails to deploy (Checkmk rejects the unknown reference)
    instead of aborting the whole export.
    """
    from .models import CheckmkPassword  # pylint: disable=import-outside-toplevel
    entry = CheckmkPassword.objects(name=name).first()
    if not entry:
        logger.error(
            "cmk_password(%r): no Checkmk Password with that name in the syncer",
            name)
        return f"cmdbsyncer_missing_{name}"
    return f"cmdbsyncer_{entry.id}"


def _macro_for(hint):
    """Build the ``{{ cmk_password(...) }}`` macro for a default name hint."""
    return '{{ cmk_password("%s") }}' % (hint or 'password')


def rewrite_explicit_passwords(value_raw):
    """
    Rewrite every ``explicit_password`` in a rule ``value_raw`` string into a
    ``stored_password`` password-store reference.

    Each ``('cmk_postprocessed', 'explicit_password', (<uuid>, '******'))``
    becomes ``('cmk_postprocessed', 'stored_password', ('{{ cmk_password("<hint>") }}', ''))``
    where ``<hint>`` defaults to the value's field name (e.g. ``secret``). The
    hint is only a starting name — rename the macro on the rule and create a
    matching syncer Checkmk Password.

    Returns ``(new_value_raw, hints)`` where ``hints`` is the list of default
    names inserted (empty, and ``value_raw`` returned unchanged, when the value
    holds no explicit password or cannot be parsed).
    """
    if not isinstance(value_raw, str) or EXPLICIT_PASSWORD not in value_raw:
        return value_raw, []
    try:
        parsed = ast.literal_eval(value_raw)
    except (ValueError, SyntaxError):
        return value_raw, []

    hints = []

    def convert(obj, key=None):
        if isinstance(obj, tuple):
            if len(obj) == 3 and obj[0] == POSTPROCESSED \
                    and obj[1] == EXPLICIT_PASSWORD:
                hint = key if isinstance(key, str) and key else 'password'
                hints.append(hint)
                return (POSTPROCESSED, STORED_PASSWORD, (_macro_for(hint), ''))
            return tuple(convert(item, key) for item in obj)
        if isinstance(obj, list):
            return [convert(item, key) for item in obj]
        if isinstance(obj, dict):
            return {k: convert(v, k) for k, v in obj.items()}
        return obj

    new = convert(parsed)
    if not hints:
        return value_raw, []
    return repr(new), hints


def preserve_password_macros(old_value, new_value):
    """
    Carry a rule's existing ``cmk_password`` macros over into a freshly
    re-imported value, so a re-run of the folder import does not revert a
    renamed macro back to its default hint.

    Positional: when ``old_value`` and ``new_value`` hold the same number of
    macros (the usual case — the rule's password fields did not change), the
    i-th new macro is replaced by the i-th old one. On any mismatch the new
    value is kept unchanged.
    """
    if not old_value:
        return new_value
    old_macros = _MACRO_RE.findall(old_value)
    new_macros = _MACRO_RE.findall(new_value)
    if not old_macros or len(old_macros) != len(new_macros):
        return new_value
    carried = iter(old_macros)
    return _MACRO_RE.sub(lambda _match: next(carried), new_value)


def referenced_password_names(text):
    """Return the set of syncer password names a value references via macro."""
    if not text:
        return set()
    return set(_MACRO_NAME_RE.findall(text))
