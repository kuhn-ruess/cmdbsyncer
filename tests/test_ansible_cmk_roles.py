"""
The shipped Checkmk Ansible roles must hand the automation secret and the
Checkmk host name to Checkmk unchanged.

A secret went through a hand built Bearer header (latin-1 only) and
through unquoted shell lines (broke on spaces, quotes, $, backslashes).
The host name was always inventory_hostname, now it is
cmk_agent_host_name, which defaults to it.

The static checks parse the role YAML. The render checks run the role's
own argv lists and vars through ansible-playbook on localhost and skip
when Ansible is not installed.
"""
# pylint: disable=missing-function-docstring
import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROLES = os.path.join(_REPO_ROOT, 'ansible', 'roles')
_ROLE_NAMES = ('cmk_host_agent', 'cmk_server_mngmt')

SECRET = 'p\\a$s\'w"ö € \\'
USER = 'automation'

_SHELL_MODULES = {
    'shell', 'ansible.builtin.shell', 'win_shell', 'ansible.windows.win_shell',
    'raw', 'ansible.builtin.raw',
}


def _load(path):
    with open(path, encoding='utf-8') as handle:
        return yaml.safe_load(handle) or []


def _task_files():
    return sorted(glob.glob(os.path.join(_ROLES, '*', 'tasks', '*.yml')))


def _tasks(path):
    for task in _load(path):
        yield task
        for key in ('block', 'rescue', 'always'):
            yield from task.get(key, [])


def _role_task(role, filename, name):
    for task in _tasks(os.path.join(_ROLES, role, 'tasks', filename)):
        if task.get('name') == name:
            return task
    raise AssertionError(f'{filename}: no task {name!r}')


def _ansible_playbook():
    local = os.path.join(os.path.dirname(sys.executable), 'ansible-playbook')
    if os.path.isfile(local):
        return local
    return shutil.which('ansible-playbook')


