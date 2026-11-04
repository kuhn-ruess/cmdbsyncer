"""Notification rule templates can be written over the web, API and Git, so
they must not reach the interpreter."""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dispatch():
    """Load the module from disk: the test bootstrap stubs ``application``."""
    path = os.path.join(_REPO_ROOT, 'application', 'helpers',
                        'notification_dispatch.py')
    spec = importlib.util.spec_from_file_location('notification_dispatch', path)
    module = importlib.util.module_from_spec(spec)
    stubs = {name: MagicMock() for name in (
        'application.helpers.notification_channels',
        'application.models.notification_channel',
        'application.models.notification_rule',
        'application.models.notification_state',
    )}
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


_render = _load_dispatch()._render  # pylint: disable=protected-access


class NotificationTemplateTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_templates_cannot_reach_python_internals(self):
        for template in (
            "{{ cycler.__init__.__globals__.os.getcwd() }}",
            "{{ ''.__class__.__mro__[1].__subclasses__() }}",
            "{{ title.__class__.__init__.__globals__ }}",
        ):
            with self.subTest(template=template):
                self.assertIsNone(_render(template, {'title': 'x'}))

    def test_documented_templates_still_render(self):
        event = {
            'title': 'Job failed',
            'message': 'Timeout',
            'details': {'requester': 'alice', 'operation': 'delete',
                        'resource_type': 'host', 'resource_name': 'srv1'},
        }
        for template, expected in (
            ("{{ title }}", "Job failed"),
            ('{{ message }}, last: {{ details.last_success_ago or "never" }}',
             "Timeout, last: never"),
            ("Approval needed: {{ details.operation }} {{ details.resource_type }}",
             "Approval needed: delete host"),
            ("{{ details.requester }} on {{ details.resource_name }}",
             "alice on srv1"),
        ):
            with self.subTest(template=template):
                self.assertEqual(_render(template, event), expected)


if __name__ == '__main__':
    unittest.main()
