"""Files: Checkmk installation packages can be uploaded, others still not."""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest

from tests import _load_real_module  # pylint: disable=no-name-in-module

fileadmin = _load_real_module(
    'application.views.fileadmin_under_test',
    'views/fileadmin.py',
)


class UploadExtensionTest(unittest.TestCase):

    def setUp(self):
        self.view = fileadmin.FileAdminView.__new__(fileadmin.FileAdminView)

    def test_checkmk_packages_are_allowed(self):
        for name in ('check-mk-pro-2.5.0p1_0.noble_amd64.deb',
                     'check-mk-pro-2.5.0p1-el9-38.x86_64.rpm',
                     'check-mk-pro-2.5.0p1-x86_64.cma',
                     'CHECK-MK.DEB'):
            self.assertTrue(self.view.is_file_allowed(name), name)

    def test_packages_are_not_editable(self):
        self.assertFalse(self.view.is_file_editable('check-mk.deb'))

    def test_other_binaries_stay_refused(self):
        for name in ('tool.exe', 'script.sh', 'archive.tar.gz'):
            self.assertFalse(self.view.is_file_allowed(name), name)


if __name__ == '__main__':
    unittest.main()
