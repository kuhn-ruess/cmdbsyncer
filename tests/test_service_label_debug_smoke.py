"""
The host debug page lists the output of the rules matching a host: service or
regex, label name and value, with or without service data from Inventorize.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = r'''
import re

from application import limiter
from application.models.host import Host
from application.modules.rule.models import FullCondition
from application.plugins.checkmk.models import CheckmkServiceLabelRule, ServiceLabelOutcome
from application.plugins.checkmk.inventorize import PER_SERVICE_LABELS_KEY

limiter.enabled = False

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})


def page(hostname):
    return check(f'/admin/host/debug?hostname={hostname}&mode=checkmk_host',
                 200).get_data(as_text=True)


def seed_host(hostname, services):
    host = Host(hostname=hostname, source_account_id='acc', source_account_name='acc')
    host.labels = {}
    host.inventory = {}
    host.save()
    if services:
        # What Inventorize stores: update_inventory prefixes the source.
        host.update_inventory(PER_SERVICE_LABELS_KEY, {'services': services})
        host.save()


seed_host('rack-01', [{'service': 'Port 1', 'labels': {'raw': 'e-a'}},
                      {'service': 'Port 2', 'labels': {}},
                      {'service': 'Disk <b>', 'labels': {}}])
seed_host('bare-01', None)

CARD = 'fa-tags"></i> Service Labels'
GONE = ('This host has no inventorized service labels', 'no matching service',
        'depends on the service', 'Inventorize', 'no label')


def card(hostname):
    body = page(hostname)
    return body[body.index(CARD):body.index('accordion-export')]


def rows(hostname):
    # What the table shows: service or regex, label, value.
    cells = re.findall(r'<td><code>(.*?)</code></td>', card(hostname))
    return [tuple(cells[pos:pos + 3]) for pos in range(0, len(cells), 3)]


def no_message(hostname):
    for gone in GONE:
        eq(gone in card(hostname), False, f'{gone} is not on the card of {hostname}')


eq(CARD in page('rack-01'), False, 'no card without a Service Label rule')

CheckmkServiceLabelRule(name='Not firing', condition_typ='all', enabled=True, sort_field=1,
    conditions=[FullCondition(match_type='host', hostname_match='equal',
                              hostname_match_negate=False, hostname='other-host')],
    outcomes=[ServiceLabelOutcome(service_pattern='^Hidden', label_name='kept',
                                  label_value='stays')]).save()
eq('No Service Label rule matches this host.' in card('bare-01'), True, 'the one line message')
eq('<table' in card('bare-01'), False, 'no list when no rule matches')
no_message('bare-01')

empty = CheckmkServiceLabelRule(name='Empty', condition_typ='anyway', enabled=True, sort_field=0,
    outcomes=[ServiceLabelOutcome(service_pattern='^Port', label_name='none',
                                  label_value="{{ LABELS.raw|default('') }}")]).save()
eq(rows('bare-01'), [], 'an empty value is not sent, so it is not listed')
eq('The Service Label rules matching this host send no label.' in card('bare-01'), True,
   'a rule matches, but nothing comes out')
eq('No Service Label rule matches' in card('bare-01'), False, 'as a rule does match')
empty.delete()

CheckmkServiceLabelRule(name='First', condition_typ='anyway', enabled=True, sort_field=2,
    outcomes=[ServiceLabelOutcome(service_pattern=r'^Port (\d)', label_name='host',
                                  label_value='{{ HOSTNAME }}'),
              ServiceLabelOutcome(service_pattern=r'^Port (\d)', label_name='raw',
                                  label_value="{{ LABELS.raw|default('') }}"),
              ServiceLabelOutcome(service_pattern=r'^Port (\d)', label_name='slot',
                                  label_value='{{ MATCH[1] }}'),
              ServiceLabelOutcome(service_pattern='^Disk', label_name='where',
                                  label_value='{{ SERVICE }}')]).save()
CheckmkServiceLabelRule(name='Second', condition_typ='anyway', enabled=True, sort_field=3,
    outcomes=[ServiceLabelOutcome(service_pattern=r'^Port (\d)', label_name='host',
                                  label_value='late'),
              ServiceLabelOutcome(service_pattern='^Fan', label_name='kind',
                                  label_value='fan'),
              ServiceLabelOutcome(service_pattern='^Fan', label_name='broken',
                                  label_value='{{ LABELS.nope.split() }}')]).save()

# Without any service data, the case the card is for.
eq(rows('bare-01'), [
    (r'^Port (\d)', 'host', 'bare-01'),
    ('^Fan', 'kind', 'fan'),
    ('^Fan', 'broken', 'dict object&#39; has no attribute &#39;nope&#39;'.join(['&#39;', ''])),
], 'the output of the rules without service data')
no_message('bare-01')

# With services: one row per service, a regex without one stays from the host.
eq(rows('rack-01'), [
    ('Port 1', 'host', 'rack-01'), ('Port 1', 'raw', 'e-a'), ('Port 1', 'slot', '1'),
    ('Port 2', 'host', 'rack-01'), ('Port 2', 'slot', '2'),
    ('Disk &lt;b&gt;', 'where', 'Disk &lt;b&gt;'),
    ('^Fan', 'kind', 'fan'),
    ('^Fan', 'broken', 'dict object&#39; has no attribute &#39;nope&#39;'.join(['&#39;', ''])),
], 'the output of the rules with service data')
no_message('rack-01')
text = card('rack-01')
for gone in ('^Hidden', 'stays', 'First', 'Second', 'Not firing', 'late', 'alert-danger'):
    eq(gone in text, False, f'{gone} is not on the card')

print('SERVICE_LABEL_DEBUG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ServiceLabelDebugTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_debug_page(self):
        """The card on the host debug page, with what comes out and what doesn't."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SERVICE_LABEL_DEBUG_OK', result.stdout)
