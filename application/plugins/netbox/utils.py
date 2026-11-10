"""
Shared helpers for the Netbox plugin.
"""
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn


def make_progress():
    """Return the Syncer's standard rich Progress bar."""
    return Progress(SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                    TimeElapsedColumn())


def parse_import_filter(import_filter):
    """
    Parse the "key:value,key:value" import_filter string into kwargs for the
    Netbox API. The same key given more than once (e.g.
    "role:router,role:firewall") becomes an OR filter (list of values); a key
    with a single value stays a plain string so existing single-value filters
    keep working unchanged.
    """
    parsed_filter = defaultdict(list)
    for pair in import_filter.split(','):
        pair = pair.strip()
        if ':' in pair:
            key, value = pair.split(':', 1)
            parsed_filter[key].append(value)
    return {key: values if len(values) > 1 else values[0]
            for key, values in parsed_filter.items()}


def same_host_url(url, address):
    """
    The page link of an answer, with scheme and host of the account.
    The link comes from the server and carries the token on the next
    request, so it must not lead to another host.
    """
    page = urlsplit(url)
    base = urlsplit(address)
    return urlunsplit((base.scheme, base.netloc, page.path, page.query, ''))
