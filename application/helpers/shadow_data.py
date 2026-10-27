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
"""
from contextlib import contextmanager
from contextvars import ContextVar

_SHADOW_VIEW = ContextVar('shadow_view', default=False)


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
