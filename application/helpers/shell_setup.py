"""
The shell setup of `cmdbsyncer sys setup_shell`: a login of the user lands
with the venv active, the Syncer's configuration found from any directory
and tab completion for the cmdbsyncer command.
"""
import os
import re
import shlex
import subprocess
import sys

BEGIN = '# >>> cmdbsyncer >>>'
END = '# <<< cmdbsyncer <<<'
_BLOCK_RE = re.compile(rf'{re.escape(BEGIN)}\n.*?{re.escape(END)}\n?', re.DOTALL)

COMPLETION_FILE = '.cmdbsyncer-completion.bash'
# Login shells read the first of these that exists, none of them .bashrc
LOGIN_FILES = ('.bash_profile', '.bash_login', '.profile')
SOURCE_BASHRC = '[ -f ~/.bashrc ] && . ~/.bashrc'


class ShellSetupError(Exception):
    """The setup could not be done, the message says why"""


def venv_activate():
    """The activate script of the venv this process runs in, None outside one"""
    if sys.prefix == sys.base_prefix:
        return None
    path = os.path.join(sys.prefix, 'bin', 'activate')
    return path if os.path.isfile(path) else None


def block(config_dir, activate):
    """The lines written into ~/.bashrc, between the two markers"""
    lines = [BEGIN,
             '# Written by `cmdbsyncer sys setup_shell`, run it again to update.',
             f'export CMDBSYNCER_CONFIG_DIR={shlex.quote(config_dir)}']
    if activate:
        lines += [f'if [ -z "$VIRTUAL_ENV" ] && [ -f {shlex.quote(activate)} ]; then',
                  f'    . {shlex.quote(activate)}',
                  'fi']
    lines += [f'[ -f ~/{COMPLETION_FILE} ] && . ~/{COMPLETION_FILE}', END]
    return '\n'.join(lines) + '\n'


def with_block(text, new_block):
    """`text` with the block replaced, or appended when it has none"""
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(lambda _match: new_block, text, count=1)
    if text and not text.endswith('\n'):
        text += '\n'
    return f"{text}\n{new_block}" if text else new_block


def login_file_fix(home):
    """
    (path, text to append) so a login shell reads ~/.bashrc, or None.

    A system user made with `useradd --system` has no dotfiles, and a
    login shell (sudo -iu, su -, ssh) reads only the first login file.
    """
    for name in LOGIN_FILES:
        path = os.path.join(home, name)
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as handle:
                if 'bashrc' in handle.read():
                    return None
            return path, f'\n{SOURCE_BASHRC}\n'
    return os.path.join(home, '.bash_profile'), f'{SOURCE_BASHRC}\n'


def completion_script(binary, python=None):
    """Click's bash completion for the cmdbsyncer command"""
    env = dict(os.environ, _CMDBSYNCER_COMPLETE='bash_source')
    result = subprocess.run([python or sys.executable, binary], env=env,
                            capture_output=True, text=True, check=False)
    # The file is sourced at every login, so it has to be Click's script
    # and nothing else the command might have printed
    if not result.stdout.startswith('_cmdbsyncer_completion()'):
        raise ShellSetupError("The cmdbsyncer command gave no completion script: "
                              f"{(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout
