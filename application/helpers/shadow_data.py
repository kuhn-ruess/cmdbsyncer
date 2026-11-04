"""
Evaluate rules against the shadow labels of a host

A shadow source account delivers its labels into `Host.shadow_labels`
only (see `Host.update_shadow()`). To test whether the rules still work
with them, the debug page evaluates a host inside `shadow_view()`: the
attribute set is then built from the shadow labels and the shadow
account instead of the live ones. Nothing outside that block is
affected, every export keeps reading the live labels.

Inside the block nothing a host computes may be stored: `Host.save()`
does nothing, so neither the rule cache the exports read nor a pool
folder or site assignment can come from shadow labels, and the Checkmk
rules take or free no pool seat.

Hosts a shadow source delivers but the syncer does not know are collected
per account and end up in one log entry when the process ends. A process
can run the imports of several accounts, and a source can miss thousands
of hosts: the count stays exact, only a sample of the names is kept.
"""
import atexit
from contextlib import contextmanager
from contextvars import ContextVar

_SHADOW_VIEW = ContextVar('shadow_view', default=False)

UNKNOWN_HOST_SAMPLE = 100
_UNKNOWN_HOSTS = {}


@contextmanager
def shadow_view():
    """
    Build the attributes of hosts from their shadow labels, without
    storing anything of them, for the duration of the block.
    """
    token = _SHADOW_VIEW.set(True)
    try:
        yield
    finally:
        _SHADOW_VIEW.reset(token)


def shadow_view_active():
    """Whether the attributes are built from shadow labels right now."""
    return _SHADOW_VIEW.get()


def report_unknown_host(hostname, account_name):
    """
    Note that *account_name* delivered *hostname*, which the syncer does
    not know. Logged by `log_unknown_hosts()` when the process ends.
    """
    if not _UNKNOWN_HOSTS:
        atexit.register(log_unknown_hosts)
    entry = _UNKNOWN_HOSTS.setdefault(account_name, {'count': 0, 'names': []})
    entry['count'] += 1
    if len(entry['names']) < UNKNOWN_HOST_SAMPLE:
        entry['names'].append(hostname)


def log_unknown_hosts():
    """Write one log entry per shadow source that delivered unknown hosts."""
    from application import log  # pylint: disable=import-outside-toplevel
    for account_name, entry in _UNKNOWN_HOSTS.items():
        names = ', '.join(entry['names'])
        hidden = entry['count'] - len(entry['names'])
        if hidden:
            names += f" and {hidden} more"
        log.log(f"Shadow source {account_name}: "
                f"{entry['count']} host(s) not in Syncer",
                source='shadow_source',
                details=[('account', account_name), ('not_in_syncer', names)])
    _UNKNOWN_HOSTS.clear()


def shadow_diff(live, shadow):
    """
    The keys whose value differs between two dicts, sorted, as
    (key, live value, shadow value). A missing side is None.
    """
    live = live if isinstance(live, dict) else {}
    shadow = shadow if isinstance(shadow, dict) else {}
    missing = object()
    rows = []
    for key in sorted(set(live) | set(shadow), key=str):
        live_value = live.get(key, missing)
        shadow_value = shadow.get(key, missing)
        if live_value != shadow_value:
            rows.append((key,
                         None if live_value is missing else live_value,
                         None if shadow_value is missing else shadow_value))
    return rows
