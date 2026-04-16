"""
Unit tests for checkmk poolfolder module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.poolfolder import get_folder, remove_seat, _get_folders


class TestGetFolders(unittest.TestCase):
    """Tests for _get_folders"""

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    def test_get_all_folders(self, mock_pool):
        mock_qs = Mock()
        mock_pool.objects.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs

        _get_folders()
        mock_pool.objects.assert_called_once_with()
        mock_qs.order_by.assert_called_with('folder_name')

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    def test_get_limited_folders(self, mock_pool):
        mock_qs = Mock()
        mock_pool.objects.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs

        _get_folders(limited=['/pool1', '/pool2'])
        mock_pool.objects.assert_called_once_with(
            folder_name__in=['/pool1', '/pool2'])


class TestGetFolder(unittest.TestCase):
    """Tests for get_folder"""

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    @patch('application.plugins.checkmk.poolfolder._get_folders')
    def test_returns_folder_with_free_seat(self, mock_get_folders, mock_pool):
        mock_folder = Mock()
        mock_folder.folder_name = '/pool1'
        mock_folder.folder_seats = 5
        mock_get_folders.return_value = [mock_folder]
        mock_pool.objects.return_value = Mock()
        mock_pool.objects.return_value.update_one.return_value = 1

        result = get_folder()
        self.assertEqual(result, mock_folder)
        mock_folder.reload.assert_called_once()

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    @patch('application.plugins.checkmk.poolfolder._get_folders')
    def test_returns_false_when_no_free_seat(self, mock_get_folders, mock_pool):
        mock_folder = Mock()
        mock_folder.folder_name = '/pool1'
        mock_folder.folder_seats = 5
        mock_get_folders.return_value = [mock_folder]
        mock_pool.objects.return_value = Mock()
        mock_pool.objects.return_value.update_one.return_value = 0

        result = get_folder()
        self.assertFalse(result)

    @patch('application.plugins.checkmk.poolfolder._get_folders')
    def test_returns_false_when_no_folders(self, mock_get_folders):
        mock_get_folders.return_value = []
        result = get_folder()
        self.assertFalse(result)

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    @patch('application.plugins.checkmk.poolfolder._get_folders')
    def test_passes_only_pools(self, mock_get_folders, mock_pool):
        mock_get_folders.return_value = []
        get_folder(only_pools=['/p1'])
        mock_get_folders.assert_called_once_with(['/p1'])


class TestRemoveSeat(unittest.TestCase):
    """Tests for remove_seat"""

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    def test_decrements_taken(self, mock_pool):
        mock_folder = Mock()
        mock_folder.folder_seats_taken = 3
        mock_pool.objects.get.return_value = mock_folder

        remove_seat('/pool1')

        self.assertEqual(mock_folder.folder_seats_taken, 2)
        mock_folder.save.assert_called_once()

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    def test_does_not_go_below_zero(self, mock_pool):
        mock_folder = Mock()
        mock_folder.folder_seats_taken = 0
        mock_pool.objects.get.return_value = mock_folder

        remove_seat('/pool1')

        self.assertEqual(mock_folder.folder_seats_taken, 0)
        mock_folder.save.assert_not_called()

    @patch('application.plugins.checkmk.poolfolder.CheckmkFolderPool')
    def test_does_not_exist_no_error(self, mock_pool):
        mock_pool.objects.get.side_effect = DoesNotExist()

        # Should not raise
        remove_seat('/nonexistent')


if __name__ == '__main__':
    unittest.main(verbosity=2)
