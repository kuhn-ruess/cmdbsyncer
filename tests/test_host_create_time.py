"""
Every host records when it was created.

`create_time` used to be written by the import path alone, so hosts
created in the GUI, clones and the CSV import had none — which made
"show me what was created today" unanswerable for half the database.
A pre_save receiver now stamps it whichever path saves the host, and
leaves every document that is already stored alone: a host from before
the field existed must stay empty rather than claim it was created
today.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=too-few-public-methods
import datetime
import importlib.util
import os
import re
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The receiver has no dependencies beyond the standard library, so it is
# loaded straight from its file instead of through the Host document.
_MODULE_PATH = os.path.join(REPO_ROOT, 'application', 'models',
                            'host_create_time.py')
_spec = importlib.util.spec_from_file_location('host_create_time_under_test',
                                               _MODULE_PATH)
host_create_time = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(host_create_time)
stamp_create_time = host_create_time.stamp_create_time

_HOST_MODEL = os.path.join(REPO_ROOT, 'application', 'models', 'host.py')


class _Document:
    """Stand-in for a Host document — the receiver only reads two fields."""

    def __init__(self, pk=None, create_time=None):
        self.pk = pk
        self.create_time = create_time


class StampCreateTimeTests(unittest.TestCase):
    def test_a_new_host_is_stamped(self):
        document = _Document()
        before = datetime.datetime.utcnow()
        stamp_create_time(None, document)
        after = datetime.datetime.utcnow()
        self.assertIsNotNone(document.create_time)
        self.assertGreaterEqual(document.create_time, before)
        self.assertLessEqual(document.create_time, after)

    def test_the_stamp_is_utc(self):
        document = _Document()
        stamp_create_time(None, document)
        # Naive, and close to utcnow — a local-time stamp would be off
        # by the server's offset and break every comparison the
        # cleanup jobs make.
        self.assertIsNone(document.create_time.tzinfo)
        drift = abs(document.create_time - datetime.datetime.utcnow())
        self.assertLess(drift, datetime.timedelta(seconds=5))

    def test_a_stored_host_keeps_its_empty_field(self):
        # The host predates the field: it must not be back-dated to now.
        document = _Document(pk='64c0ffee0000000000000000')
        stamp_create_time(None, document)
        self.assertIsNone(document.create_time)

    def test_an_existing_value_is_never_overwritten(self):
        original = datetime.datetime(2021, 5, 4, 12, 0)
        document = _Document(create_time=original)
        stamp_create_time(None, document)
        self.assertEqual(document.create_time, original)

    def test_the_receiver_is_wired_to_every_host_save(self):
        # The Host document cannot be imported without a live MongoDB,
        # so the wiring is checked where it is written. A stamp that is
        # never connected would leave the field empty again.
        with open(_HOST_MODEL, encoding='utf-8') as handle:
            source = handle.read()
        self.assertTrue(re.search(
            r'signals\.pre_save\.connect\(\s*stamp_create_time,\s*sender=Host\s*\)',
            source), 'stamp_create_time is not connected to Host pre_save')


if __name__ == '__main__':
    unittest.main()
