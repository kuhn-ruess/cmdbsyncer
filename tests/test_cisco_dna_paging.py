"""
The device list of Cisco DNA answers with 500 devices at most. The API is
faked, as a version that pages and as one that ignores offset and limit.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import re
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module():
    spec = importlib.util.spec_from_file_location(
        'cisco_dna_syncer_under_test',
        os.path.join(REPO_ROOT, 'application', 'plugins', 'cisco_dna', 'syncer.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def devices(count):
    return [{'id': f'id{number}'} for number in range(count)]


class DevicePagingTest(unittest.TestCase):

    def setUp(self):
        self.module = load_module()
        self.offsets = []
        printer = patch('builtins.print')
        printer.start()
        self.addCleanup(printer.stop)

    def read(self, answer):
        def request(_method, url, **_kwargs):
            offset = int(re.search(r'offset=(\d+)', url).group(1))
            self.offsets.append(offset)
            return answer(offset)

        dna = self.module.CiscoDNA.__new__(self.module.CiscoDNA)
        dna.address = 'https://example.com'
        dna.verify = True
        with patch.object(self.module.requests, 'request', request):
            return dna.get_devices({})

    @staticmethod
    def paging(all_devices):
        def answer(offset):
            page = all_devices[offset - 1:offset - 1 + 500]
            return MagicMock(status_code=200, json=lambda: {'response': page})
        return answer

    def test_reads_all_pages(self):
        self.assertEqual(self.read(self.paging(devices(1200))), devices(1200))
        self.assertEqual(self.offsets, [1, 501, 1001])

    def test_a_short_first_page_is_one_request(self):
        self.assertEqual(self.read(self.paging(devices(20))), devices(20))
        self.assertEqual(self.offsets, [1])

    def test_a_full_last_page_ends_with_the_empty_one(self):
        self.assertEqual(self.read(self.paging(devices(500))), devices(500))
        self.assertEqual(self.offsets, [1, 501])

    def test_a_version_ignoring_offset_gives_no_duplicates(self):
        def answer(_offset):
            return MagicMock(status_code=200, json=lambda: {'response': devices(500)})
        self.assertEqual(self.read(answer), devices(500))
        self.assertEqual(self.offsets, [1, 501])

    def test_an_error_on_a_later_page_keeps_the_devices_read(self):
        def answer(offset):
            if offset > 1:
                return MagicMock(status_code=400)
            return MagicMock(status_code=200, json=lambda: {'response': devices(500)})
        self.assertEqual(self.read(answer), devices(500))

    def test_an_error_on_the_first_page_still_raises(self):
        def answer(_offset):
            return MagicMock(status_code=401, json=lambda: {'error': 'x'})
        with self.assertRaises(KeyError):
            self.read(answer)


if __name__ == '__main__':
    unittest.main()
