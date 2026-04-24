"""
Shared section-card scaffolding for modernized admin edit forms.

Every config-heavy edit form in the admin (rule forms, account form,
notification/backup configs, …) tends to break down into three or
four logical steps: Main Options / Basics → Conditions or Access →
Outcomes or Plugin Settings. Rather than style each form separately,
this module produces consistent accented-card wrappers via
`rules.HTML` snippets that any Flask-Admin ModelView can drop into
its `form_rules`.

Usage:

    from application.views._form_sections import (
        MODERN_FORM_CSS, modern_form, section,
    )

    form_rules = modern_form(
        section('1', 'main',  'Basics',   'Name, type …',      [fields…]),
        section('2', 'cond',  'Access',   'How to connect …',  [fields…]),
        section('3', 'out',   'Plugins',  'Per-plugin tweaks', [fields…]),
    )

The colour / badge mapping:
    main (blue)   — the "what is it" step
    cond (orange) — the "when / how" step
    out  (green)  — the "what happens" step
    aux  (grey)   — optional extra card for auxiliary content
"""
from markupsafe import escape
from flask_admin.form import rules


MODERN_FORM_CSS = '''
<style>
.rule-form-sections { display: flex; flex-direction: column; gap: 14px;
    margin: 8px 0 16px; }
.rule-section { border: 1px solid #e2e6ea; border-radius: 10px;
    background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    overflow: hidden; }
.rule-section-head { display: flex; align-items: center; gap: 12px;
    padding: 10px 14px; border-bottom: 1px solid #eef0f3;
    background: #f8f9fa; }
.rule-section-head .rule-step { flex: 0 0 auto; display: inline-flex;
    align-items: center; justify-content: center; width: 28px; height: 28px;
    border-radius: 50%; font-weight: bold; color: #fff; font-size: 0.9rem;
    font-family: ui-monospace, monospace; }
.rule-section-head h4 { margin: 0; font-size: 1.05rem; color: #2c3e50; }
.rule-section-head p { margin: 0; font-size: 0.82rem; color: #6c757d; }
.rule-section-body { padding: 12px 14px; }
.rule-section-body > .form-group:last-child { margin-bottom: 0; }

.rule-section-main { border-left: 4px solid #3498db; }
.rule-section-main .rule-step { background: #3498db; }
.rule-section-cond { border-left: 4px solid #e67e22; }
.rule-section-cond .rule-step { background: #e67e22; }
.rule-section-out  { border-left: 4px solid #27ae60; }
.rule-section-out  .rule-step { background: #27ae60; }
.rule-section-aux  { border-left: 4px solid #6c757d; }
.rule-section-aux  .rule-step { background: #6c757d; }

/* Flask-Admin inline-field-list cards nested in any modernised step. */
[id^="conditions-"] > legend,
[id^="outcomes-"] > legend,
[id^="rewrite_attributes-"] > legend,
[id^="custom_fields-"] > legend,
[id^="plugin_settings-"] > legend { display: none !important; }
[id^="conditions-"] .inline-field > legend > small,
[id^="outcomes-"] .inline-field > legend > small,
[id^="rewrite_attributes-"] .inline-field > legend > small,
[id^="custom_fields-"] .inline-field > legend > small,
[id^="plugin_settings-"] .inline-field > legend > small {
    font-size: 0 !important;
}
[id^="conditions-"] .inline-field > legend > small .pull-right,
[id^="outcomes-"] .inline-field > legend > small .pull-right,
[id^="rewrite_attributes-"] .inline-field > legend > small .pull-right,
[id^="custom_fields-"] .inline-field > legend > small .pull-right,
[id^="plugin_settings-"] .inline-field > legend > small .pull-right {
    font-size: 1rem !important;
}
[id^="conditions-"] .inline-field.card,
[id^="outcomes-"] .inline-field.card,
[id^="rewrite_attributes-"] .inline-field.card,
[id^="custom_fields-"] .inline-field.card,
[id^="plugin_settings-"] .inline-field.card {
    border: 1px solid #e6e9ec !important;
    background: #fbfcfd !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    padding: 10px 12px !important;
    margin-bottom: 10px !important;
    position: relative;
}
[id^="conditions-"] .inline-field.card > legend,
[id^="outcomes-"] .inline-field.card > legend,
[id^="rewrite_attributes-"] .inline-field.card > legend,
[id^="custom_fields-"] .inline-field.card > legend,
[id^="plugin_settings-"] .inline-field.card > legend {
    position: absolute !important; top: 4px; right: 6px;
    padding: 0 !important; margin: 0 !important; border: none !important;
    width: auto !important;
}
[id^="conditions-"] .form-group,
[id^="outcomes-"] .form-group,
[id^="rewrite_attributes-"] .form-group,
[id^="custom_fields-"] .form-group,
[id^="plugin_settings-"] .form-group { margin-bottom: 6px !important; }
[id^="conditions-"] > a.btn,
[id^="outcomes-"] > a.btn,
[id^="rewrite_attributes-"] > a.btn,
[id^="custom_fields-"] > a.btn,
[id^="plugin_settings-"] > a.btn {
    background: #f8f9fa !important; border: 1px solid #ced4da !important;
    color: #2c3e50 !important; font-size: 0.88rem !important;
    padding: 4px 12px !important;
}
</style>
'''


def _section_open(step, kind, title, desc):
    return rules.HTML(
        f'<section class="rule-section rule-section-{kind}">'
        f'  <header class="rule-section-head">'
        f'    <span class="rule-step">{escape(step)}</span>'
        f'    <div><h4>{escape(title)}</h4>'
        f'    <p>{escape(desc)}</p></div>'
        f'  </header>'
        f'  <div class="rule-section-body">'
    )


_section_close = rules.HTML('</div></section>')
_sections_open = rules.HTML('<div class="rule-form-sections">')
_sections_close = rules.HTML('</div>')


def section(step, kind, title, desc, field_rules):
    """Return a list of form_rules entries wrapping `field_rules`
    in one accented step card."""
    return [_section_open(step, kind, title, desc),
            *field_rules,
            _section_close]


def modern_form(*sections):
    """Return the full `form_rules` list: CSS, outer wrapper and every
    section card joined in order."""
    out = [rules.HTML(MODERN_FORM_CSS), _sections_open]
    for sec in sections:
        out.extend(sec)
    out.append(_sections_close)
    return out
