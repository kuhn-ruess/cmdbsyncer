"""
active_templates() with a run cache: each template is loaded once for
all hosts instead of once per host.
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import MagicMock, patch

from bson.dbref import DBRef

from application.models.host_templates import active_templates


class _Template:  # pylint: disable=too-few-public-methods
    def __init__(self, pk, deleted_at=None):
        self.pk = pk
        self.deleted_at = deleted_at


def _host(*template_ids):
    host = MagicMock()
    host._data = {'cmdb_templates': [DBRef('host', tid) for tid in template_ids]}  # pylint: disable=protected-access
    return host


class TestActiveTemplatesCache(unittest.TestCase):
    """active_templates(host, cache)"""

    def test_loads_each_template_once(self):
        templates = {1: _Template(1), 2: _Template(2, deleted_at='x'), 3: _Template(3)}
        host_model = MagicMock()
        host_model.objects.side_effect = lambda pk__in: [templates[i] for i in pk__in]
        cache = {}
        with patch('application.models.host.Host', host_model):
            first = active_templates(_host(1, 2), cache)
            second = active_templates(_host(2, 1, 3), cache)
        self.assertEqual([t.pk for t in first], [1])
        self.assertEqual([t.pk for t in second], [1, 3])
        # Two queries for three templates, none for the known ones
        self.assertEqual(host_model.objects.call_count, 2)
        self.assertEqual(host_model.objects.call_args.kwargs, {'pk__in': [3]})

    def test_deleted_template_is_skipped(self):
        host_model = MagicMock()
        host_model.objects.return_value = []
        with patch('application.models.host.Host', host_model):
            self.assertEqual(active_templates(_host(7), {}), [])

    def test_without_cache_reads_the_host(self):
        host = MagicMock()
        host.cmdb_templates = [_Template(1), _Template(2, deleted_at='x')]
        self.assertEqual([t.pk for t in active_templates(host)], [1])


if __name__ == '__main__':
    unittest.main()