def _msvc_split(cmdline):
    """Split a command line like the Microsoft C runtime does."""
    args = []
    pos, end = 0, len(cmdline)
    while pos < end:
        while pos < end and cmdline[pos] in ' \t':
            pos += 1
        if pos >= end:
            break
        arg, quoted = '', False
        while pos < end and (quoted or cmdline[pos] not in ' \t'):
            char = cmdline[pos]
            if char == '\\':
                run_end = pos
                while run_end < end and cmdline[run_end] == '\\':
                    run_end += 1
                count = run_end - pos
                if run_end < end and cmdline[run_end] == '"':
                    arg += '\\' * (count // 2)
                    if count % 2:
                        arg += '"'
                        run_end += 1
                else:
                    arg += '\\' * count
                pos = run_end
            elif char == '"':
                quoted = not quoted
                pos += 1
            else:
                arg += char
                pos += 1
        args.append(arg)
    return args


class CmkRoleStaticTest(unittest.TestCase):
    """Rules every task file of the Checkmk roles has to follow."""

    def test_defaults_define_host_name(self):
        for role in _ROLE_NAMES:
            defaults = _load(os.path.join(_ROLES, role, 'defaults', 'main.yml'))
            self.assertEqual(defaults.get('cmk_agent_host_name'),
                             '{{ inventory_hostname }}', role)

    def test_host_name_goes_through_role_variable(self):
        for path in _task_files():
            with open(path, encoding='utf-8') as handle:
                self.assertNotIn('inventory_hostname', handle.read(), path)

    def test_secret_tasks(self):
        found = 0
        for path in _task_files():
            for task in _tasks(path):
                dumped = yaml.safe_dump(task, allow_unicode=True)
                if 'cmk_secret' not in dumped:
                    continue
                found += 1
                where = f"{os.path.basename(path)}: {task.get('name')}"
                if os.path.basename(path) == 'report_error.yml':
                    # Prints the error of a no_log task, the secret masked
                    self.assertIn('replace(cmk_secret', dumped, where)
                    continue
                self.assertNotIn('Bearer', dumped, where)
                self.assertIs(task.get('no_log'), True, where)
                self.assertFalse(_SHELL_MODULES & set(task), where)
                for module in ('command', 'ansible.builtin.command',
                               'win_command', 'ansible.windows.win_command'):
                    if module in task:
                        self.assertIn('argv', task[module], where)
        self.assertGreaterEqual(found, 10)

    def test_hidden_errors_are_reported(self):
        # no_log hides the error of a failed step, the next task reports it
        found = 0
        tasks_dir = os.path.join(_ROLES, 'cmk_host_agent', 'tasks')
        for path in glob.glob(os.path.join(tasks_dir, '*-tasks.yml')) + [
                os.path.join(tasks_dir, 'main.yml')]:
            tasks = _load(path)
            for idx, task in enumerate(tasks):
                if task.get('no_log') is not True:
                    continue
                found += 1
                where = f"{os.path.basename(path)}: {task.get('name')}"
                result = task.get('register')
                self.assertTrue(result, where)
                self.assertTrue(task.get('ignore_errors'), where)
                report = tasks[idx + 1]
                self.assertEqual(report.get('ansible.builtin.include_tasks'),
                                 'report_error.yml', where)
                self.assertEqual(report['vars']['cmk_result'],
                                 f'{{{{ {result} }}}}', where)
                self.assertEqual(report['when'], f'{result} is failed', where)
        self.assertGreaterEqual(found, 10)

    def test_uri_tasks_use_basic_auth(self):
        for path in _task_files():
            for task in _tasks(path):
                args = task.get('ansible.builtin.uri')
                if not args or 'cmk_secret' not in str(args):
                    continue
                self.assertEqual(args.get('url_password'), '{{ cmk_secret }}')
                self.assertEqual(args.get('url_username'), '{{ cmk_user }}')
                self.assertIs(args.get('force_basic_auth'), True)


@unittest.skipUnless(_ansible_playbook(), 'ansible-playbook not installed')
class CmkRoleRenderTest(unittest.TestCase):
    """Render the role's own commands with a hostile secret."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        cls.result = cls._run_playbook(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _build_tasks(tmp):
        """The role's register commands and download header as local tasks."""
        echo = [sys.executable, '-c',
                'import json, sys; print(json.dumps(sys.argv[1:]))']
        names = ('Register Agent for TLS.', 'Register Agent on Local Bakery.',
                 'Register Agent on Central Bakery.')
        tasks, keys = [], []
        for name in names:
            task = _role_task('cmk_host_agent', 'Linux-tasks.yml', name)
            key = f'linux_{len(keys)}'
            tasks.append({'name': name, 'register': key, 'vars': task.get('vars', {}),
                          'ansible.builtin.command': {
                              'argv': echo + task['ansible.builtin.command']['argv'][1:]}})
            keys.append((key, 'stdout'))
        for name in names:
            task = _role_task('cmk_host_agent', 'Windows-tasks.yml', name)
            key = f'win_{len(keys)}'
            tasks.append({'name': name, 'register': key, 'vars': task.get('vars', {}),
                          'ansible.builtin.debug': {
                              'msg': task['ansible.windows.win_command']['argv']}})
            keys.append((key, 'msg'))
        download = _role_task('cmk_host_agent', 'Windows-tasks.yml',
                              'Download Checkmk Agent.')['ansible.windows.win_get_url']
        tasks.append({'name': 'download', 'register': 'download',
                      'ansible.builtin.debug': {'msg': {
                          'url': download['url'],
                          'auth': download['headers']['Authorization']}}})
        keys.append(('download', 'msg'))
        collected = '{{ {' + ', '.join(f"'{key}': {key}.{field}"
                                        for key, field in keys) + '} | to_json }}'
        tasks.append({'ansible.builtin.copy': {
            'content': collected, 'dest': os.path.join(tmp, '{{ inventory_hostname }}.json')}})
        return tasks

    @classmethod
    def _run_playbook(cls, tmp):
        defaults = os.path.join(_ROLES, 'cmk_host_agent', 'defaults', 'main.yml')
        local = {'ansible_connection': 'local', 'ansible_python_interpreter': sys.executable}
        # Group vars rank below host vars like role defaults do, so the
        # per host value from the syncer inventory wins over the default.
        files = {
            'play.yml': [{'hosts': 'all', 'gather_facts': False,
                          'tasks': cls._build_tasks(tmp)}],
            'inventory.yml': {'all': {'vars': _load(defaults), 'hosts': {
                'srv01.corp.example.com': dict(local, cmk_agent_host_name='srv01'),
                'srv02': dict(local),
            }}},
            'extra.yml': {'cmk_user': USER, 'cmk_secret': SECRET,
                          'cmk_server': 'cmk.corp.example.com', 'cmk_site': 'mysite',
                          'cmk_main_server': 'main.corp.example.com',
                          'cmk_main_site': 'central'},
        }
        for filename, content in files.items():
            with open(os.path.join(tmp, filename), 'w', encoding='utf-8') as handle:
                yaml.safe_dump(content, handle, allow_unicode=True)
        env = dict(os.environ, ANSIBLE_NOCOLOR='1', ANSIBLE_HOST_KEY_CHECKING='0',
                   ANSIBLE_LOCAL_TEMP=os.path.join(tmp, 'local'),
                   ANSIBLE_REMOTE_TEMP=os.path.join(tmp, 'remote'))
        proc = subprocess.run(
            [_ansible_playbook(), '-i', os.path.join(tmp, 'inventory.yml'),
             '-e', '@' + os.path.join(tmp, 'extra.yml'), os.path.join(tmp, 'play.yml')],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
            timeout=300, check=False)
        if proc.returncode:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        result = {}
        for host in ('srv01.corp.example.com', 'srv02'):
            with open(os.path.join(tmp, host + '.json'), encoding='utf-8') as handle:
                result[host] = json.load(handle)
        return result

    def test_linux_argv_keeps_secret(self):
        for host, name in (('srv01.corp.example.com', 'srv01'), ('srv02', 'srv02')):
            for key in ('linux_0', 'linux_1', 'linux_2'):
                argv = json.loads(self.result[host][key])
                self.assertEqual(argv[argv.index('--password') + 1], SECRET)
                self.assertEqual(argv[argv.index('-U') + 1], USER)
                self.assertEqual(argv[argv.index('-H') + 1], name)
            self.assertIn('cmk.corp.example.com:8000', json.loads(self.result[host]['linux_0']))
            self.assertIn('main.corp.example.com:443', json.loads(self.result[host]['linux_2']))

    def test_windows_tls_argv_keeps_secret(self):
        argv = self.result['srv01.corp.example.com']['win_3']
        self.assertEqual(argv[argv.index('--password') + 1], SECRET)
        self.assertEqual(argv[argv.index('--hostname') + 1], 'srv01')

    def test_windows_updater_survives_agent_join(self):
        # check_mk_agent.exe joins everything after "updater" with plain
        # spaces and starts the Python updater with that command line.
        for host, name in (('srv01.corp.example.com', 'srv01'), ('srv02', 'srv02')):
            for key in ('win_4', 'win_5'):
                argv = self.result[host][key]
                params = argv[argv.index('updater') + 1:]
                parsed = _msvc_split(' '.join(params))
                self.assertEqual(parsed[parsed.index('-S') + 1], SECRET)
                self.assertEqual(parsed[parsed.index('-U') + 1], USER)
                self.assertEqual(parsed[parsed.index('-H') + 1], name)
                self.assertEqual(parsed[-1], '-v')

    def test_windows_download_header(self):
        download = self.result['srv01.corp.example.com']['download']
        self.assertTrue(download['url'].endswith('host_name=srv01'))
        scheme, token = download['auth'].split(' ', 1)
        self.assertEqual(scheme, 'Basic')
        self.assertEqual(base64.b64decode(token).decode('utf-8'), f'{USER}:{SECRET}')

    def test_playbooks_syntax(self):
        env = dict(os.environ, ANSIBLE_ROLES_PATH=_ROLES,
                   ANSIBLE_LOCAL_TEMP=os.path.join(self.tmp.name, 'local'))
        for playbook in ('cmk_agent_mngmt.yml', 'cmk_server_mngmt.yml'):
            proc = subprocess.run(
                [_ansible_playbook(), '--syntax-check', '-i', 'localhost,',
                 os.path.join(_REPO_ROOT, 'ansible', playbook)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                timeout=300, check=False)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

_FAKE_OMD = """#!/bin/bash
echo "omd $*" >> "$OMD_CALLS"
case "$*" in
  *update*)
    [ "$OMD_UPDATE" = ok ] && echo "Finished update." && exit 0
    [ "$OMD_UPDATE" = noop ] && exit 0
    echo "-| Incompatible local file '/omd/sites/mysite/local/share/check_mk/web/plugins/pages/x.py'."
    echo "-| Abort the update process? [A/c]"
    exit 1;;
esac
"""


@unittest.skipUnless(_ansible_playbook(), 'ansible-playbook not installed')
class SiteUpdateResultTest(unittest.TestCase):
    """The run passes only when omd prints "Finished update", the check of
    the Checkmk Ansible collection. The site is started again either way."""

    def _run(self, update):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.mkdir(os.path.join(tmp, 'bin'))
        omd = os.path.join(tmp, 'bin', 'omd')
        with open(omd, 'w', encoding='utf-8') as handle:
            handle.write(_FAKE_OMD)
        os.chmod(omd, 0o755)
        role_tasks = _load(os.path.join(_ROLES, 'cmk_server_mngmt', 'tasks', 'main.yml'))
        tasks = [task for task in role_tasks
                 if task.get('name', '').startswith(('Update Sites', 'Site update of'))]
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            task.pop('become', None)
        play = [{'hosts': 'all', 'gather_facts': False, 'tasks': tasks, 'vars': {
            'cmk_site': 'mysite', 'cmk_version': '2.5.0p19', 'cmk_edition': 'pro',
            'server_site_version': {'stdout': '2.4.0p20.pro'},
            'site_just_installed': {'changed': False}}}]
        with open(os.path.join(tmp, 'play.yml'), 'w', encoding='utf-8') as handle:
            yaml.safe_dump(play, handle)
        calls = os.path.join(tmp, 'calls')
        env = dict(os.environ, ANSIBLE_NOCOLOR='1', OMD_CALLS=calls, OMD_UPDATE=update,
                   PATH=os.path.join(tmp, 'bin') + os.pathsep + os.environ['PATH'],
                   ANSIBLE_LOCAL_TEMP=os.path.join(tmp, 'local'),
                   ANSIBLE_REMOTE_TEMP=os.path.join(tmp, 'remote'))
        proc = subprocess.run(
            [_ansible_playbook(), '-i', 'srv01,', '-c', 'local',
             '-e', f'ansible_python_interpreter={sys.executable}',
             os.path.join(tmp, 'play.yml')],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
            timeout=300, check=False)
        with open(calls, encoding='utf-8') as handle:
            return proc, handle.read().splitlines()

    def test_failed_update_fails_with_output_and_starts_the_site(self):
        proc, calls = self._run('fail')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("did not finish: -| Incompatible local file", proc.stdout)
        self.assertEqual(calls[-1], 'omd start mysite')

    def test_update_without_finish_fails(self):
        proc, _calls = self._run('noop')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('did not finish', proc.stdout)

    def test_update_passes(self):
        proc, calls = self._run('ok')
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:])
        self.assertEqual(calls, ['omd stop mysite',
                                 'omd -f -V 2.5.0p19.pro update --conflict=install mysite',
                                 'omd start mysite'])

    def test_no_preflight_switch(self):
        with open(os.path.join(_ROLES, 'cmk_server_mngmt', 'tasks', 'main.yml'),
                  encoding='utf-8') as handle:
            tasks = handle.read()
        self.assertIn('update --conflict=install', tasks)
        self.assertNotIn('--pre-flight', tasks)

