"""
What `cmdbsyncer sys setup_shell` writes into the bash files of a user
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import os
import tempfile
import unittest

from application.helpers import shell_setup


class BlockTest(unittest.TestCase):

    def test_the_block_names_config_venv_and_completion(self):
        text = shell_setup.block('/opt/cmdbsyncer', '/opt/cmdbsyncer/venv/bin/activate')
        self.assertTrue(text.startswith(shell_setup.BEGIN))
        self.assertTrue(text.endswith(shell_setup.END + '\n'))
        self.assertIn('export CMDBSYNCER_CONFIG_DIR=/opt/cmdbsyncer', text)
        self.assertIn('. /opt/cmdbsyncer/venv/bin/activate', text)
        self.assertIn(f'. ~/{shell_setup.COMPLETION_FILE}', text)

    def test_without_venv_there_is_nothing_to_activate(self):
        self.assertNotIn('activate', shell_setup.block('/opt/x', None))

    def test_paths_are_quoted(self):
        self.assertIn("CMDBSYNCER_CONFIG_DIR='/opt/my syncer'",
                      shell_setup.block('/opt/my syncer', None))


class WithBlockTest(unittest.TestCase):
    OLD = shell_setup.block('/old', None)
    NEW = shell_setup.block('/new', None)

    def test_an_empty_file_gets_the_block(self):
        self.assertEqual(shell_setup.with_block('', self.NEW), self.NEW)

    def test_the_block_is_appended_and_the_rest_kept(self):
        text = shell_setup.with_block('alias ll="ls -l"', self.NEW)
        self.assertEqual(text, f'alias ll="ls -l"\n\n{self.NEW}')

    def test_a_second_run_replaces_the_block(self):
        before = f'alias ll="ls -l"\n\n{self.OLD}export EDITOR=vim\n'
        text = shell_setup.with_block(before, self.NEW)
        self.assertEqual(text, f'alias ll="ls -l"\n\n{self.NEW}export EDITOR=vim\n')
        self.assertEqual(text.count(shell_setup.BEGIN), 1)


class LoginFileTest(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()

    def _write(self, name, text):
        with open(os.path.join(self.home, name), 'w', encoding='utf-8') as handle:
            handle.write(text)

    def test_a_home_without_dotfiles_gets_a_bash_profile(self):
        path, text = shell_setup.login_file_fix(self.home)
        self.assertEqual(path, os.path.join(self.home, '.bash_profile'))
        self.assertIn('.bashrc', text)

    def test_a_login_file_reading_bashrc_stays(self):
        self._write('.profile', 'if [ -f ~/.bashrc ]; then . ~/.bashrc; fi\n')
        self.assertIsNone(shell_setup.login_file_fix(self.home))

    def test_the_first_login_file_gets_the_line(self):
        self._write('.bash_profile', 'export PATH=$PATH:~/bin\n')
        self._write('.profile', '. ~/.bashrc\n')
        path, text = shell_setup.login_file_fix(self.home)
        self.assertEqual(path, os.path.join(self.home, '.bash_profile'))
        self.assertIn(shell_setup.SOURCE_BASHRC, text)


if __name__ == '__main__':
    unittest.main()
