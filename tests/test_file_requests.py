"""
Replaying a file written by --save-requests
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import unittest
from unittest.mock import Mock, patch

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'https://cmk.example.com/api/hosts'


def load_module():
    spec = importlib.util.spec_from_file_location(
        'file_requests_under_test',
        os.path.join(REPO_ROOT, 'application', 'plugins', 'file_requests.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def saved_line(method, payload):
    """A line the way Plugin.inner_request writes it"""
    return f"{method}||{URL}||{payload}\n"


class RunLinesTest(unittest.TestCase):

    def setUp(self):
        self.module = load_module()
        patcher = patch.object(self.module.requests, 'request',
                               return_value=Mock(status_code=200))
        self.request = patcher.start()
        self.addCleanup(patcher.stop)
        printer = patch('builtins.print')
        self.print = printer.start()
        self.addCleanup(printer.stop)

    def test_a_line_sends_only_its_own_method(self):
        payload = {'verify': True, 'timeout': 30.0, 'json': {'entries': ['a||b']},
                   'headers': {'Accept': 'application/json'}}
        failed = self.module.run_lines([saved_line('delete', payload)])
        self.assertEqual(failed, 0)
        self.request.assert_called_once_with('delete', URL, **payload)

    def test_every_method_the_plugins_send_works(self):
        for method in ('get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'POST'):
            self.request.reset_mock()
            self.assertEqual(self.module.run_lines([saved_line(method, {})]), 0)
            self.request.assert_called_once_with(method.lower(), URL)

    def test_empty_lines_are_skipped(self):
        self.assertEqual(self.module.run_lines(['\n', '   \n']), 0)
        self.request.assert_not_called()

    def test_bad_lines_are_named_and_the_rest_still_runs(self):
        lines = [
            saved_line('explode', {}),
            'no separators\n',
            f"post||{URL}||not a literal\n",
            f"post||{URL}||['no dict']\n",
            saved_line('get', {}),
        ]
        self.assertEqual(self.module.run_lines(lines), 4)
        self.request.assert_called_once_with('get', URL)
        printed = [call.args[0] for call in self.print.call_args_list]
        for number in (1, 2, 3, 4):
            self.assertTrue(any(text.startswith(f'Line {number}: ') for text in printed),
                            printed)

    def test_a_failed_connection_does_not_stop_the_file(self):
        self.request.side_effect = [requests.exceptions.ConnectionError('down'),
                                    Mock(status_code=200)]
        lines = [saved_line('post', {}), saved_line('post', {})]
        self.assertEqual(self.module.run_lines(lines), 1)
        self.assertEqual(self.request.call_count, 2)

    def test_debug_raises(self):
        with self.assertRaises(ValueError):
            self.module.run_lines([saved_line('explode', {})], debug=True)


if __name__ == '__main__':
    unittest.main()
