"""
Weekly runs of the Checkmk Server Settings: when they are due and what
they do.
"""
# pylint: disable=missing-function-docstring
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import requests

from application.helpers.task_status import take_task_failure
from application.plugins.checkmk import server_schedule
from application.plugins.checkmk.download_catalog import newest_patch

# A Tuesday
TUESDAY_22_30 = datetime(2026, 11, 10, 22, 30)

MAJORS = [{'major': '2.4.0', 'version': '2.4.0p15'},
          {'major': '2.3.0', 'version': '2.3.0p40'}]


def _setting(**kwargs):
    values = {'id': 'abc', 'name': 'prod', 'cmk_version': '2.4.0p12',
              'download_proxy': None, 'schedule_weekday': 'tue',
              'schedule_hour': '22', 'schedule_update_version': True,
              'schedule_run_playbook': True, 'schedule_last_run': None,
              'schedule_depends_on': None, 'schedule_last_status': None,
              'schedule_last_message': None, 'schedule_last_version': None,
              'get_server_ssh_key': lambda: None}
    values.update(kwargs)
    return SimpleNamespace(**values)


class IsDueTest(unittest.TestCase):
    """The run is due once, from its hour until the end of its day"""

    def test_due_after_the_hour_on_the_day(self):
        self.assertTrue(server_schedule.is_due(_setting(), TUESDAY_22_30))

    def test_not_due_before_the_hour(self):
        self.assertFalse(server_schedule.is_due(
            _setting(), TUESDAY_22_30.replace(hour=21)))

    def test_not_due_on_another_day(self):
        self.assertFalse(server_schedule.is_due(
            _setting(schedule_weekday='wed'), TUESDAY_22_30))

    def test_not_due_twice(self):
        setting = _setting(schedule_last_run=TUESDAY_22_30.replace(minute=0))
        self.assertFalse(server_schedule.is_due(setting, TUESDAY_22_30))

    def test_due_again_a_week_later(self):
        setting = _setting(schedule_last_run=datetime(2026, 11, 3, 22, 15))
        self.assertTrue(server_schedule.is_due(setting, TUESDAY_22_30))

    def test_not_due_without_weekday_or_action(self):
        self.assertFalse(server_schedule.is_due(
            _setting(schedule_weekday=None), TUESDAY_22_30))
        self.assertFalse(server_schedule.is_due(
            _setting(schedule_update_version=False, schedule_run_playbook=False),
            TUESDAY_22_30))


class DependencyChainTest(unittest.TestCase):
    """A chain of dependencies that leads back is refused"""

    def test_chain_nearest_first(self):
        base = SimpleNamespace(id=1, name='lab', schedule_depends_on=None)
        test = SimpleNamespace(id=2, name='test', schedule_depends_on=base)
        prod = SimpleNamespace(id=3, name='prod', schedule_depends_on=test)
        self.assertEqual(server_schedule.dependency_chain(prod), [test, base])

    def test_cycle_refused(self):
        prod = SimpleNamespace(id=3, name='prod', schedule_depends_on=None)
        test = SimpleNamespace(id=2, name='test', schedule_depends_on=prod)
        prod.schedule_depends_on = test
        with self.assertRaisesRegex(ValueError, 'depends on itself'):
            server_schedule.dependency_chain(prod)


class NewestPatchTest(unittest.TestCase):
    """The newest patch release of the same major version"""

    def test_newest_of_same_major(self):
        self.assertEqual(newest_patch(MAJORS, '2.3.0p12'), '2.3.0p40')

    def test_major_not_offered(self):
        with self.assertRaisesRegex(ValueError, 'not offered'):
            newest_patch(MAJORS, '2.1.0p3')

    def test_no_version(self):
        with self.assertRaisesRegex(ValueError, 'No version'):
            newest_patch(MAJORS, '')