@unittest.skipUnless(_ansible_playbook(), 'ansible-playbook not installed')
class InstalledVersionTest(unittest.TestCase):
    """The installer is only copied and installed when omd lacks exactly
    this version and edition; a grep for the version alone also hit
    2.5.0p19 for 2.5.0p1 and installed again on every run."""

    def _missing(self, installed):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.mkdir(os.path.join(tmp, 'bin'))
        omd = os.path.join(tmp, 'bin', 'omd')
        with open(omd, 'w', encoding='utf-8') as handle:
            handle.write('#!/bin/bash\nprintf "$OMD_VERSIONS"\n')
        os.chmod(omd, 0o755)
        tasks = [task for task in _load(os.path.join(_ROLES, 'cmk_server_mngmt', 'tasks',
                                                     'main.yml'))
                 if 'Version is' in task.get('name', '')]
        self.assertEqual(len(tasks), 2)
        result = os.path.join(tmp, 'result')
        tasks.append({'ansible.builtin.copy': {'dest': result,
                                               'content': '{{ cmk_version_missing | bool }}'}})
        play = [{'hosts': 'all', 'gather_facts': False, 'tasks': tasks, 'vars': {
            'cmk_version': '2.5.0p1', 'cmk_edition': 'pro'}}]
        with open(os.path.join(tmp, 'play.yml'), 'w', encoding='utf-8') as handle:
            yaml.safe_dump(play, handle)
        env = dict(os.environ, ANSIBLE_NOCOLOR='1', OMD_VERSIONS=installed,
                   PATH=os.path.join(tmp, 'bin') + os.pathsep + os.environ['PATH'],
                   ANSIBLE_LOCAL_TEMP=os.path.join(tmp, 'local'),
                   ANSIBLE_REMOTE_TEMP=os.path.join(tmp, 'remote'))
        proc = subprocess.run(
            [_ansible_playbook(), '-i', 'srv01,', '-c', 'local',
             '-e', f'ansible_python_interpreter={sys.executable}',
             os.path.join(tmp, 'play.yml')],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
            timeout=300, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:])
        with open(result, encoding='utf-8') as handle:
            return handle.read()

    def test_installed(self):
        self.assertEqual(self._missing('2.4.0p20.cee\\n2.5.0p1.pro\\n2.5.0p1.ultimate\\n'),
                         'False')

    def test_other_patch_or_edition_is_missing(self):
        self.assertEqual(self._missing('2.5.0p19.pro\\n2.5.0p1.community\\n'), 'True')

    def test_no_omd_yet(self):
        self.assertEqual(self._missing(''), 'True')


if __name__ == '__main__':
    unittest.main()
