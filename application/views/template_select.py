"""
Shared CMDB-template multi-select form field.

The template-side counterpart of `account_select`: a user can be scoped to
a set of CMDB templates (`User.restrict_to_templates`), stored as a plain
list of template names. The widget and its choice source live here so
every view that offers such a scope picks from the same list.
"""
from flask_admin.form.widgets import Select2Widget
from wtforms import SelectMultipleField

from application.models.host_templates import assignable_templates


def template_choices():
    """All active CMDB templates as (name, name) pairs, ordered by name."""
    return [(template.hostname, template.hostname)
            for template in assignable_templates().only('hostname')
                                                  .order_by('hostname')]


class TemplatesMultiSelectField(SelectMultipleField):
    """Multi-select of CMDB templates, stored as a list of template names."""
    # Select2 chips for the same reason the account picker uses them: the
    # native multi-select needs Ctrl/Cmd-click and is near-invisible on the
    # dark themes.
    widget = Select2Widget(multiple=True)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', template_choices)
        # Tolerate a saved name whose template was since archived/removed.
        kwargs.setdefault('validate_choice', False)
        super().__init__(*args, **kwargs)
