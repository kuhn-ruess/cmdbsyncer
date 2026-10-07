"""
The hosts one imported record stands for

Every importer turns a record of its source into hosts the same way:
the hostname the source delivers runs through the `rewrite_hostname`
template of the account once, and the result names the host. Usually
that is one name. A template that renders a list names several hosts,
and each of them is imported with the attributes of the whole record.

This sits next to `Host.get_host()` instead of inside it on purpose:
get_host() is called by the API, the web views and every exporter
too, which expect exactly one object back and know nothing about an
account or a record. Only an import has both, so only the import path
goes through here.
"""
import ast

from application import app
from application.models.host import Host


def parse_hostname_list(value):
    """
    The hostnames a rendered rewrite holds, or None when it is no list.

    Only a Python or JSON list literal counts, written in square brackets
    with quoted entries: `['a', 'b']`, which is what Jinja renders for a
    list. Brackets cannot be part of a valid hostname, so a name a
    template rendered so far can never be read as a list by accident. A
    comma alone splits nothing, so a hostname with a comma in it keeps
    its meaning.

    Empty entries are skipped, repeated ones are kept once, in the order
    they came. Entries that are no text and no number are skipped too.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.startswith('[') and text.endswith(']')):
        return None
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    if not isinstance(parsed, list):
        return None

    lowercase = app.config.get('LOWERCASE_HOSTNAMES')
    names = []
    seen = set()
    for entry in parsed:
        if isinstance(entry, bool) or not isinstance(entry, (str, int)):
            continue
        name = str(entry).strip()
        # get_host() stores the name the same way, so two entries that
        # only differ there would be the same host twice
        key = name.lower() if lowercase else name
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def import_hostnames(hostname, config, attributes):
    """
    The hostnames one record is imported under.

    Applies the `rewrite_hostname` template of the account once. Without
    a template, or when it renders a plain name, that is exactly one
    name, unchanged from what the rewrite gives. When it renders a list
    (see `parse_hostname_list`), it is one name per entry; an empty list
    imports nothing.
    """
    template = (config or {}).get('rewrite_hostname')
    if not template:
        return [hostname]
    rendered = Host.rewrite_hostname(hostname, template, attributes or {})
    names = parse_hostname_list(rendered)
    if names is None:
        return [rendered]
    return names


def get_import_hosts(hostname, config, attributes, create=True):
    """
    The hosts one record is imported into, as (hostname, host) pairs.

    The single entry point every importer goes through: rewrite once,
    split a list, then `Host.get_host()` for each name. The importer
    then does with every host what it always did with the one, so each
    of them gets the labels of the record, the account and the time it
    was last seen.
    """
    return [(name, Host.get_host(name, create=create))
            for name in import_hostnames(hostname, config, attributes)]


def update_import_host(host_obj, labels, config, **kwargs):
    """
    Write the labels of a record to one of its hosts and bind the host to
    the importing account. Saved only when the account may own it, a
    host of another master account stays as it is. Returns whether it
    was saved. Extra keywords go to `set_account()`.
    """
    host_obj.update_host(labels)
    if host_obj.set_account(account_dict=config, **kwargs):
        host_obj.save()
        return True
    return False
