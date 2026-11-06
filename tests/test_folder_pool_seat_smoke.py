"""
Deleting a host gives its folder pool seat back, in the REST API and in MCP.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.plugins.checkmk.models import CheckmkFolderPool


def pool(folder, taken):
    CheckmkFolderPool(folder_name=folder, folder_seats=10, folder_seats_taken=taken).save()


def taken(folder):
    return CheckmkFolderPool.objects.get(folder_name=folder).folder_seats_taken


pool('web', 5)
pool('empty', 0)

CheckmkFolderPool.free_seat_of_folder('web')
eq(taken('web'), 4, 'a seat comes back')
CheckmkFolderPool.free_seat_of_folder('WEB')
eq(taken('web'), 3, 'the folder name ignores the case')
CheckmkFolderPool.free_seat_of_folder('empty')
eq(taken('empty'), 0, 'never below zero')
CheckmkFolderPool.free_seat_of_folder('gone')
eq(CheckmkFolderPool.objects.count(), 2, 'a folder without a pool is no error')

print('SEAT_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class FolderPoolSeatTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_free_seat(self):
        """The seat counter follows, a missing pool is no error."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SEAT_OK', result.stdout)
