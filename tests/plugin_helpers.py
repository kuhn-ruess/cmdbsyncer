"""
Shared setup for the `Plugin.get_attributes` tests.

Building the plugin with its three rule engines stubbed out is the same
half dozen lines in every attribute test, in this file and in
`test_template_merge_fields`, so it lives here once.
"""
from unittest.mock import Mock

from application.modules.plugin import Plugin


def plain_plugin():
    """
    A Plugin whose rule engines contribute nothing: no custom
    attributes, no rewrite rules and no filter. What comes out of
    `get_attributes` is then the host's own data plus its templates.
    """
    plugin = Plugin()
    plugin.custom_attributes = Mock()
    plugin.custom_attributes.get_outcomes.return_value = {}
    plugin.init_custom_attributes = Mock()
    plugin.rewrite = None
    plugin.filter = None
    return plugin
