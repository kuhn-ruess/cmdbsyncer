"""
The AQL search of Jira Assets: total stops at 1000 since September 2024, so
only isLast may end the paging. The API is faked.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import MagicMock

from application.plugins.jira_cloud.jira_cloud import JiraCloud


def fake_api(objects, capped_total=True, with_is_last=True, server_page=None):
    """A stand-in for inner_request that pages through `objects`."""
    calls = []

    def request(**kwargs):
        start = kwargs['params']['startAt']
        calls.append(start)
        size = server_page or kwargs['params']['maxResults']
        values = objects[start:start + size]
        total = min(len(objects), 1000) if capped_total else len(objects)
        body = {'values': values, 'total': total}
        if with_is_last:
            body['isLast'] = start + len(values) >= len(objects)
        return MagicMock(json=lambda: body)

    return request, calls


class AqlPagingTest(unittest.TestCase):

    @staticmethod
    def read(request):
        jira = JiraCloud.__new__(JiraCloud)
        jira.base_url = 'https://example.com'
        jira.headers = {}
        jira.auth = ()
        jira.inner_request = request
        return list(jira._iter_aql_objects('x'))  # pylint: disable=protected-access

    def test_reads_past_the_capped_total(self):
        objects = list(range(1700))
        request, calls = fake_api(objects)
        self.assertEqual(self.read(request), objects)
        self.assertEqual(calls, [0, 500, 1000, 1500])

    def test_a_real_total_still_ends_at_the_last_page(self):
        objects = list(range(800))
        request, calls = fake_api(objects, capped_total=False)
        self.assertEqual(self.read(request), objects)
        self.assertEqual(calls, [0, 500])

    def test_a_smaller_page_of_the_server_does_not_end_it(self):
        objects = list(range(250))
        request, calls = fake_api(objects, server_page=100)
        self.assertEqual(self.read(request), objects)
        self.assertEqual(calls, [0, 100, 200])

    def test_without_is_last_a_short_page_ends_it(self):
        objects = list(range(1700))
        request, calls = fake_api(objects, with_is_last=False)
        self.assertEqual(self.read(request), objects)
        self.assertEqual(calls, [0, 500, 1000, 1500])

    def test_without_is_last_an_empty_page_ends_it(self):
        objects = list(range(1000))
        request, calls = fake_api(objects, with_is_last=False)
        self.assertEqual(self.read(request), objects)
        self.assertEqual(calls, [0, 500, 1000])


if __name__ == '__main__':
    unittest.main()
