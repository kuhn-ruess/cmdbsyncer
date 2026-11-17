"""
REST API import: reading an API page by page and keeping only the
records whose field value is listed in a lookup table.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import json
from unittest.mock import MagicMock

from application.helpers.lookup_table import clear_cache
from application.models.lookup_table import LookupTable
from application.modules.plugin import ResponseDataException
from application.plugins.rest.rest import RestImport

LookupTable(name='services', mode='table', entries="service\\nsvc-a\\n svc-b \\n").save()
clear_cache()


def importer(pages, **config):
    """A RestImport answering one page per request."""
    rest = RestImport.__new__(RestImport)
    rest.config = {'address': 'https://api.example.com/assets',
                   'data_key': 'assetEntities', **config}
    rest.inner_request = MagicMock(side_effect=[
        MagicMock(json=MagicMock(return_value={'assetEntities': page})) for page in pages])
    return rest


def asset(name, service):
    return {'host': name, 'technischesService': service}


# POST: the paging fields of the account go into the JSON body
rest = importer([[asset('srv1', 'svc-a'), asset('srv2', 'other')],
                 [asset('srv3', 'svc-b')]],
                method='POST', post_body='{"conditions": []}', page_limit='2',
                page_offset_field='offset', page_limit_field='limit',
                filter_field='technischesService', filter_lookup_table='services')
eq([r['host'] for r in rest.get_records()], ['srv1', 'srv3'], 'post pages filtered')
bodies = [json.loads(c.kwargs['data']) for c in rest.inner_request.call_args_list]
eq(bodies, [{'conditions': [], 'offset': 0, 'limit': 2},
            {'conditions': [], 'offset': 2, 'limit': 2}], 'post bodies')

# GET: own field names, sent as URL parameters; an empty page ends it
rest = importer([[asset('srv1', None), asset('srv2', 'svc-a')], []],
                page_limit='2', page_offset_field='start', page_limit_field='count')
eq(len(rest.get_records()), 2, 'get pages unfiltered')
eq([c.kwargs['params'] for c in rest.inner_request.call_args_list],
   [{'start': 0, 'count': 2}, {'start': 2, 'count': 2}], 'get params')

# Without page_limit it stays one request without paging fields
rest = importer([[asset('srv1', 'svc-a')]], page_limit='')
eq(len(rest.get_records()), 1, 'no paging')
eq('params' in rest.inner_request.call_args.kwargs, False, 'no paging params')

# An API that ignores the paging must not be asked forever
same = [asset('srv1', 'svc-a'), asset('srv2', 'svc-a')]
try:
    importer([same, same], page_limit='2').get_records()
    fail('paging ignored: no error')
except ResponseDataException:
    pass

# A missing lookup table stops the import instead of importing nothing
try:
    importer([[asset('srv1', 'svc-a')]], filter_field='technischesService',
             filter_lookup_table='nope').get_records()
    fail('missing table: no error')
except ValueError:
    pass

print('REST_PAGING_FILTER_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RestPagingFilterTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_paging_and_filter(self):
        """See the checks in SNIPPET."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('REST_PAGING_FILTER_OK', result.stdout)
