"""
Send the events of the Event Driven Ansible rules
"""
import json
from datetime import datetime, timedelta

from requests.exceptions import RequestException

from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin

from .models import EdaEventLog, EdaEventRule, EdaEventState
from .repeats import note_match, note_send, repeat_threshold
from .rules import EdaEventRuleEngine

# How much of an answer the history keeps
RESPONSE_EXCERPT = 500


def build_payload(hostname, event):
    """The JSON body of one event, as the rulebook sees it in event.payload."""
    payload = {
        'source': 'cmdbsyncer',
        'event': event['event'],
        'hostname': hostname,
        'rule': event['rule_name'],
        'vars': event['vars'],
        'timestamp': datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    # YAML gives dates and the like, the request wants plain JSON
    return json.loads(json.dumps(payload, default=str))


class EdaSender(Plugin):
    """
    Walk the hosts, evaluate the EDA rules and post one event per match to
    the event stream / webhook of the account.
    """
    name = "Event Driven Ansible: Send Events"
    source = "eda_send_events"

    def __init__(self, account):
        super().__init__(account)
        self.actions = EdaEventRuleEngine()
        self.actions.rules = EdaEventRule.objects(enabled=True).order_by('sort_field')
        self.counts = {'sent': 0, 'failed': 0, 'skipped': 0}
        self.run_started = datetime.now()

    #   .-- Request
    def auth(self):
        """
        (headers, auth) for the request: Basic Auth with a username,
        otherwise the password as token in the configured header.
        """
        username = self.config.get('username')
        password = self.config.get('password')
        if username:
            return {}, (username, password or '')
        if not password:
            return {}, None
        header = (self.config.get('auth_header') or 'Authorization').strip()
        # A missing field means the default, an emptied one no prefix
        prefix = (self.config.get('auth_prefix', 'Bearer') or '').strip()
        value = f"{prefix} {password}" if prefix else password
        return {header: value}, None

    def post_event(self, payload):
        """Post one event, return (ok, http_status, answer excerpt)."""
        headers, auth = self.auth()
        headers['Content-Type'] = 'application/json'
        try:
            response = self.inner_request('POST', self.config['address'],
                                          json=payload, headers=headers, auth=auth)
        except RequestException as exc:
            return False, None, str(exc)[:RESPONSE_EXCERPT]
        text = (getattr(response, 'text', '') or '')[:RESPONSE_EXCERPT]
        status = getattr(response, 'status_code', None)
        return bool(status and status < 400), status, text
    #.

    #   .-- Dedup
    def recently_sent(self, hostname, event):
        """
        Did this host send this event of this rule successfully within its
        `resend_after_hours`? 0 means once and never again.
        """
        query = {
            'account': self.account_name,
            'rule_id': event['rule_id'],
            'hostname': hostname,
            'event': event['event'],
            'status': 'success',
        }
        hours = event['resend_after_hours']
        if hours:
            query['sent_at__gte'] = datetime.now() - timedelta(hours=hours)
        return EdaEventLog.objects(**query).first() is not None
    #.

    #   .-- Repeat tracking
    def track_match(self, hostname, event):
        """The streak of this event on this host, updated for this run."""
        key = {
            'account': self.account_name,
            'rule_id': event['rule_id'],
            'hostname': hostname,
            'event': event['event'],
        }
        state = EdaEventState.objects(**key).first() or EdaEventState(**key)
        note_match(state, event['rule_name'],
                   repeat_threshold(self.config.get('repeat_threshold')), datetime.now())
        state.save()
        return state

    def resolve_unmatched(self):
        """
        Streaks of this account whose host gave no such event in this run
        are resolved: the host no longer matches, the action worked.
        """
        return EdaEventState.objects(
            account=self.account_name, resolved_at=None,
            last_match__lt=self.run_started,
        ).update(set__resolved_at=datetime.now(), set__state='resolved')
    #.

    def host_events(self, db_host):
        """The events the rules give one host."""
        attributes = self.get_attributes(db_host, False)
        if not attributes:
            return []
        outcomes = self.actions.get_outcomes(db_host, attributes['all'], use_cache=False)
        return outcomes.get('events', [])

    def handle_event(self, hostname, event):
        """Send one event unless it was sent recently, and log it."""
        state = None if self.dry_run else self.track_match(hostname, event)
        if self.recently_sent(hostname, event):
            self.counts['skipped'] += 1
            return
        payload = build_payload(hostname, event)
        if self.dry_run:
            print(f" {CC.OKBLUE}*{CC.ENDC} {hostname}: would send "
                  f"{json.dumps(payload)}")
            return
        if event['error']:
            ok, status, answer = False, None, event['error']
        else:
            ok, status, answer = self.post_event(payload)
        EdaEventLog(
            account=self.account_name,
            rule_id=event['rule_id'],
            rule_name=event['rule_name'],
            hostname=hostname,
            event=event['event'],
            payload=json.dumps(payload),
            sent_at=datetime.now(),
            status='success' if ok else 'failure',
            http_status=status,
            response=answer,
        ).save()
        note_send(state, ok, status, datetime.now())
        state.save()
        if ok:
            self.counts['sent'] += 1
            print(f" {CC.OKGREEN}*{CC.ENDC} {hostname}: sent {event['event']}")
        else:
            self.counts['failed'] += 1
            self.log_error(f"{hostname}: {event['event']} failed: {answer}")

    def send_events(self):
        """Evaluate every host and send its events."""
        for db_host in Host.get_export_hosts():
            for event in self.host_events(db_host):
                self.handle_event(db_host.hostname, event)
        if not self.dry_run:
            self.log_details.append(('resolved', self.resolve_unmatched()))
        for key, value in self.counts.items():
            self.log_details.append((key, value))
        return self.counts
