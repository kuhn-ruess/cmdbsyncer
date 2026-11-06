"""
How the Checkmk jobs report a failure: the three ways out are the same for all
"""
# pylint: disable=missing-function-docstring
import contextlib
import io
import unittest
from unittest.mock import patch, MagicMock

from application.plugins.checkmk import inits
from application.plugins.checkmk.cmk2 import CmkException

# job, syncer class, its work method, message when not started, log source
JOBS = [
    ('export_tags', 'CheckmkTagSync', 'export_tags',
     'Export Tags to Account acc not started', 'cmk_tag_sync'),
    ('export_bi_rules', 'BI', 'export_bi_rules',
     'Export BI Rules to Account acc not started', 'cmk_bi_sync'),
    ('export_bi_aggregations', 'BI', 'export_bi_aggregations',
     'Export BI Aggregations to Account acc not started', 'cmk_bi_aggrigation_sync'),
    ('inventorize_hosts', 'InventorizeHosts', 'run',
     'Inventorize Hosts Account acc not started', 'checkmk_inventorize'),
    ('export_groups', 'CheckmkGroupSync', 'export_cmk_groups',
     'Export Groups to Account acc not started', 'cmk_group_sync'),
    ('export_rules', 'CheckmkRuleSync', 'export_cmk_rules',
     'Export Rules to Account acc not started', 'cmk_rule_sync'),
    ('export_notifications', 'CheckmkNotificationRuleSync', 'export_notification_rules',
     'Export Notification Rules to Account acc not started', 'cmk_notification_rule_sync'),
    ('export_downtimes', 'CheckmkDowntimeSync', 'run',
     'Export Downtimes to Account acc not started', 'cmk_downtime_sync'),
    ('export_service_labels', 'CheckmkServiceLabelSync', 'export_cmk_rules',
     'Export Service Labels to Account acc not started', 'cmk_service_label_sync'),
    ('export_dcd_rules', 'CheckmkDCDRuleSync', 'export_rules',
     'Export DCD Rules to Account acc not started', 'cmk_dcd_rule_sync'),
    ('export_passwords', 'CheckmkPasswordSync', 'export_passwords',
     'Export Passwords to Account acc not started', 'cmk_password_sync'),
    ('import_sites', 'CheckmkSites', 'import_sites',
     'Import Sites from Account acc not started', 'cmk_site_sync'),
    ('export_users', 'CheckmkUserSync', 'export_users',
     'Export Users to Account acc not started', 'cmk_user_sync'),
    ('export_ldap_connections', 'CheckmkLdapConnectionSync', 'export_ldap_connections',
     'Export LDAP Connections to Account acc not started', 'cmk_ldap_connection_sync'),
]

# These have no debug argument, a failure is always reported
WITHOUT_DEBUG = {'export_passwords', 'import_sites', 'export_users', 'export_ldap_connections'}


class TestJobFailures(unittest.TestCase):
    """Every job, once failing in its work and once failing to set up"""

    def setUp(self):
        models = ['CheckmkRuleMngmt', 'CheckmkBiRule', 'CheckmkBiAggregation',
                  'CheckmkDowntimeRule', 'CheckmkServiceLabelRule', 'CheckmkDCDRule',
                  'CheckmkNotificationRule']
        patches = [patch.object(inits, name) for name in models] + [
            patch.object(inits, '_load_rules',
                         return_value={'rewrite': MagicMock(), 'filter': MagicMock()}),
            patch.object(inits, 'account_allows', return_value=True),
            patch.object(inits, 'projects_for_account', return_value=[]),
        ]
        for one in patches:
            one.start()
            self.addCleanup(one.stop)

    @staticmethod
    def _run(job, syncer_cls, method, error, debug=False):
        """
        Run the job with its syncer mocked: ``method`` raises ``error``, or the
        syncer's constructor does when it is None. Returns the mock and the output.
        """
        kwargs = {} if job in WITHOUT_DEBUG else {'debug': debug}
        output = io.StringIO()
        with patch.object(inits, syncer_cls) as mock_cls, \
                contextlib.redirect_stdout(output):
            if method:
                getattr(mock_cls.return_value, method).side_effect = error
            else:
                mock_cls.side_effect = error
            getattr(inits, job)('acc', **kwargs)
        return mock_cls, output.getvalue()

    def test_failing_work_goes_to_the_syncer(self):
        for job, syncer_cls, method, _message, _source in JOBS:
            with self.subTest(job=job), patch.object(inits, 'log') as log, \
                    patch.object(inits, 'task_failed') as task_failed:
                error = CmkException('boom')
                mock_cls, printed = self._run(job, syncer_cls, method, error)
                mock_cls.return_value.record_exception.assert_called_once_with(error)
                log.log.assert_not_called()
                task_failed.assert_not_called()
                self.assertIn('boom', printed)

    def test_failing_setup_is_logged_and_fails_the_task(self):
        for job, syncer_cls, _method, message, source in JOBS:
            with self.subTest(job=job), patch.object(inits, 'log') as log, \
                    patch.object(inits, 'task_failed') as task_failed:
                error = CmkException('boom')
                _mock_cls, printed = self._run(job, syncer_cls, None, error)
                log.log.assert_called_once_with(
                    message, source=source, details=[('error', 'boom')])
                task_failed.assert_called_once_with(error)
                self.assertIn('boom', printed)

    def test_debug_raises(self):
        for job, syncer_cls, method, _message, _source in JOBS:
            if job in WITHOUT_DEBUG:
                continue
            with self.subTest(job=job), patch.object(inits, 'log') as log:
                error = CmkException('boom')
                with self.assertRaises(CmkException) as caught:
                    self._run(job, syncer_cls, method, error, debug=True)
                self.assertIs(caught.exception, error)
                log.log.assert_not_called()

    def test_other_errors_only_caught_where_intended(self):
        broad = {'export_tags', 'export_downtimes', 'export_service_labels'}
        for job, syncer_cls, method, _message, _source in JOBS:
            with self.subTest(job=job), patch.object(inits, 'log'), \
                    patch.object(inits, 'task_failed'):
                error = ValueError('boom')
                if job in broad:
                    _mock_cls, printed = self._run(job, syncer_cls, method, error)
                    self.assertIn('Error: boom', printed)
                else:
                    with self.assertRaises(ValueError):
                        self._run(job, syncer_cls, method, error)


if __name__ == '__main__':
    unittest.main()
