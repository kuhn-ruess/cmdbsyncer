# Notification Hub plugin

Local "who do we alert and how" layer. Sits between an event source
(Checkmk notification script is the first wired caller; the endpoint
is source-agnostic) and a delivery channel. Alerting logic is
described declaratively through five models, all editable in the
admin UI under **Modules → Notification Hub**:

| Model | Purpose |
|-------|---------|
| `NotifyContact` | A recipient: email + phone + default channels. Source may be `manual`, `imported` or `ldap` (dynamic). |
| `NotifyContactGroup` | A named set of contacts, optionally extended by a `dynamic_tag` or an LDAP filter. |
| `NotifyVacation` | Away window. During the window the contact is skipped or replaced by the substitute. |
| `NotifyShiftCalendar` | iCal / HTTPS calendar URL. The people whose names appear in the current event are the on-call subset. |
| `NotifyDispatchRule` | The routing table: match the event → pick groups → pick channels. |

## Dispatch endpoint

Two endpoints, registered as a Flask-RESTX namespace so they show up
in Swagger (`/api/v1/`):

```
POST /api/v1/notify/dispatch        → enqueue, return 202 + job_id
GET  /api/v1/notify/dispatch/<id>   → job status + per-recipient outcomes
```

Auth: the normal syncer API token (`x-login-user: USER:SECRET` or
HTTP Basic over HTTPS).

```
POST /api/v1/notify/dispatch
x-login-user: USER:SECRET
Content-Type: application/json

{
  "source": "checkmk",
  "event_type": "host.down",
  "host": "web01.example.com",
  "state": "CRIT",
  "title":   "[CRIT] web01 host down",
  "message": "PING CRITICAL - 100% packet loss",
  "context": { "contact_groups": "ops", "site": "prod" }
}
```

The POST is non-blocking — it validates, drops the event into the
in-memory queue and returns 202 with the job id. Poll the GET
endpoint (or watch the **Dispatch Queue** page in the admin) to see
the resolved recipients and per-channel outcome.

## In-memory queue

Inbound events land in a RAM `queue.Queue` (no Mongo hop on the hot
path). A single background worker thread per process drains it and
runs the resolver; completed jobs go into a bounded `deque` ring
buffer (last 1000 by default) that the admin UI reads for display.
Configurable via `local_config.py`:

```python
config['NOTIFY_QUEUE_MAXSIZE'] = 10_000    # concurrent inbox size
config['NOTIFY_HISTORY_SIZE']  = 1_000     # recent-job ring buffer
config['NOTIFY_MAX_ATTEMPTS']  = 3         # requeue count on error
```

Trade-off: a hard process kill loses in-flight jobs and the history
ring buffer. Upstream callers (the Checkmk notification script
included) already retry, so this is the right knob for "tens of
thousands of events / hour without a Redis dependency".

## Checkmk integration

A drop-in notification script is in `checkmk_notify.py.sample`. Copy
it as `cmdbsyncer` into the site's notification folder and create a
notification rule pointing at it. Set `CMDBSYNCER_URL`,
`CMDBSYNCER_USER`, `CMDBSYNCER_PASS` via the rule's parameters.

## CLI helpers

```
cmdbsyncer notify sync_calendars        # refresh every iCal feed
cmdbsyncer notify test_dispatch \       # resolve without delivering
    --event-type host.down --host web01 --state CRIT
```

Add *Notify: Sync Shift Calendars* to a cron group so the cached
events stay current (every 15 min is plenty for rotation cycles).

## Shift calendars

The iCal sync is intentionally minimal: it fetches the feed, parses
VEVENT blocks, and for every event it looks up which `NotifyContact`
names appear in the event summary or description. Those contacts are
the on-call set for that time window. So an event titled
`On-Call: alice, bob` during Monday 08:00–18:00 means the two
contacts `alice` and `bob` are on call during that window — no
Syncer IDs or plugin integration in Google Calendar needed.

## Dispatch delivery

When the Enterprise `notifications` feature is licensed, deliveries
reuse its `NotificationChannel` adapters (Slack, Teams, email,
generic webhook with HMAC signing). On plain OSS installs the
dispatcher falls back to **Flask-Mail SMTP** using the syncer's
standard `MAIL_*` config and the contact's `email` field — so Phase-1
still delivers end-to-end without a license. Contacts without an
email address are reported back as failed with a clear reason so you
see exactly who got skipped.

## Out of scope (v1)

- Escalation ladders (no-ack → next group after N minutes)
- Ack / snooze UI
- SMS / voice delivery
- Ticket-system integration
