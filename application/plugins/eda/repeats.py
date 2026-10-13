"""
Events that are sent again and again without effect.

Every event of a rule on a host has a streak (EdaEventState): it starts
with the first match and counts every send. When a run no longer gives
the host the event, the streak is resolved, the rulebook did its job.
A host that still matches after `repeat_threshold` sends is repeating:
its event keeps going out and nothing changes. The overview, the REST
API and with it the Checkmk check list those.
"""
from datetime import datetime, timedelta

from .models import DEFAULT_REPEAT_THRESHOLD, EdaEventLog, EdaEventState

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# How many offenders the API lists at most unless asked for more
DEFAULT_OFFENDER_LIMIT = 100


def repeat_threshold(value):
    """The `repeat_threshold` of an account, the default when unset."""
    if value is None or str(value).strip() == '':
        return DEFAULT_REPEAT_THRESHOLD
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return DEFAULT_REPEAT_THRESHOLD


#   .-- Streak bookkeeping
def is_repeating(state, threshold=None):
    """Still matching after at least `threshold` sends, 0 means never."""
    if threshold is None:
        threshold = state.repeat_threshold
    return not state.resolved_at and bool(threshold) and (state.sends or 0) >= threshold


def refresh_state(state):
    """Derive the `state` field from the counters."""
    if state.resolved_at:
        state.state = 'resolved'
    elif is_repeating(state):
        state.state = 'repeating'
    else:
        state.state = 'pending'


def note_match(state, rule_name, threshold, now):
    """
    The host gives this event in the current run. A resolved streak
    starts over, the condition is back.
    """
    if state.resolved_at:
        state.resolved_at = None
        state.sends = 0
        state.failures = 0
        state.first_sent = None
    state.rule_name = rule_name
    state.repeat_threshold = threshold
    state.last_match = now
    refresh_state(state)


def note_send(state, ok, http_status, now):
    """One send of the streak, successful or not."""
    state.sends = (state.sends or 0) + 1
    state.total_sends = (state.total_sends or 0) + 1
    if not ok:
        state.failures = (state.failures or 0) + 1
    if not state.first_sent:
        state.first_sent = now
    state.last_sent = now
    state.last_status = 'success' if ok else 'failure'
    state.last_http_status = http_status
    refresh_state(state)
#.


#   .-- Summary
def _time(value):
    return value.strftime(TIME_FORMAT) if value else None


def _offender(state, threshold):
    return {
        'account': state.account,
        'hostname': state.hostname,
        'event': state.event,
        'rule': state.rule_name,
        'rule_id': state.rule_id,
        'sends': state.sends or 0,
        'failures': state.failures or 0,
        'threshold': threshold,
        'first_sent': _time(state.first_sent),
        'last_sent': _time(state.last_sent),
        'last_status': state.last_status,
        'last_http_status': state.last_http_status,
    }


def _empty_counts():
    return {'events_24h': 0, 'failed_24h': 0, 'pending': 0, 'repeating': 0,
            'repeating_hosts': 0, 'failing': 0, 'max_sends': 0}


def _totals(accounts, hosts):
    """The counters over every account, hosts counted once."""
    total = _empty_counts()
    for counts in accounts.values():
        for key, value in counts.items():
            total[key] = max(total[key], value) if key == 'max_sends' else total[key] + value
    total['repeating_hosts'] = len(set().union(*hosts.values()))
    return total


def summarize(states, log_counts, min_sends=None, limit=DEFAULT_OFFENDER_LIMIT):
    """
    The numbers and the offenders, from the open streaks (not resolved,
    sent at least once) and the sends of the last 24 hours per account
    (`log_counts`: {account: (sent, failed)}). `min_sends` replaces the
    threshold of the accounts.
    """
    accounts = {}
    hosts = {}
    offenders = []
    for account, (sent, failed) in log_counts.items():
        counts = accounts.setdefault(account, _empty_counts())
        counts['events_24h'] = sent
        counts['failed_24h'] = failed
    for state in states:
        counts = accounts.setdefault(state.account, _empty_counts())
        threshold = state.repeat_threshold if min_sends is None else min_sends
        counts['max_sends'] = max(counts['max_sends'], state.sends or 0)
        if state.last_status == 'failure':
            counts['failing'] += 1
        if is_repeating(state, threshold):
            counts['repeating'] += 1
            hosts.setdefault(state.account, set()).add(state.hostname)
            offenders.append(_offender(state, threshold))
        else:
            counts['pending'] += 1
    for account, names in hosts.items():
        accounts[account]['repeating_hosts'] = len(names)

    offenders.sort(key=lambda entry: (-entry['sends'], entry['account'] or '',
                                      entry['hostname'] or '', entry['event'] or ''))
    return {
        **_totals(accounts, hosts),
        'min_sends': min_sends,
        'accounts': [{'account': name, **counts}
                     for name, counts in sorted(accounts.items(),
                                                key=lambda item: item[0] or '')],
        'offenders': offenders[:limit],
        'offenders_truncated': len(offenders) > limit,
    }


def collect_summary(account=None, min_sends=None, limit=DEFAULT_OFFENDER_LIMIT,
                    hostname_filter=None):
    """
    `summarize` over the database. `hostname_filter` takes a set of
    hostnames and returns the ones the caller may see (API scope).
    """
    query = {'resolved_at': None, 'sends__gte': 1}
    log_query = {'sent_at__gte': datetime.now() - timedelta(hours=24)}
    if account:
        query['account'] = account
        log_query['account'] = account
    states = list(EdaEventState.objects(**query))
    logs = EdaEventLog.objects(**log_query)
    if hostname_filter is not None:
        allowed = hostname_filter({s.hostname for s in states}
                                  | set(logs.distinct('hostname')))
        states = [s for s in states if s.hostname in allowed]
        logs = logs.filter(hostname__in=list(allowed))
    log_counts = {}
    for name in logs.distinct('account'):
        log_counts[name] = (logs.filter(account=name).count(),
                            logs.filter(account=name, status='failure').count())
    return summarize(states, log_counts, min_sends=min_sends, limit=limit)
#.
