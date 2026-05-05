"""
WTForms widgets/fields used by the Host model views.

Extracted from `application.views.host` to keep the main module focused on
ModelView wiring; the widgets here are pure presentation and have no
dependency on Flask-Admin or the Host model itself, so they round-trip
cleanly into their own file.
"""
from markupsafe import Markup, escape
from wtforms import Field


class StaticLabelWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Lablels in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        entries = []
        for key, value in field.data.items():
            html_entry = ""
            html_entry += f'<span class="badge badge-primary">{escape(key)}</span>:'
            html_entry += f'<span class="badge badge-info">{escape(value)}</span>'
            entries.append(html_entry)
        html += ", ".join(entries)
        html += "</div></div>"
        return Markup(html)


class StaticLabelField(Field):
    """
    Helper for Widget
    """
    widget = StaticLabelWidget()

    def _value(self):
        return str(self.data) if self.data else ''


class StaticTemplateLabelWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Template Labels in Views
    """
    _INTRO = (
        '<p class="text-muted small" style="margin-bottom:6px;">'
        '<i class="fa fa-info-circle"></i> '
        'These labels originate from the templates assigned above. They '
        'are read-only here and are merged into the host labels at export '
        'time — manual labels below win on conflicts.'
        '</p>'
    )

    def __call__(self, field, **kwargs):
        model = field.object_data
        if not model or not hasattr(model, 'cmdb_templates') or not model.cmdb_templates:
            return Markup(
                self._INTRO
                + '<div class="alert alert-info">'
                'No templates assigned — no template labels apply.'
                '</div>'
            )

        html = self._INTRO
        had_entries = False
        for template in model.cmdb_templates:
            if not hasattr(template, 'labels') or not template.labels:
                continue
            had_entries = True
            entries = [
                f'<span class="badge badge-primary">{escape(key)}</span>'
                f':<span class="badge badge-info">{escape(value)}</span>'
                for key, value in template.labels.items()
            ]
            html += (
                f'<div class="card" style="margin-bottom:4px; '
                f'border-left: 3px solid #3498db;">'
                f'<div class="card-header p-1" '
                f'style="background-color:#eef6fc;">'
                f'<i class="fa fa-clone"></i> '
                f'<strong>{escape(template.hostname)}</strong>'
                f'</div>'
                f'<div class="card-body p-2">{" ".join(entries)}</div>'
                f'</div>'
            )
        if had_entries:
            return Markup(html)
        return Markup(
            self._INTRO
            + '<div class="alert alert-warning">'
            'Assigned templates carry no labels.'
            '</div>'
        )


class StaticTemplateLabelField(Field):
    """
    Helper for Widget
    """
    widget = StaticTemplateLabelWidget()

    def _value(self):
        return str(self.data) if self.data else ''


class CmdbMatchWidget:  # pylint: disable=too-few-public-methods
    """
    Widget for CMDB Match key:value input with styling
    """
    def __call__(self, field, **kwargs):
        # Split existing value if any
        key = ""
        value = ""
        if field.data and ':' in field.data:
            key, value = field.data.split(':', 1)

        html = f'''
        <div class="cmdb-match-container" style="margin-bottom: 15px;">
            <div class="form-row align-items-center">
                <div class="col-auto">
                    <input type="text" id="cmdb_match_key"
                           value="{escape(key)}" placeholder="Key"
                           style="background-color: #2EFE9A;
                                  border-radius: 5px; padding: 8px 12px;
                                  font-weight: bold;
                                  border: 1px solid #1abc9c;
                                  margin-right: 10px; width: 150px;">
                </div>
                <div class="col-auto">
                    <input type="text" id="cmdb_match_value"
                           value="{escape(value)}" placeholder="Value"
                           style="background-color: #81DAF5;
                                  border-radius: 5px; padding: 8px 12px;
                                  font-family: monospace;
                                  border: 1px solid #3498db;
                                  width: 200px;">
                </div>
            </div>
            <input type="hidden"
                   name="{escape(field.name)}"
                   id="{escape(field.id)}"
                   value="{escape(field.data or '')}" />
            <small class="form-text text-muted">Enter Attribute which should lead to automatic match</small>
        </div>
        <script>
        function updateCmdbMatch() {{
            var key = document.getElementById('cmdb_match_key').value;
            var value = document.getElementById('cmdb_match_value').value;
            var hiddenField = document.getElementById('{escape(field.id)}');

            if (key && value) {{
                hiddenField.value = key + ':' + value;
            }} else {{
                hiddenField.value = '';
            }}
        }}

        document.getElementById('cmdb_match_key').addEventListener('input', updateCmdbMatch);
        document.getElementById('cmdb_match_value').addEventListener('input', updateCmdbMatch);
        </script>
        '''
        return Markup(html)


class CmdbMatchField(Field):
    """
    Custom field for CMDB Match key:value input
    """
    widget = CmdbMatchWidget()

    def _value(self):
        return str(self.data) if self.data else ''


class StaticLogWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Lists in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        html += "<table class='table'>"
        for line in field.data:
            html += f"<tr><td>{escape(line[:160])}</td></tr>"
        html += "</table>"
        html += "</div></div>"
        return Markup(html)


class StaticLogField(Field):
    """
    Helper for Widget
    """
    widget = StaticLogWidget()

    def _value(self):
        return str(self.data) if self.data else ''
