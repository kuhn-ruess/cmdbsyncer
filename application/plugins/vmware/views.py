"""
Vmware Rule Views
"""
from flask_login import current_user
from application.modules.rule.views import RuleModelView
from application.modules.rule.list_source_views import ListSourceViewMixin


class VMwareCustomAttributeView(ListSourceViewMixin, RuleModelView):  # pylint: disable=too-many-ancestors
    """
    Custom Rule Model View
    """
    list_source_creates = 'set of custom attributes'
    list_source_help_items = (
        'The column <code>hostname</code> (or <code>name</code>) names the '
        'virtual machine the attributes are written to, a row without it '
        'writes none.',
    )
    list_source_outcome = ('Custom Attributes', 'The vCenter custom attributes to write.')
    list_source_template_fields = (('attribute_value', 'Attribute Value'),)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('vmware')
