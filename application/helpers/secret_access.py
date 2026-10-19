"""
Who may see, bind and read which Secret Store entries.

Every path that lists, edits, binds or reveals an entry (web views, the
import, Jinja rendering inside a request) asks this module, so the rules
live in one place:

* Managing entries needs the ``secrets`` role (or ``checkmk``, which ran
  the store when it was the Checkmk password store).
* Seeing a plaintext value needs the ``secrets_reveal`` role on top.
* A user limited to accounts or CMDB templates only reaches entries bound
  to hosts inside that limit. Global entries belong to no host and are
  therefore out of their reach, and they may only bind entries to hosts
  they can see. This holds for global admins too, the same way the host
  lists treat them.

Outside a request (CLI, cron) there is no acting user and everything is
allowed: that is the export itself, run by whoever runs the syncer.
"""
from contextvars import ContextVar

from flask import g, has_request_context

MANAGE_ROLES = ('secrets', 'checkmk')
REVEAL_ROLE = 'secrets_reveal'


class _NoRights:  # pylint: disable=too-few-public-methods
    """Stands in for an anonymous request: no role, no host."""

    @staticmethod
    def has_right(_role):
        """Anonymous requests hold no role."""
        return False

    @staticmethod
    def account_scope():
        """Reaches no account."""
        return set()

    @staticmethod
    def template_scope():
        """Template limit does not matter once no account is reachable."""
        return None


NO_RIGHTS = _NoRights()


# Set by entry points that serve users without a Flask request (the MCP
# server), so the checks below know who is asking there as well.
_ACTING_USER = ContextVar('secret_store_acting_user', default=None)


def set_acting_user(user):
    """Name the user a non-Flask entry point acts for."""
    _ACTING_USER.set(user)


def acting_user():
    """
    The user whose rights apply right now: the user an entry point named
    with ``set_acting_user``, the API user of an API request, the logged-in
    user of a web request, ``NO_RIGHTS`` for an anonymous request, and
    ``None`` outside any request (trusted CLI context).
    """
    named = _ACTING_USER.get()
    if named is not None:
        return named
    if not has_request_context():
        return None
    api_user = getattr(g, 'api_user', None)
    if api_user is not None:
        return api_user
    from flask_login import current_user  # pylint: disable=import-outside-toplevel
    if current_user and current_user.is_authenticated:
        return current_user._get_current_object()  # pylint: disable=protected-access
    return NO_RIGHTS


def can_manage(user):
    """True when ``user`` may work with the Secret Store at all."""
    if user is None:
        return True
    return any(user.has_right(role) for role in MANAGE_ROLES)


def can_reveal_role(user):
    """True when ``user`` holds the role to see plaintext values."""
    if user is None:
        return True
    return user.has_right(REVEAL_ROLE)


def is_scoped(user):
    """True when ``user`` is limited to accounts and/or CMDB templates."""
    if user is None:
        return False
    return user.account_scope() is not None or user.template_scope() is not None


def scoped_hosts(user):
    """Host queryset ``user`` may reach (all hosts when unrestricted)."""
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    from application.models.host_templates import scope_hosts_to_templates
    query = Host.objects
    if user is None:
        return query
    accounts = user.account_scope()
    if accounts is not None:
        query = query.filter(source_account_name__in=list(accounts))
    return scope_hosts_to_templates(query, user.template_scope())


def host_in_scope(user, host):
    """True when ``user`` may reach ``host``."""
    if host is None:
        return False
    if not is_scoped(user):
        return True
    return scoped_hosts(user).filter(id=host.id).only('id').first() is not None


def visible_secrets(user):
    """Queryset of the entries ``user`` may see in the store."""
    from application.models.secret import Secret  # pylint: disable=import-outside-toplevel
    if not can_manage(user):
        return Secret.objects(id=None)
    if not is_scoped(user):
        return Secret.objects
    host_ids = list(scoped_hosts(user).scalar('id'))
    return Secret.objects(host_id__in=host_ids)


def can_access(user, entry):
    """True when ``user`` may see and edit ``entry``."""
    if entry is None or not can_manage(user):
        return False
    if not is_scoped(user):
        return True
    if entry.host_id is None:
        return False
    return host_in_scope(user, entry.get_host())


def can_reveal(user, entry):
    """True when ``user`` may read the plaintext of ``entry``."""
    return can_reveal_role(user) and can_access(user, entry)


def can_bind(user, host):
    """True when ``user`` may bind entries to ``host``."""
    return can_manage(user) and host_in_scope(user, host)