class RunScheduledTest(unittest.TestCase):
    """The cron job sets the version first, then runs the playbook"""

    def setUp(self):
        take_task_failure()
        self.settings = mock.patch.object(server_schedule, 'CheckmkSettings').start()
        self.fetch = mock.patch.object(server_schedule.download_catalog, 'fetch',
                                       return_value=MAJORS).start()
        self.servers = mock.patch.object(server_schedule, 'site_servers',
                                         return_value=['srv01', 'srv02']).start()
        self.run = mock.patch.object(
            server_schedule, 'run_playbook',
            return_value=SimpleNamespace(status='success', pk='run1')).start()
        self.log = mock.patch.object(server_schedule, 'log').start()
        clock = mock.patch.object(server_schedule, 'datetime').start()
        clock.now.return_value = TUESDAY_22_30
        self.addCleanup(mock.patch.stopall)

    def _run(self, *settings):
        self.settings.objects.return_value.order_by.return_value = list(settings)
        server_schedule.run_scheduled_updates()
        return take_task_failure()

    def test_sets_version_and_runs_playbook_with_it(self):
        setting = _setting()
        self.assertIsNone(self._run(setting))
        self.assertEqual(setting.cmk_version, '2.4.0p15')
        updates = self.settings.objects.return_value.update_one.call_args_list
        self.assertIn(mock.call(set__cmk_version='2.4.0p15'), updates)
        self.assertIn(mock.call(set__schedule_last_run=TUESDAY_22_30), updates)
        kwargs = self.run.call_args.kwargs
        self.assertEqual(kwargs['target_host'], 'srv01,srv02')
        self.assertEqual(kwargs['provider'], 'cmk_sites:prod')
        self.assertTrue(kwargs['wait'])

    def test_settings_not_due_are_left_alone(self):
        self.assertIsNone(self._run(_setting(schedule_weekday='mon')))
        self.fetch.assert_not_called()
        self.run.assert_not_called()

    def test_only_version(self):
        self._run(_setting(schedule_run_playbook=False))
        self.run.assert_not_called()

    def test_only_playbook_needs_no_internet(self):
        self._run(_setting(schedule_update_version=False))
        self.fetch.assert_not_called()
        self.run.assert_called_once()

    def _updates(self):
        return self.settings.objects.return_value.update_one.call_args_list

    def test_checkmk_com_unreachable_is_tried_again(self):
        self.fetch.side_effect = requests.exceptions.ConnectionError('offline')
        failure = self._run(_setting())
        self.assertIn('Could not load', str(failure))
        self.assertNotIn(mock.call(set__schedule_last_run=TUESDAY_22_30),
                         self._updates())
        self.run.assert_not_called()

    def test_success_is_stored_and_logged(self):
        self._run(_setting())
        self.assertIn(mock.call(set__schedule_last_status='success',
                                set__schedule_last_message='Done',
                                set__schedule_last_version='2.4.0p15'),
                      self._updates())
        logged = [call.args[0] for call in self.log.log.call_args_list]
        self.assertEqual(logged, ['Weekly run of prod: Manage OMD Server started',
                                  'Weekly run of prod: success'])
        details = dict(self.log.log.call_args.kwargs['details'])
        self.assertEqual(details['version_before'], '2.4.0p12')
        self.assertEqual(details['ansible_run'], 'run1')

    def _with_dependency(self, **dependency):
        values = {'id': 'test-id', 'name': 'test', 'cmk_version': '2.4.0p14',
                  'schedule_last_status': 'success', 'schedule_last_message': 'Done',
                  'schedule_last_run': datetime(2026, 11, 9, 22, 10),
                  'schedule_last_version': '2.4.0p14', 'schedule_depends_on': None}
        values.update(dependency)
        dependency = SimpleNamespace(**values)
        self.settings.objects.return_value.first.return_value = dependency
        return _setting(schedule_depends_on=dependency)

    def test_dependency_success_gives_its_version(self):
        setting = self._with_dependency()
        self.assertIsNone(self._run(setting))
        self.fetch.assert_not_called()
        self.assertEqual(setting.cmk_version, '2.4.0p14')
        self.run.assert_called_once()

    def test_dependency_failure_skips_and_fails(self):
        setting = self._with_dependency(schedule_last_status='failure',
                                        schedule_last_message='playbook failed')
        failure = self._run(setting)
        self.assertIn('Skipped: test did not succeed: playbook failed', str(failure))
        self.run.assert_not_called()
        self.assertIn(mock.call(set__schedule_last_run=TUESDAY_22_30), self._updates())
        details = dict(self.log.log.call_args.kwargs['details'])
        self.assertIn('error', details)

    def test_dependency_too_old_skips(self):
        setting = self._with_dependency(schedule_last_run=datetime(2026, 11, 2, 22))
        self.assertIn('last 7 days', str(self._run(setting)))
        self.run.assert_not_called()

    def test_dependency_of_another_major_fails(self):
        setting = self._with_dependency(schedule_last_version='2.5.0p1')
        self.assertIn('another major release', str(self._run(setting)))
        self.run.assert_not_called()

    def test_dependency_runs_first_in_the_same_pass(self):
        test = _setting(name='test', id='test-id')
        prod = _setting(name='prod', schedule_depends_on=test)
        self.settings.objects.return_value.first.return_value = SimpleNamespace(
            **{**vars(test), 'schedule_last_status': 'success',
               'schedule_last_run': TUESDAY_22_30})
        self._run(prod, test)
        self.assertEqual([c.kwargs['provider'] for c in self.run.call_args_list],
                         ['cmk_sites:test', 'cmk_sites:prod'])

    def test_failed_playbook_fails_the_task_and_others_still_run(self):
        self.run.return_value = SimpleNamespace(status='failure', pk='run1')
        failure = self._run(_setting(name='prod'), _setting(name='test'))
        self.assertIn('prod: Manage OMD Server ended with failure', str(failure))
        self.assertEqual(self.run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
