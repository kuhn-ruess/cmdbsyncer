"""
Unit tests for the OP5 Monitor import
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import MagicMock

from application.plugins.op5.op5 import Op5, DEFAULT_COLUMNS


def make_op5(columns=''):
    op5 = Op5.__new__(Op5)
    op5.config = {
        'address': 'https://op5.example.com/',
        'username': 'user',
        'password': 'secret',
        'columns': columns,
    }
    return op5


class TestOp5(unittest.TestCase):
    """Tests for the OP5 host import"""

    def test_default_columns(self):
        self.assertEqual(make_op5().columns(), DEFAULT_COLUMNS)

    def test_configured_columns_always_contain_name(self):
        self.assertEqual(make_op5('address, groups').columns(),
                         ['name', 'address', 'groups'])

    def test_custom_variables_are_flattened(self):
        attributes = Op5.prepare_attributes({
            'name': 'web01',
            'groups': ['linux'],
            'custom_variables': {'LOCATION': 'Berlin'},
        })
        self.assertEqual(attributes, {
            'name': 'web01',
            'groups': ['linux'],
            'custom_variable_location': 'Berlin',
        })

    def test_get_hosts_pages_through_api(self):
        op5 = make_op5()
        op5.page_size = 2
        pages = [
            [{'name': 'a'}, {'name': 'b'}],
            [{'name': 'c'}],
        ]
        op5.inner_request = MagicMock(side_effect=[
            MagicMock(json=MagicMock(return_value=page)) for page in pages
        ])
        hostnames = [name for name, _ in op5.get_hosts()]
        self.assertEqual(hostnames, ['a', 'b', 'c'])

        first_call = op5.inner_request.call_args_list[0].kwargs
        self.assertEqual(first_call['url'], 'https://op5.example.com/api/filter/query')
        self.assertEqual(first_call['auth'], ('user', 'secret'))
        self.assertEqual(first_call['params']['query'], '[hosts] all')
        self.assertEqual(op5.inner_request.call_args_list[1].kwargs['params']['offset'], '2')

    def test_error_answer_raises(self):
        op5 = make_op5()
        op5.inner_request = MagicMock(return_value=MagicMock(
            json=MagicMock(return_value={'error': 'Invalid column'})))
        with self.assertRaises(ValueError):
            list(op5.get_hosts())
