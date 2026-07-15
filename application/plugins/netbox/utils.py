"""
Shared helpers for the Netbox plugin.
"""
from collections import defaultdict
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
