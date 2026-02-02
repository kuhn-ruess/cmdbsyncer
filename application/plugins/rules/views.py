import json
from application.views.default import DefaultModelView
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_login import current_user
from wtforms.validators import ValidationError
from application.modules.rule.views import (
    get_rule_json,
    _render_jinja,
)

class SyncerRuleAutomationView(DefaultModelView):
    """
    Syncer Rule Automation View
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    column_formatters = {
            'rule_body': _render_jinja,
    }

    column_default_sort = "name"

    column_editable_list = [
        'enabled',
    ]

    column_filters = (
       FilterLike(
            "name",
           'Rule Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    form_widget_args = {
        'rule_body' : {"rows": 10},
    }


    def on_model_change(self, form, model, is_created):
        """
        Validation and cleanup when changing the model
        """
        try:
            json.loads(form.rule_body.data)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON in rule_body: {str(e)}")
        
        rule_data = json.loads(form.rule_body.data)
        if isinstance(rule_data, dict) and '_id' in rule_data:
            del rule_data['_id']
            model.rule_body = json.dumps(rule_data, indent=2)

        elif isinstance(rule_data, list):
            # If rule_body is a list of objects
            for item in rule_data:
                if isinstance(item, dict) and '_id' in item:
                    del item['_id']
            model.rule_body= json.dumps(rule_data, indent=2)
        
        super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('admin')