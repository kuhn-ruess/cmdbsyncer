"""
Host Model View

Helpers (form widgets, Mongo filters) live in sibling modules:
  - `host_widgets`  — WTForms widgets/fields (StaticLabelField, ...)
  - `host_filters`  — BaseMongoEngineFilter subclasses (FilterHostnameRegex, ...)
"""
# pylint: disable=too-many-lines,duplicate-code
from datetime import datetime
import csv
import io
from flask_login import current_user
from flask import flash, request, redirect, url_for, render_template, Response
from flask_admin.model.template import EndpointLinkRowAction, LinkRowAction
from flask_admin.form import rules
from flask_admin.actions import action
from flask_admin.base import expose
from wtforms import HiddenField, StringField, BooleanField
from wtforms.validators import Optional
from markupsafe import escape
from mongoengine.errors import DoesNotExist

# pylint: disable=import-error
from application.plugins.checkmk.models import CheckmkFolderPool
from application.plugins.checkmk import (
    get_host_debug_data as cmk_host_debug,
    get_rule_preview as cmk_rule_preview,
)
from application.plugins.checkmk.cmk_rules import get_preview_providers
from application.plugins.netbox import get_device_debug_data as netbox_host_debug
from application.plugins.ansible import get_ansible_debug_data as ansible_host_debug
from application.plugins.idoit import get_idoit_debug_data as idoit_host_debug
from application.plugins.vmware import get_vmware_debug_data as vmware_host_debug
from application import app, logger
from application.views.default import DefaultModelView
from application.views.host_widgets import (
    StaticLabelField,
    StaticTemplateLabelField,
    CmdbMatchField,
    StaticLogField,
)
from application.views.host_filters import (
    FilterAccountRegex,
    FilterHostnameRegex,
    FilterLifecycleState,
    FilterObjectType,
    FilterPoolFolder,
    FilterStale,
    FilterCmdbTemplate,
    FilterLabelKeyAndValue,
    FilterInventoryKeyAndValue,
    HostnameAndLabelSearchMixin,
)
from application.views.host_renderers import (
    format_cache,
    format_inventory,
    format_labels,
    format_log,
    get_rule_json,
    _render_cmdb_fields,
    _render_cmdb_fields_preview,
    _render_cmdb_match_label,
    _render_cmdb_template,
    _render_cmdb_template_preview,
    _render_datetime,
    _render_inventory_grid,
    _render_labels,
    _render_labels_with_origin,
    _render_lifecycle_state,
    _render_log_grid,
    _render_object_type_icon,
    _render_relations,
    _render_relations_preview,
)
from application.views.saved_search import SavedSearchRoutesMixin
from application.models.host import (
    Host, CmdbField, HostLabelChange, LIFECYCLE_STATES,
)
from application.models.config import Config
# pylint: enable=import-error

div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")


# Fields that only make sense when the syncer is in CMDB mode. Stripped
# from list/detail/filter/form when CMDB_MODE is off so the syncer-only
# install gets a clean, minimal Host UI.
_CMDB_ONLY_FIELDS = ('lifecycle_state', 'relations', 'is_stale', 'stale_since')


def _strip_cmdb_form_rules(rule_list, drop_fields):
    """
    Walk a flask_admin form_rules tree and drop every `rules.Field`
    entry whose name is in `drop_fields`. Containers (FieldSet,
    NestedRule) are recursed into; empty containers are removed.
    """
    out = []
    for entry in rule_list:
        if isinstance(entry, rules.Field):
            if entry.field_name in drop_fields:
                continue
            out.append(entry)
            continue
        sub = getattr(entry, 'rules', None)
        if sub is None:
            out.append(entry)
            continue
        kept = _strip_cmdb_form_rules(sub, drop_fields)
        if not kept:
            continue
        entry.rules = kept
        out.append(entry)
    return out


def get_debug(hostname, mode):
    """
    Get Output for Host Debug Page
    """

    # Check permissions based on debug mode
    mode_role_mapping = {
        'checkmk_host': 'checkmk',
        'netbox_device': 'netbox',
        'ansible_host': 'ansible',
        'idoit_host': 'idoit',
        'vmware_host': 'vmware',
    }

    required_role = mode_role_mapping.get(mode)
    if required_role and not current_user.has_right(required_role):
        return {'Error': f"You need the '{required_role}' role to access {mode} debug mode"}, {}

    try:
        Host.objects.get(hostname=hostname)

        output = {}
        output_rules = {}

        debug_funcs = {
            'checkmk_host': cmk_host_debug,
            'netbox_device': netbox_host_debug,
            'ansible_host': ansible_host_debug,
            'idoit_host': idoit_host_debug,
            'vmware_host': vmware_host_debug,
        }

        attributes, actions, debug_log = debug_funcs[mode](hostname)

        for type_name, data in debug_log.items():
            output_rules[type_name] = data

        if attributes:
            output["Full Attribute List"] = attributes['all']
            if attributes.get('filtered'):
                output["Filtered"] = attributes['filtered']
            output["Outcomes"] =  actions
            additional_attributes = {}
            additional_attributes =  actions.get('custom_attributes', {})

            for additional_attr in actions.get('attributes',[]):
                if attr_value := attributes['all'].get(additional_attr):
                    additional_attributes[additional_attr] = attr_value
            if additional_attributes:
                output["Custom Attributes"] = additional_attributes
        else:
            output["Info: Host disabled by Filter"] = None
        return output, output_rules
    except DoesNotExist:
        return {'Error': "Host not found in Database"}, {}


def _find_rule_match(rules_by_group, raw_id):
    """
    Look up a rule's hit/no-match info from the per-group rules dict
    that the debug page already builds. Returns a small dict with
    `hit`, `no_match_reason` and `condition_type`, or None if the rule
    is not present (e.g. a rule type that doesn't appear in this host's
    debug output).
    """
    for group_rules in rules_by_group.values():
        for rule_row in group_rules:
            if str(rule_row.get('id')) == raw_id:
                return {
                    'hit': bool(rule_row.get('hit')),
                    'no_match_reason': rule_row.get('no_match_reason'),
                    'condition_type': rule_row.get('condition_type'),
                }
    return None


def _safe_return_to(candidate, fallback_endpoint='.index_view'):
    """
    Validate a `return_to` URL coming from a query/form param and return
    it iff it points back at this server's admin (relative URL or same
    host). Used by the bulk-action processors so users land on the same
    list page (with their pagination/filters) instead of the first page
    of an unfiltered listing. Anything looking like an open redirect
    falls back to `fallback_endpoint`.
    """
    if not candidate:
        return url_for(fallback_endpoint)
    candidate = str(candidate).strip()
    # Reject scheme/netloc-bearing URLs and protocol-relative URLs —
    # only same-app relative paths are accepted.
    if candidate.startswith('//') or '://' in candidate:
        return url_for(fallback_endpoint)
    if not candidate.startswith('/'):
        return url_for(fallback_endpoint)
    return candidate


def _render_copy_as_new_form(view, label):
    """
    Render the new-hostname modal for the copy-as-new row action.

    `label` is the user-facing noun ("Host" / "Object") that decides
    only the wording of the not-found flash. The HTML template is the
    same for every view.
    """
    source_id = request.args.get('source_id', '')
    source = Host.objects(id=source_id).first() if source_id else None
    if not source:
        flash(f'{label} not found.', 'error')
        return redirect(url_for('.index_view'))
    return view.render(
        'admin/copy_as_new_form.html',
        source=source,
        default_name=f'{source.hostname}-copy',
    )


def _process_copy_as_new(label):
    """
    Clone the source Host under the new hostname.

    Used by both HostModelView and ObjectModelView. `label` only varies
    the wording of flash messages — the cloning itself is identical
    because Object/Template/Host all live in the same Host collection.
    """
    source_id = request.form.get('source_id', '')
    new_name = (request.form.get('new_hostname') or '').strip()
    if not source_id or not new_name:
        flash('Missing source or new hostname.', 'error')
        return redirect(url_for('.index_view'))
    if Host.objects(hostname=new_name).first():
        flash(f'{label} {new_name!r} already exists.', 'error')
        return redirect(url_for('.index_view'))
    source = Host.objects(id=source_id).first()
    if not source:
        flash(f'{label} not found.', 'error')
        return redirect(url_for('.index_view'))

    clone = Host()
    clone.hostname = new_name
    clone.object_type = source.object_type
    clone.is_object = source.is_object
    clone.no_autodelete = source.no_autodelete
    clone.source_account_name = source.source_account_name or 'cmdb'
    clone.source_account_id = ''
    clone.labels = dict(source.labels or {})
    clone.cmdb_fields = [
        CmdbField(field_name=f.field_name, field_value=f.field_value)
        for f in (source.cmdb_fields or [])
    ]
    clone.cmdb_templates = list(source.cmdb_templates or [])
    clone.cmdb_match = source.cmdb_match
    clone.lifecycle_state = source.lifecycle_state or 'active'
    clone.last_import_sync = datetime.now()
    clone.last_import_seen = datetime.now()
    clone.save()

    flash(f'Copied to new {label.lower()} {new_name!r}.', 'success')
    return redirect(url_for('.edit_view', id=str(clone.pk)))


def _build_tree_view(tree):
    """
    Shape a HostInventoryTree document for the CMDB Tree template:
    sorted current paths, plus an added / removed / changed diff against
    the previous snapshot. Returns a plain dict so the template doesn't
    have to call methods on a mongoengine document.
    """
    current = {p.path: p.value for p in (tree.paths or [])}
    previous = {p.path: p.value for p in (tree.previous_paths or [])}

    added_keys = sorted(set(current) - set(previous))
    removed_keys = sorted(set(previous) - set(current))
    changed_keys = sorted(
        k for k in current.keys() & previous.keys()
        if current[k] != previous[k]
    )

    return {
        'source': tree.source,
        'last_update': tree.last_update,
        'previous_update': tree.previous_update,
        'entries': sorted(
            ({'path': p, 'value': v} for p, v in current.items()),
            key=lambda e: e['path'],
        ),
        'diff': {
            'added': [{'path': k, 'value': current[k]} for k in added_keys],
            'removed': [{'path': k, 'value': previous[k]} for k in removed_keys],
            'changed': [
                {'path': k, 'old': previous[k], 'new': current[k]}
                for k in changed_keys
            ],
        },
        'has_diff': bool(
            tree.previous_update and (added_keys or removed_keys or changed_keys)
        ),
    }


class _SoftDeleteHostMixin:
    """
    Replace per-row / bulk Delete with `Host.soft_delete`. Hard delete
    stays reachable from the Archive view's admin-only action. Used by
    every Flask-Admin view that lists Host documents (Hosts, Objects,
    Templates) so their delete buttons all behave consistently.
    """
    # pylint: disable=too-few-public-methods

    def delete_model(self, model):
        """Soft-delete the host instead of removing the document."""
        # Best-effort hook chain for any subclass-specific cleanup
        # (e.g. Checkmk pool seat accounting in HostModelView).
        try:
            self.on_model_delete(model)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        actor = getattr(current_user, 'email', None) or 'web UI'
        model.soft_delete(reason=f"deleted via UI by {actor}")
        model.save()
        flash(
            f'"{getattr(model, "hostname", "object")}" archived '
            '(soft-deleted). Restore or hard-delete from Objects → Archive.',
            'success',
        )
        return True


class _LifecycleBulkActionsMixin:
    """
    Bulk actions and `lifecycle_state` form/filter/column wiring shared
    across HostModelView and ObjectModelView. Subclasses still own the
    rest of their layout — this mixin only owns lifecycle.
    """
    # pylint: disable=too-few-public-methods

    def _bulk_set_lifecycle(self, ids, new_state):
        changed = 0
        for host in Host.objects(id__in=ids):
            if host.set_lifecycle_state(new_state):
                host.save()
                changed += 1
        flash(f'Lifecycle state set to "{new_state}" on {changed} object(s).',
              'success')
        return redirect(request.referrer or url_for('.index_view'))

    @action('lifecycle_planned', 'Lifecycle: Planned', None)
    def action_lifecycle_planned(self, ids):
        """Mark selection as planned."""
        return self._bulk_set_lifecycle(ids, 'planned')

    @action('lifecycle_staged', 'Lifecycle: Staged', None)
    def action_lifecycle_staged(self, ids):
        """Mark selection as staged."""
        return self._bulk_set_lifecycle(ids, 'staged')

    @action('lifecycle_active', 'Lifecycle: Active', None)
    def action_lifecycle_active(self, ids):
        """Mark selection as active."""
        return self._bulk_set_lifecycle(ids, 'active')

    @action('lifecycle_decommissioned', 'Lifecycle: Decommissioned', None)
    def action_lifecycle_decommissioned(self, ids):
        """Mark selection as decommissioned."""
        return self._bulk_set_lifecycle(ids, 'decommissioned')

    @action('lifecycle_archived', 'Lifecycle: Archived', None)
    def action_lifecycle_archived(self, ids):
        """Mark selection as archived."""
        return self._bulk_set_lifecycle(ids, 'archived')


class ObjectModelView(_SoftDeleteHostMixin,  # pylint: disable=too-many-ancestors,too-many-instance-attributes
                      _LifecycleBulkActionsMixin,
                      HostnameAndLabelSearchMixin, DefaultModelView):
    """
    Onlye show objects
    """

    can_create = True
    can_edit = True
    can_export = True
    can_view_details = True

    column_details_list = [
        'hostname', 'no_autodelete', 'lifecycle_state',
        'inventory', 'labels', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
        'cmdb_templates',
        'sync_id',
        'cmdb_match',
        'last_import_id',
        'create_time',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
        'lifecycle_state_changed_at',
    ]

    column_export_list = ('hostname', )

    column_filters = (
       FilterHostnameRegex(
        Host,
        "Hostname",
       ),
       FilterObjectType(
        Host,
        "Object Type",
       ),
       FilterAccountRegex(
           Host,
           'Account',
       ),
       FilterLabelKeyAndValue(
        Host,
        "Label Key:Value"
       ),
       FilterInventoryKeyAndValue(
        Host,
        "Inventory Key:Value"
       ),
       FilterLifecycleState(
           Host,
           'Lifecycle State',
           options=LIFECYCLE_STATES,
       ),
    )

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_fields': _render_cmdb_fields_preview,
        'cmdb_match': _render_cmdb_match_label,
        'object_type': _render_object_type_icon,
        'lifecycle_state': _render_lifecycle_state,
    }

    # Detail view uses the rich Key / Value / Type table; the list
    # view stays compact with the badge preview above.
    column_formatters_detail = {
        'log': _render_log_grid,
        'labels': _render_labels_with_origin,
        'inventory': _render_inventory_grid,
        'cache': format_cache,
        'cmdb_fields': _render_cmdb_fields,
        'cmdb_match': _render_cmdb_match_label,
        'object_type': _render_object_type_icon,
        'lifecycle_state': _render_lifecycle_state,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'hostname': "Object Name",
        'source_account_name': "Account",
        'cmdb_fields': "CMDB Attributes",
        'lifecycle_state': "Lifecycle",
    }

    export_types = ['syncer_rules',]

    form_overrides = {
        'inventory': StaticLabelField,
        'log': StaticLogField,
        'hostname': StringField,
        'cmdb_match': CmdbMatchField,
    }

    form_rules = [
        rules.HTML('''
        <style>
        [id^="cmdb_fields-"] legend { border: none !important; padding: 0 !important; margin: 0 0 4px 0 !important; }
        [id^="cmdb_fields-"] legend small { font-size: 0 !important; }
        [id^="cmdb_fields-"] legend small .pull-right { font-size: 1rem !important; }
        [id^="cmdb_fields-"] .card {
            margin-bottom: 8px !important;
            padding: 10px !important;
            background-color: #f8f9fa !important;
            border-radius: 8px !important;
        }
        [id^="cmdb_fields-"] label { display: none !important; }
        [id^="cmdb_fields-"] .form-group { margin-bottom: 0 !important; }
        [id^="cmdb_fields-"] .inline-field { margin-bottom: 8px !important; }
        </style>
        '''),
        rules.Field('hostname'),
        rules.Field('object_type'),
        rules.Field('lifecycle_state'),
        rules.FieldSet(('cmdb_fields',), "CMDB Fields"),
    ]

    form_args = {
        "hostname": {
            "label": 'Object Name'
        },
        "object_type": {
            "label": 'Object Type'
        },
        "cmdb_match": {
            "label": 'CMDB Match Rule'
        }
    }

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {
                            'style': (
                                'background-color: #2EFE9A; '
                                'border-radius: 5px; '
                                'padding: 6px 10px; '
                                'margin-right: 5px; '
                                'font-weight: bold; '
                                'border: 1px solid #1abc9c; '
                                'width: 220px;'
                            ),
                            'size': 20,
                            'placeholder': 'Key'
                        },
                        'field_value': {
                            'style': (
                                'background-color: #81DAF5; '
                                'border-radius: 5px; '
                                'padding: 6px 10px; '
                                'font-family: monospace; '
                                'margin-left: 5px; '
                                'border: 1px solid #3498db; '
                                'width: 450px;'
                            ),
                            'size': 40,
                            'placeholder': 'Value'
                        },
                    },
                    'form_rules': [
                        rules.HTML(
                            '<div class="form-row '
                            'align-items-center" '
                            'style="margin-bottom: 5px; '
                            'margin-top: 0;">'
                        ),
                        rules.HTML('<div class="col-auto">'),
                        rules.Field('field_name'),
                        rules.HTML('</div>'),
                        rules.HTML(
                            '<div class="col-auto">'
                            '<span style="font-size: 16px;'
                            ' margin: 0 3px;">:</span>'
                            '</div>'
                        ),
                        rules.HTML('<div class="col-auto">'),
                        rules.Field('field_value'),
                        rules.HTML('</div>'),
                        rules.HTML('</div>'),
                    ]
                }
            }
        }
    }

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status

        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.can_delete = False
            self.column_exclude_list.append('CMDB Attributes')
            self.column_exclude_list.append('cmdb_fields')
            self._strip_cmdb_only_ui()

        super().__init__(model, **kwargs)

    def _strip_cmdb_only_ui(self):
        """
        Hide lifecycle/relations columns, filters and form rules.
        Copies class-level dicts/lists first so the mutation does not
        leak into other view instances of the same class.
        """
        self.column_formatters = dict(self.column_formatters)
        self.column_formatters_detail = dict(self.column_formatters_detail)
        self.column_labels = dict(self.column_labels)
        self.column_exclude_list = list(self.column_exclude_list)
        # Drop the Relations graph row icon — the route is CMDB-only.
        self.column_extra_row_actions = [
            a for a in (self.column_extra_row_actions or [])
            if 'relations_graph' not in getattr(a, 'url', '')
        ]
        for col in _CMDB_ONLY_FIELDS:
            self.column_formatters.pop(col, None)
            self.column_formatters_detail.pop(col, None)
            self.column_labels.pop(col, None)
            if col not in self.column_exclude_list:
                self.column_exclude_list.append(col)
        self.column_details_list = [
            c for c in self.column_details_list if c not in _CMDB_ONLY_FIELDS
        ]
        self.column_filters = tuple(
            f for f in self.column_filters
            if not isinstance(f, (FilterLifecycleState, FilterStale))
        )
        self.form_rules = _strip_cmdb_form_rules(
            list(self.form_rules), set(_CMDB_ONLY_FIELDS),
        )

    def is_action_allowed(self, name):
        if name.startswith('lifecycle_') and not app.config.get('CMDB_MODE'):
            return False
        return super().is_action_allowed(name)

    def get_export_name(self, _export_type):  # pylint: disable=signature-differs
        """
        Generates a filename for exporting data based on the model name and current timestamp.

        Args:
            export_type: The type of export being performed (currently unused).

        Returns:
            str: A string representing the export filename in the format
                 '<ModelName>_<YYYYMMDDHHMM>.syncer_json'.
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True, object_type__ne='template',
                            deleted_at__exists=False)

    # Subclasses (e.g. TemplateModelView) set this so on_model_change
    # stamps the right object_type. None = "leave whatever the form had".
    _force_object_type = None

    def on_model_change(self, form, model, _is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.is_object = True
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
        if self._force_object_type is not None:
            model.object_type = self._force_object_type
        new_labels = {x['field_name']: x['field_value'] for x in form.cmdb_fields.data}
        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('objects')

    # Copy + Timeline row actions. EndpointLinkRowAction resolves the
    # current view's endpoint at render time, so the URL stays correct
    # regardless of how the view was registered ("Objects" vs.
    # "Objects Templates", with or without spaces). The hand-built URL
    # strings this replaced were case-mismatched against the registered
    # endpoint and broke whenever the front-end didn't case-fold paths.
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-history", ".timeline",
                              title="Show change timeline",
                              id_arg="obj_id"),
        LinkRowAction("fa fa-sitemap",
                      app.config['BASE_PREFIX'] +
                      "admin/host/relations_graph?obj_id={row_id}",
                      title="Relations graph"),
        EndpointLinkRowAction("fa fa-copy", ".copy_as_new_form",
                              title="Copy as new",
                              id_arg="source_id"),
    ]

    # Custom list template adds the Copy-as-new modal + a small JS
    # interceptor that hijacks the row icon's click. Without this the
    # icon would navigate to the bare form partial.
    list_template = 'admin/object_list.html'

    @expose('/timeline')
    def timeline(self):
        """Reuse HostModelView's timeline renderer for CMDB objects."""
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Object not found.', 'error')
            return redirect(url_for('.index_view'))
        changes = list(HostLabelChange.objects(host=host).order_by('-changed_at')[:500])
        return self.render(
            'admin/host_timeline.html', host=host, changes=changes,
        )

    @expose('/copy_as_new_form')
    def copy_as_new_form(self):
        """Render the new-hostname modal for the copy-as-new row action."""
        return _render_copy_as_new_form(self, 'Object')

    @expose('/copy_as_new_process', methods=['POST'])
    def copy_as_new_process(self):
        """Clone the source object under the new hostname."""
        return _process_copy_as_new('Object')


class TemplateModelView(ObjectModelView):  # pylint: disable=too-many-ancestors
    """Template Model View for CMDB templates."""

    def is_accessible(self):
        # Templates only exist for CMDB users — hide menu and route
        # entirely when the install is in plain syncer mode.
        if not app.config.get('CMDB_MODE'):
            return False
        return super().is_accessible()

    form_rules = [
        rules.HTML('''
        <style>
        [id^="cmdb_fields-"] legend { border: none !important; padding: 0 !important; margin: 0 0 4px 0 !important; }
        [id^="cmdb_fields-"] legend small { font-size: 0 !important; }
        [id^="cmdb_fields-"] legend small .pull-right { font-size: 1rem !important; }
        [id^="cmdb_fields-"] .card {
            margin-bottom: 8px !important;
            padding: 10px !important;
            background-color: #f8f9fa !important;
            border-radius: 8px !important;
        }
        [id^="cmdb_fields-"] label { display: none !important; }
        [id^="cmdb_fields-"] .form-group { margin-bottom: 0 !important; }
        [id^="cmdb_fields-"] .inline-field { margin-bottom: 8px !important; }
        </style>
        '''),
        rules.Field('hostname'),
        rules.FieldSet(('cmdb_fields', 'cmdb_match'), "CMDB Fields"),
    ]

    column_exclude_list = [
        'source_account_id',
        'cmdb_templates',
        'sync_id',
        'object_type',
        'last_import_seen',
        'create_time',
        'last_import_id',
        'last_import_sync',
        'no_autodelete',
        'source_account_name',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
    ]

    _force_object_type = 'template'

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True, object_type="template")

    def on_model_change(self, form, model, is_created):
        super().on_model_change(form, model, is_created)
        # Editing a template invalidates the rendered Jinja values its
        # consumers carry in `cache`. Wipe those caches in one bulk
        # update so the next sync re-evaluates rules against the new
        # template. Also drop the in-process template-match cache so a
        # changed `cmdb_match` is picked up on the next host save.
        if not is_created:
            Host.objects(cmdb_templates=model.id).update(cache={})
        Host.clear_template_cache()


class HostModelView(_SoftDeleteHostMixin,  # pylint: disable=too-many-public-methods,too-many-ancestors,too-many-instance-attributes
                    _LifecycleBulkActionsMixin,
                    SavedSearchRoutesMixin,
                    HostnameAndLabelSearchMixin,
                    DefaultModelView):
    """
    Host Model
    """
    can_create = True
    can_edit = True
    can_export = True
    can_set_page_size = True
    can_view_details = True

    page_size = app.config['HOST_PAGESIZE']

    # Labels already carry per-row badges showing the originating
    # template (see `_render_labels_with_origin`), so the separate
    # "CMDB" block (cmdb_templates + per-template label dumps) would
    # duplicate the same information. Keep `cmdb_templates` out of the
    # detail list.
    column_details_list = [
        'hostname', 'folder', 'no_autodelete', 'lifecycle_state',
        'relations',
        'labels', 'inventory', 'log',
        'last_import_seen', 'last_import_sync', 'create_time', 'last_import_id',
        'source_account_name', 'raw', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
        'sync_id',
        'cmdb_fields',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
        'last_import_id',
        'last_import_sync',
        'cmdb_match',
        'lifecycle_state_changed_at',
        'is_stale',
        'stale_since',
        'deleted_at',
        'delete_reason',
    ]


    column_export_list = ('hostname', )

    column_extra_row_actions = [
        LinkRowAction("fa fa-bug", app.config['BASE_PREFIX'] + \
                    "admin/host/debug?obj_id={row_id}",
                    title="Debug host"),
        LinkRowAction("fa fa-history", app.config['BASE_PREFIX'] + \
                    "admin/host/timeline?obj_id={row_id}",
                    title="Show change timeline"),
        LinkRowAction("fa fa-sitemap", app.config['BASE_PREFIX'] + \
                    "admin/host/relations_graph?obj_id={row_id}",
                    title="Relations graph"),
        LinkRowAction("fa fa-copy", app.config['BASE_PREFIX'] + \
                    "admin/host/copy_as_new_form?source_id={row_id}",
                    title="Copy as new"),
    ]

    column_filters = (
       FilterHostnameRegex(
        Host,
        "Hostname",
       ),
       FilterAccountRegex(
           Host,
           'Account',
       ),
       FilterLabelKeyAndValue(
        Host,
        "Label Key:Value"
       ),
       FilterInventoryKeyAndValue(
        Host,
        "Inventory Key:Value"
       ),
       FilterCmdbTemplate(
           Host,
           'CMDB Template'
       ),
       FilterPoolFolder(
           Host,
           'CMK Pool Folder'
       ),
       FilterLifecycleState(
           Host,
           'Lifecycle State',
           options=LIFECYCLE_STATES,
       ),
       FilterStale(
           Host,
           'Stale',
           options=(('yes', 'Stale'), ('no', 'Fresh')),
       ),
    )

    column_formatters = {
        'log': format_log,
        'labels': _render_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_templates': _render_cmdb_template_preview,
        'last_import_seen': _render_datetime,
        'last_import_sync': _render_datetime,
        'create_time': _render_datetime,
        'object_type': _render_object_type_icon,
        'lifecycle_state': _render_lifecycle_state,
        'relations': _render_relations_preview,
    }

    # Detail view groups labels by origin (manual vs. each assigned
    # template) so admins can tell at a glance where each value is
    # coming from, and scans cleanly at 50+ labels via the compact
    # two-column grid. Inventory reuses the row style but stays
    # single-column so long values (UUIDs, firmware strings) aren't
    # truncated. Log rows get their own compact scrollable list.
    column_formatters_detail = {
        'log': _render_log_grid,
        'labels': _render_labels_with_origin,
        'inventory': _render_inventory_grid,
        'cache': format_cache,
        'cmdb_templates': _render_cmdb_template,
        'last_import_seen': _render_datetime,
        'last_import_sync': _render_datetime,
        'create_time': _render_datetime,
        'object_type': _render_object_type_icon,
        'lifecycle_state': _render_lifecycle_state,
        'relations': _render_relations,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
        'cmdb_templates': "CMDB",
        'lifecycle_state': "Lifecycle",
        'relations': "Relations",
    }

    column_sortable_list = ('hostname',
                            'lifecycle_state',
                            'last_import_seen',
                            'last_import_sync')

    export_types = ['syncer_rules',]

    form_overrides = {
        'hostname': StringField,
        'last_import_seen': HiddenField,
        'last_import_sync': HiddenField,
        'last_import_id': HiddenField,
        'raw': HiddenField,
        'folder': HiddenField,
        'sync_id': HiddenField,
        'cache': HiddenField,
        'source_account_name': HiddenField,
        'source_account_id': HiddenField,
        'inventory': StaticLabelField,
        'log': StaticLogField,
        'labels': HiddenField,
        # Hosts created/edited here are always of type 'host'. Keep the
        # field in the form as hidden so its value round-trips cleanly,
        # then pin it to 'host' in on_model_change.
        'object_type': HiddenField,
    }

    form_args = {
        'cmdb_templates': {
            'label': 'Assigned Templates',
            'validators': [Optional()],
        },
        'labels_from_template': {
            'label': 'Labels from Templates',
        },
        'cmdb_fields': {
            'label': 'Manual Labels',
        },
    }

    form_rules = [
        rules.FieldSet(
            (
                rules.Field('hostname'),
                rules.Field('lifecycle_state'),
            ),
            "Object",
        ),
        rules.FieldSet(
            (
                rules.HTML('''
<style>
/* Flask-Admin inline-field-list DOM for cmdb_fields (bootstrap4 template):
     <label for="cmdb_fields">Manual Labels</label>
     <div class="inline-field" id="cmdb_fields">
       <div class="inline-field-list">
         <div class="inline-field card card-body bg-light mb-3" id="cmdb_fields-N">
           <legend><small>Manual Labels #N <div class="pull-right">[X]</div></small></legend>
           <div class="clearfix"></div>
           <div class="form-row">
             <div class="form-group"><label>…</label><input class="form-control"></div>
             <div class="form-group"><label>…</label><input class="form-control"></div>
           </div>
         </div>
         ...
       </div>
       <a id="cmdb_fields-button" class="btn btn-primary">Add Manual Labels</a>
     </div>
   Scoped so generic Flask-Admin forms are unaffected. */

/* Outer field label "Manual Labels" — the FieldSet already names the
   section; drop this redundant label. */
label[for="cmdb_fields"] { display: none !important; }

#cmdb_fields .inline-field { position: relative; }

/* Flatten each row card to a plain padded line. */
#cmdb_fields .inline-field.card {
    margin: 0 !important;
    padding: 2px 40px 2px 24px !important;
    /* right padding leaves room for the JS-injected delete X,
       left padding for the drag-handle in the legend. */
    border: none !important;
    box-shadow: none !important;
    background-color: transparent !important;
    border-radius: 0 !important;
}

/* Drag-handle (FA sort icon injected via legend small::before) on the
   LEFT, so it does not collide with the JS delete-X on the right. */
#cmdb_fields .inline-field > legend {
    position: absolute !important;
    top: 4px !important;
    left: 4px !important;
    right: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    width: auto !important;
    line-height: 1 !important;
    font-size: 0 !important;  /* kills "Manual Labels #N" caption */
}
/* The JS-injected .cmdb-inline-remove handles the delete; hide the
   legend's native [X] so we don't show two delete affordances. */
#cmdb_fields .inline-field > legend .pull-right,
#cmdb_fields .inline-field > legend small .pull-right {
    display: none !important;
}
#cmdb_fields .inline-field > legend small { font-size: 0 !important; }
#cmdb_fields .inline-field > .clearfix { display: none !important; }

/* Form-row: horizontal, no wrap, no vertical gap. */
#cmdb_fields .form-row {
    margin: 0 !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    width: 100%;
}
#cmdb_fields .form-group { margin: 0 !important; padding: 0 !important; }
#cmdb_fields .form-group > label { display: none !important; }

/* Field name shrinks to its content width, field value consumes the
   remaining space. `:nth-of-type` instead of `:first/last-child` so the
   selector still binds if Flask-Admin adds a sibling node (error block
   etc.). */
#cmdb_fields .form-row > .form-group:nth-of-type(1) { flex: 0 0 auto; }
#cmdb_fields .form-row > .form-group:nth-of-type(2) {
    flex: 1 1 auto;
    min-width: 0;
    margin-left: 0 !important;
}
#cmdb_fields .form-row > .form-group:nth-of-type(2) input {
    width: 100% !important;
    box-sizing: border-box !important;
}
#cmdb_fields input { padding: 2px 7px !important; height: auto !important; }

/* Two-column grid on wide screens, single column on narrow. */
#cmdb_fields .inline-field-list {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 2px 16px !important;
}
@media (max-width: 992px) {
    #cmdb_fields .inline-field-list { grid-template-columns: 1fr !important; }
}
#cmdb_fields > a.btn { margin-top: 8px; }
</style>
<p class="text-muted small" style="margin: -6px 0 6px 0;">
<i class="fa fa-pencil"></i>
Labels you maintain by hand, plus labels that were seeded from an import
(e.g. CSV). Edit or remove any entry — this list is the single source of
truth for this host. Template-derived labels live in their own section
below and do not appear here.
</p>
'''),
                rules.Field('cmdb_fields'),
            ),
            "Manual Labels (editable)",
        ),
        rules.FieldSet(
            (
                rules.Field('cmdb_templates'),
                rules.Field('labels_from_template'),
            ),
            "Template Labels (read-only)",
        ),
        rules.FieldSet(
            (
                rules.HTML('''
<style>
/* Compact, table-ish layout for the typed Host relations list. Same
   pattern as cmdb_fields above: scope to #relations so generic
   Flask-Admin forms stay untouched. */
label[for="relations"] { display: none !important; }
#relations .inline-field { position: relative; }
#relations .inline-field.card {
    margin: 0 0 4px 0 !important;
    padding: 6px 44px 6px 28px !important;
    /* right pad: JS delete-X; left pad: drag-handle in legend */
    border: 1px solid #e3e6ea !important;
    box-shadow: none !important;
    background-color: #fbfbfc !important;
    border-radius: 4px !important;
}
#relations .inline-field > legend {
    position: absolute !important;
    top: 8px !important;
    left: 6px !important;
    right: auto !important;
    margin: 0 !important; padding: 0 !important; border: none !important;
    width: auto !important; line-height: 1 !important;
    font-size: 0 !important;
}
#relations .inline-field > legend .pull-right,
#relations .inline-field > legend small .pull-right {
    display: none !important;
}
#relations .inline-field > legend small { font-size: 0 !important; }
#relations .inline-field > .clearfix { display: none !important; }
#relations .form-row {
    margin: 0 !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 8px;
    width: 100%;
}
#relations .form-group { margin: 0 !important; padding: 0 !important; }
#relations .form-group > label {
    font-size: 0.7rem !important;
    color: #6c757d !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
    margin: 0 0 1px 0 !important;
    font-weight: 600 !important;
}
#relations .form-row > .form-group:nth-of-type(1) { flex: 0 0 180px; }
#relations .form-row > .form-group:nth-of-type(2) { flex: 1 1 auto; min-width: 0; }
#relations .form-row > .form-group:nth-of-type(3) { flex: 0 0 120px; }
#relations select, #relations input {
    padding: 2px 7px !important;
    height: auto !important;
    font-size: 0.9rem !important;
}
#relations > a.btn { margin-top: 8px; }
</style>
<p class="text-muted small" style="margin: -6px 0 6px 0;">
<i class="fa fa-link"></i>
Typed links from this host to other CMDB objects (depends on, runs on,
member of, ...). Inverse direction is shown on the target host's
Impact Chain.
</p>
'''),
                rules.Field('relations'),
            ),
            "Relations",
        ),
    ]

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {
                            'style': (
                                'background-color: #2EFE9A; '
                                'border-radius: 4px; '
                                'padding: 2px 7px; '
                                'margin-right: 4px; '
                                'font-weight: bold; '
                                'border: 1px solid #1abc9c;'
                            ),
                            'size': 15,
                        },
                        'field_value': {
                            'style': (
                                'background-color: #81DAF5; '
                                'border-radius: 4px; '
                                'padding: 2px 7px; '
                                'font-family: monospace; '
                                'margin-left: 4px; '
                                'border: 1px solid #3498db; '
                                'width: 100%; '
                                'box-sizing: border-box;'
                            ),
                        },
                    },
                    'form_rules': [
                        rules.HTML(
                            '<div class="form-row align-items-center" '
                            'style="margin: 0; flex-wrap: nowrap;">'
                        ),
                        rules.NestedRule(('field_name', 'field_value')),
                        rules.HTML('</div>'),
                    ],
                },
            },
        },
    }

    @expose('/timeline')
    def timeline(self):
        """
        Render a standalone Timeline page for a single host:
        every `HostLabelChange` row, newest first, grouped by day.
        """
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Host not found.', 'error')
            return redirect(url_for('.index_view'))
        changes = list(HostLabelChange.objects(host=host).order_by('-changed_at')[:500])
        return self.render(
            'admin/host_timeline.html',
            host=host,
            changes=changes,
            cmdb_mode=app.config.get('CMDB_MODE', False),
        )

    @expose('/cmdb_tree')
    def cmdb_tree(self):
        """
        Render the full inventory tree(s) for a host. Each
        ``HostInventoryTree`` document attached to the host is rendered
        as one collapsible source section listing every ``path: value``
        pair. The promoted subset stays on the host's regular Inventory
        view; this page is the un-curated raw tree.

        For each tree, computes a diff against the previous snapshot
        (``previous_paths``) so the page can highlight what was added,
        removed or changed in the last import.
        """
        # pylint: disable=import-outside-toplevel
        from application.models.host_inventory_tree import HostInventoryTree
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Host not found.', 'error')
            return redirect(url_for('.index_view'))
        trees = list(
            HostInventoryTree.objects(hostname=host.hostname).order_by('source')
        )
        tree_views = [_build_tree_view(tree) for tree in trees]
        return self.render(
            'admin/host_cmdb_tree.html',
            host=host,
            tree_views=tree_views,
            cmdb_mode=app.config.get('CMDB_MODE', False),
        )

    @expose('/relations_graph')
    def relations_graph(self):
        """Render the interactive Relations graph page for one host."""
        if not app.config.get('CMDB_MODE'):
            flash('Relations graph is only available in CMDB mode.', 'error')
            return redirect(url_for('.index_view'))
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Host not found.', 'error')
            return redirect(url_for('.index_view'))
        return self.render(
            'admin/host_relations_graph.html',
            host=host,
            cmdb_mode=True,
        )

    @expose('/relations_graph_data')
    def relations_graph_data(self):  # pylint: disable=too-many-locals,too-many-branches
        """
        Return nodes/edges around `obj_id` as JSON for vis-network.

        Single hop in both directions: outgoing edges from the focus
        host plus inbound edges that point at it. The frontend can call
        this endpoint again with a neighbour id to expand the graph.
        """
        # pylint: disable=import-outside-toplevel
        from flask import jsonify
        from application.models.host import RELATION_TYPES, RELATION_INVERSE_LABEL
        if not app.config.get('CMDB_MODE'):
            return jsonify({'nodes': [], 'edges': []}), 403
        obj_id = request.args.get('obj_id', '').strip()
        focus = Host.objects(id=obj_id).first() if obj_id else None
        if not focus:
            return jsonify({'nodes': [], 'edges': []})
        type_label = dict(RELATION_TYPES)

        def _node(h, is_focus=False):
            return {
                'id': str(h.pk),
                'label': h.hostname,
                'group': h.object_type or 'host',
                'is_focus': is_focus,
            }

        nodes = {str(focus.pk): _node(focus, is_focus=True)}
        edges = []
        for rel in (focus.relations or []):
            tgt = rel.target_host
            if not tgt:
                continue
            tgt_id = str(tgt.pk)
            nodes.setdefault(tgt_id, _node(tgt))
            edges.append({
                'from': str(focus.pk), 'to': tgt_id,
                'label': type_label.get(rel.type, rel.type),
                'arrows': 'to',
            })
        inbound = Host.objects(
            __raw__={'relations.target_host': focus.pk}
        ).only('hostname', 'object_type', 'relations')
        for src in inbound:
            src_id = str(src.pk)
            if src_id == str(focus.pk):
                continue
            nodes.setdefault(src_id, _node(src))
            for rel in (src.relations or []):
                if rel.target_host and rel.target_host.pk == focus.pk:
                    edges.append({
                        'from': src_id, 'to': str(focus.pk),
                        'label': RELATION_INVERSE_LABEL.get(rel.type, rel.type),
                        'arrows': 'to',
                        'dashes': True,
                    })

        # Template links — opt-in via query param so the graph stays
        # uncluttered for users who don't care about template
        # provenance. A host points at the templates it uses; a
        # template points back at the hosts that consume it.
        if request.args.get('include_templates') == '1':
            if focus.object_type == 'template':
                consumers = Host.objects(cmdb_templates=focus.pk).only(
                    'hostname', 'object_type'
                )
                for c in consumers:
                    cid = str(c.pk)
                    nodes.setdefault(cid, _node(c))
                    edges.append({
                        'from': cid, 'to': str(focus.pk),
                        'label': 'template',
                        'arrows': 'to',
                        'kind': 'template',
                    })
            else:
                for tpl in (focus.cmdb_templates or []):
                    if not tpl:
                        continue
                    tid = str(tpl.pk)
                    nodes.setdefault(tid, _node(tpl))
                    edges.append({
                        'from': str(focus.pk), 'to': tid,
                        'label': 'template',
                        'arrows': 'to',
                        'kind': 'template',
                    })
        return jsonify({'nodes': list(nodes.values()), 'edges': edges})

    @expose('/debug')
    def debug(self):  # pylint: disable=too-many-locals,too-many-branches
        """
        Checkmk specific Debug Page
        """
        host = None
        if obj_id := request.args.get('obj_id'):
            host = Host.objects.get(id=obj_id)
            hostname = host.hostname
        else:
            hostname = request.args.get('hostname', '').strip()
            if hostname:
                host = Host.objects(hostname=hostname).first()
        mode = request.args.get('mode', 'checkmk_host')



        output= {}
        output_rules = {}

        if hostname:
            output, output_rules = get_debug(hostname, mode)

        # Map each rule-group key (as set by the mode-specific debug
        # function) to the Flask-Admin model endpoint. Flask-Admin's
        # default endpoint is `model.__name__.lower()` since none of our
        # add_view() calls override it. Shared across all modes first,
        # then the per-mode specifics win.
        bp = app.config['BASE_PREFIX']
        base_urls = {'CustomAttributes': f"{bp}admin/customattributerule/edit/?id="}
        per_mode = {
            'checkmk_host': {
                'filter':      'checkmkfilterrule',
                'rewrite':     'checkmkrewriteattributerule',
                'actions':     'checkmkrule',
                'Setup Rules': 'checkmkrulemngmt',
            },
            'netbox_device': {
                'rewrite':            'netboxrewriteattributerule',
                'actions':            'netboxcustomattributes',
                'VM Attributes':      'netboxvirtualmachineattributes',
                'Cluster Attributes': 'netboxclusterattributes',
            },
            'ansible_host': {
                'filter':  'ansiblefilterrule',
                'rewrite': 'ansiblerewriteattributesrule',
                'actions': 'ansiblecustomvariablesrule',
            },
            'idoit_host': {
                'rewrite': 'idoitrewriteattributerule',
                'actions': 'idoitcustomattributes',
            },
            'vmware_host': {
                'rewrite': 'vmwarerewriteattributes',
                'actions': 'vmwarecustomattributes',
            },
        }.get(mode, {})
        for group, endpoint in per_mode.items():
            base_urls[group] = f"{bp}admin/{endpoint}/edit/?id="

        new_rules = {}
        for rule_group, rule_data in output_rules.items():
            new_rules.setdefault(rule_group, [])
            for rule in rule_data:
                rule_id = rule.get('id')
                if rule_group in base_urls and rule_id:
                    rule['rule_url'] = f"{base_urls[rule_group]}{rule_id}"
                else:
                    rule['rule_url'] = ''
                new_rules[rule_group].append(rule)

        if "Error" in output:
            output = f"Error: {output['Error']}"

        # Optional rule preview: when an admin picks a rule from any
        # registered Checkmk rule-type, render its outcomes against
        # this host's attributes so the debug page shows what the
        # corresponding export would emit for this host. The dropdown
        # value is encoded as ``"<rule_type>:<id>"`` so a single
        # selector can offer rules from every registered provider.
        rule_preview = None
        rule_preview_error = None
        rule_preview_groups = []
        preview_rule_id = request.args.get('preview_rule_id', '').strip()
        if mode == 'checkmk_host' and current_user.has_right('checkmk'):
            for rule_type, provider in get_preview_providers().items():
                entries = list(
                    provider['model'].objects().only('id', 'name').order_by('name')
                )
                rule_preview_groups.append({
                    'type': rule_type,
                    'label': provider['label'],
                    'entries': entries,
                })
            if preview_rule_id and hostname and ':' in preview_rule_id:
                preview_type, _, raw_id = preview_rule_id.partition(':')
                rule_preview, rule_preview_error = \
                    cmk_rule_preview(hostname, preview_type, raw_id)
                # The preview itself only renders the outcome — it does
                # not know whether the rule's conditions match this host.
                # Reuse the per-rule hit info already computed for the
                # Rules section so the preview can show a "won't match"
                # warning when relevant.
                if rule_preview:
                    rule_preview['match'] = _find_rule_match(new_rules, raw_id)

        return self.render('debug_host.html', hostname=hostname, output=output,
                           host=host,
                           cmdb_mode=app.config.get('CMDB_MODE', False),
                           rules=new_rules, mode=mode,
                           rule_preview=rule_preview,
                           rule_preview_error=rule_preview_error,
                           rule_preview_groups=rule_preview_groups,
                           preview_rule_id=preview_rule_id)


    # Bulk actions that only make sense when the syncer is in CMDB mode
    # (the host list is the primary place an admin mutates hosts by hand).
    # Filtered out via is_action_allowed() when CMDB_MODE is off so the
    # "With selected..." dropdown stays clean for import-only installs.
    _CMDB_ONLY_ACTIONS = frozenset({
        'copy_as_new', 'bulk_label_edit', 'set_template',
    })

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status
        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.can_delete = False
            self.column_exclude_list = list(self.column_exclude_list) + [
                'cmdb_fields', 'cmdb_templates',
            ]
            # The copy-row icon only makes sense when the user is
            # expected to create hosts by hand. The relations-graph
            # icon is CMDB-only too — drop both.
            self.column_extra_row_actions = [
                a for a in (self.column_extra_row_actions or [])
                if 'copy_as_new_form' not in getattr(a, 'url', '')
                and 'relations_graph' not in getattr(a, 'url', '')
            ]
            self.column_formatters = dict(self.column_formatters)
            self.column_formatters_detail = dict(self.column_formatters_detail)
            self.column_labels = dict(self.column_labels)
            for col in _CMDB_ONLY_FIELDS:
                self.column_formatters.pop(col, None)
                self.column_formatters_detail.pop(col, None)
                self.column_labels.pop(col, None)
                if col not in self.column_exclude_list:
                    self.column_exclude_list.append(col)
            self.column_details_list = [
                c for c in self.column_details_list if c not in _CMDB_ONLY_FIELDS
            ]
            self.column_sortable_list = tuple(
                c for c in self.column_sortable_list if c not in _CMDB_ONLY_FIELDS
            )
            self.column_filters = tuple(
                f for f in self.column_filters
                if not isinstance(f, (FilterLifecycleState, FilterStale))
            )
            self.form_rules = _strip_cmdb_form_rules(
                list(self.form_rules), set(_CMDB_ONLY_FIELDS),
            )

        if app.config['LABEL_PREVIEW_DISABLED']:
            self.column_exclude_list.append('labels')

        super().__init__(model, **kwargs)

        # CMDB Template filter is reachable only via the click-to-filter
        # icon next to each template badge — exposing it in the filter
        # dropdown would just confuse users (the typed value is a
        # template ObjectId nobody types by hand). Strip it from the
        # filter-group UI but leave _filter_args wired so the URL keeps
        # resolving.
        if self._filter_groups:
            for flt in list(self._filter_groups):
                if flt == 'CMDB Template':
                    self._filter_groups.pop(flt)

    def is_action_allowed(self, name):
        if (name in self._CMDB_ONLY_ACTIONS
                and not app.config.get('CMDB_MODE')):
            return False
        if name.startswith('lifecycle_') and not app.config.get('CMDB_MODE'):
            return False
        return super().is_action_allowed(name)

    def get_export_name(self, _export_type):  # pylint: disable=signature-differs
        """
        Generates a filename for exporting data based on the model name and current timestamp.

        Args:
            export_type: The type of export being performed (currently unused).

        Returns:
            str: A string representing the export filename in the format
                 '<ModelName>_<YYYYMMDDHHMM>.syncer_json'.
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object__ne=True, deleted_at__exists=False)

    def scaffold_form(self):
        """Scaffold form with extra CMDB fields."""
        form_class = super().scaffold_form()
        form_class.labels_from_template = StaticTemplateLabelField()

        # Filter cmdb_templates to show only template objects
        if hasattr(form_class, 'cmdb_templates'):
            form_class.cmdb_templates.kwargs['queryset'] = Host.objects(object_type='template')

        return form_class

    def edit_form(self, obj=None):
        """Build edit form with template labels and CMDB fields."""
        # Merge existing cmdb_fields with labels not yet in the list, then
        # sort alphabetically by name so the form renders in a predictable
        # order. The reorder is in-memory only — on_model_change persists
        # it along with any user edits.
        if obj is not None:
            merged = {
                entry.field_name: (entry.field_value or '')
                for entry in (obj.cmdb_fields or [])
                if getattr(entry, 'field_name', None)
            }
            for label_key, label_value in (obj.labels or {}).items():
                if label_key not in merged:
                    merged[label_key] = (
                        str(label_value) if label_value is not None else ''
                    )
            sorted_fields = []
            for key in sorted(merged.keys(), key=str.lower):
                field = CmdbField()
                field.field_name = key
                field.field_value = merged[key]
                sorted_fields.append(field)
            obj.cmdb_fields = sorted_fields

        form = super().edit_form(obj)
        if obj and hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj

        if hasattr(form, 'cmdb_templates'):
            form.cmdb_templates.queryset = Host.objects(object_type='template')

        return form

    def get_form_field_type(self, field_name):
        """
        Dynamically determine the WTForms field type for a given field_name
        based on your configuration (e.g., app.config['CMDB_MODELS']).
        Returns a WTForms Field class.
        """
        field_type = app.config['CMDB_MODELS']['all'].get(field_name, {'type': 'string'})
        field_type = field_type['type']
        if field_type == 'boolean':
            return BooleanField
        return StringField

    def create_form(self, obj=None):
        """Build create form with template labels and CMDB fields."""
        form = super().create_form(obj)
        if hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj
        if hasattr(form, 'cmdb_templates'):
            form.cmdb_templates.queryset = Host.objects(object_type='template')
        return form

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')

    def on_model_delete(self, model):
        """
        Housekeeping on host deletion (called by the soft-delete mixin
        before the host transitions to archived).
        """
        if model.folder:
            folder = CheckmkFolderPool.objects.get(folder_name__iexact=model.folder)
            if folder.folder_seats_taken > 0:
                folder.folder_seats_taken -= 1
                folder.save()


    def on_model_change(self, form, model, _is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
        # Tag this label mutation as a manual edit so HostLabelChange
        # rows carry the right origin + acting user in the Timeline.
        # pylint: disable=protected-access
        model._label_change_source = 'manual'
        model._label_change_user = getattr(current_user, 'email', None)
        # Hosts created/edited here are always of type 'host' — the form
        # field is hidden so the choice can't be accidentally changed.
        model.object_type = 'host'
        model.cmdb_templates = form.cmdb_templates.data or []
        # Set Extra Fields
        cmdb_fields = app.config['CMDB_MODELS'].get(model.object_type, {})
        cmdb_fields.update(app.config['CMDB_MODELS']['all'])
        new_labels = {
            entry['field_name']: entry['field_value']
            for entry in form.cmdb_fields.data
            if entry.get('field_name')
        }

        existing_labels = model.labels or {}
        for label_key, label_value in existing_labels.items():
            if label_key not in new_labels:
                new_labels[label_key] = label_value

        # Hold back changes to APPROVAL_REQUIRED_LABELS until a second
        # operator approves them. enqueue_critical_label_changes() rolls
        # each contested key back to its old value inside `new_labels`,
        # so update_host below persists the safe subset only.
        # pylint: disable=import-outside-toplevel
        from application.views.field_approval import enqueue_critical_label_changes
        queued = enqueue_critical_label_changes(model, new_labels, existing_labels)
        if queued:
            flash(f'{queued} change(s) on protected fields are pending '
                  'approval and were not applied yet.', 'warning')

        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

        existing_cmdb_fields = {
            field.field_name for field in (model.cmdb_fields or [])
            if getattr(field, 'field_name', None)
        }
        for label_key, label_value in new_labels.items():
            if label_key not in existing_cmdb_fields:
                new_field = CmdbField()
                new_field.field_name = label_key
                new_field.field_value = str(label_value) if label_value is not None else ''
                model.cmdb_fields.append(new_field)
                existing_cmdb_fields.add(label_key)

        for key in cmdb_fields:
            if key not in new_labels:
                new_field = CmdbField()
                new_field.field_name = key
                model.cmdb_fields.append(new_field)

        # Keep the persisted order stable: the edit view sorts entries
        # alphabetically, so on save we preserve that ordering instead of
        # leaving dropped/newly-appended entries out of place.
        model.cmdb_fields = sorted(
            model.cmdb_fields or [],
            key=lambda f: (getattr(f, 'field_name', '') or '').lower(),
        )

    list_template = 'admin/host_list.html'
    details_template = 'admin/host_details.html'
    edit_template = 'admin/host_edit.html'

    def render(self, template, **kwargs):
        """
        Supply the template choice list to the list view so the
        "Set Template" modal can render its <select> inline. Also
        pre-load the user's Saved Searches for this list path so the
        preset bar renders without a follow-up DB round-trip.
        """
        if template.endswith('host_list.html') or template.endswith('list.html'):
            kwargs.setdefault('set_template_choices', self.get_template_list())
            # pylint: disable=import-outside-toplevel
            from application.views.saved_search import list_for_path
            kwargs.setdefault(
                'saved_searches', list_for_path(request.path),
            )
        return super().render(template, **kwargs)

    # `action_set_template` stays as a server-side fallback. The
    # modernized list view intercepts the action client-side and opens
    # a modal instead of redirecting to a separate page — see
    # admin/host_list.html. If JS is disabled the redirect path still
    # works.
    @action('set_template', 'Set Template', None)
    def action_set_template(self, ids):
        """
        Action to set CMDB template
        """
        url = url_for('.set_template_form', ids=','.join(ids),
                      return_to=request.referrer or '')
        return redirect(url)

    @action('bulk_label_edit', 'Bulk Edit Labels', None)
    def action_bulk_label_edit(self, ids):
        """
        Open the bulk label editor (add/remove/rename) for the
        selected hosts. The actual change is applied in bulk_label_process.
        """
        return redirect(url_for('.bulk_label_form', ids=','.join(ids),
                                return_to=request.referrer or ''))

    @action('copy_as_new', 'Copy as new', None)
    def action_copy_as_new(self, ids):
        """
        Clone one Host/Template into a new row. The user is prompted for
        the new hostname in a small modal — labels, cmdb_fields and
        cmdb_templates round-trip, timestamps and sync state are reset
        so the clone doesn't look like a recently-imported object.
        """
        if len(ids) != 1:
            flash('Copy as new requires exactly one selected row.', 'error')
            return redirect(url_for('.index_view'))
        return redirect(url_for('.copy_as_new_form', source_id=ids[0]))

    @expose('/copy_as_new_form')
    def copy_as_new_form(self):
        """Render the new-hostname modal for the copy-as-new action."""
        return _render_copy_as_new_form(self, 'Host')

    @expose('/copy_as_new_process', methods=['POST'])
    def copy_as_new_process(self):
        """Clone the source Host under the new hostname."""
        return _process_copy_as_new('Host')

    @expose('/bulk_label_form')
    def bulk_label_form(self):
        """Render the bulk label editor for the ids passed in the URL."""
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',') if i]
        return render_template('admin/bulk_label_form.html', ids=ids,
                               return_to=request.args.get('return_to', ''))

    @expose('/bulk_label_process', methods=['POST'])
    def bulk_label_process(self):  # pylint: disable=too-many-branches
        """
        Apply an add / remove / rename label operation to every host in
        `host_ids`. Uses `update_host` so existing side-effects (log entry,
        last_import_sync bump, cache invalidation) still fire per host.
        """
        host_ids = [x for x in request.form.get('host_ids', '').split(',') if x]
        mode = request.form.get('mode', '')
        key = (request.form.get('label_key') or '').strip()
        value = (request.form.get('label_value') or '').strip()
        new_key = (request.form.get('new_key') or '').strip()

        if mode not in ('add', 'remove', 'rename') or not key:
            flash('Invalid bulk label request', 'error')
            return redirect(url_for('.index_view'))
        if mode == 'rename' and not new_key:
            flash('Rename needs a new key', 'error')
            return redirect(url_for('.index_view'))
        # Empty value in add-mode would silently overwrite an existing
        # value — the operator has to either type a value or pick remove.
        if mode == 'add' and not value:
            flash('Add mode requires a non-empty value '
                  '(use Remove mode to drop a label).', 'error')
            return redirect(url_for('.index_view'))

        changed = 0
        skipped = 0
        user_email = getattr(current_user, 'email', None)
        # Fetch all selected hosts in one query instead of one round-trip
        # per id. Per-doc .save() stays — HostLabelChange signal handling
        # and update_host's import_seen/sync bumps need it.
        hosts = Host.objects(id__in=host_ids)
        for host in hosts:
            labels = dict(host.labels or {})
            before = dict(labels)
            if mode == 'add':
                labels[key] = value
            elif mode == 'remove':
                labels.pop(key, None)
            elif mode == 'rename':
                if key in labels:
                    labels[new_key] = labels.pop(key)
                else:
                    skipped += 1
                    continue

            # Defensive check: a bulk action must only touch the one key
            # the operator named. If anything else moved (e.g. an upstream
            # config quietly flattened a nested label), bail out instead
            # of writing the truncated dict back.
            expected_keys = set(before.keys())
            if mode == 'add':
                expected_keys.add(key)
            elif mode == 'remove':
                expected_keys.discard(key)
            elif mode == 'rename':
                expected_keys.discard(key)
                expected_keys.add(new_key)
            if set(labels.keys()) != expected_keys:
                logger.error(
                    "bulk_label_process aborted for %s: key drift "
                    "(before=%s, after=%s, mode=%s, key=%s)",
                    host.hostname, sorted(before.keys()),
                    sorted(labels.keys()), mode, key,
                )
                skipped += 1
                continue

            if labels != before:
                # Tag the change so HostLabelChange rows show "manual"
                # + the acting user in the Timeline, not "import".
                # pylint: disable=protected-access
                host._label_change_source = 'manual'
                host._label_change_user = user_email
                host.update_host(labels)
                host.save()
                changed += 1

        flash(
            f'Bulk label {mode}: updated {changed} host(s)'
            + (f', {skipped} skipped (key not present)' if skipped else ''),
            'success' if changed else 'warning',
        )
        return redirect(_safe_return_to(request.form.get('return_to')))


    @expose('/set_template_form')
    def set_template_form(self):
        """
        Custom form for template selection
        """
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',')]
        templates = self.get_template_list()

        return render_template('admin/set_template_form.html', ids=ids,
                               templates=templates,
                               return_to=request.args.get('return_to', ''))

    @expose('/process_template_assignment', methods=['POST'])
    def process_template_assignment(self):  # pylint: disable=too-many-locals
        """
        Process the template assignment
        """
        host_ids = request.form.get('host_ids', '').split(',')
        template_id = request.form.get('template_id')

        return_to = _safe_return_to(request.form.get('return_to'))
        if not template_id:
            flash('Please select a template', 'error')
            return redirect(return_to)

        try:
            # Get the template
            template = Host.objects(id=template_id).first()
            if not template:
                flash('Template not found', 'error')
                return redirect(return_to)

            # Single id__in fetch instead of one query per host. Per-doc
            # .save() is kept because mongoengine signals + update_host
            # side-effects need it.
            valid_ids = [hid for hid in host_ids if hid.strip()]
            hosts = list(Host.objects(id__in=valid_ids))
            updated_count = 0
            for host in hosts:
                # Append template if not already in the list
                existing_ids = [t.id for t in host.cmdb_templates]
                if template.id not in existing_ids:
                    host.cmdb_templates.append(template)

                # Apply the same logic as on_model_change
                host.last_import_sync = datetime.now()
                host.last_import_seen = datetime.now()
                host.cache = {}
                host.source_account_name = "cmdb"

                # Set Extra Fields from CMDB config
                cmdb_fields = app.config['CMDB_MODELS'].get(host.object_type, {})
                cmdb_fields.update(app.config['CMDB_MODELS']['all'])

                # Create labels from existing cmdb_fields
                new_labels = {
                    x.field_name: x.field_value
                    for x in host.cmdb_fields
                    if x.field_value
                }

                host.update_host(new_labels)
                host.set_inventory_attributes('cmdb')

                # Add missing CMDB fields based on configuration
                existing_field_names = {x.field_name for x in host.cmdb_fields}
                for cfg_key in cmdb_fields:
                    if cfg_key not in existing_field_names:
                        new_field = CmdbField()
                        new_field.field_name = cfg_key
                        host.cmdb_fields.append(new_field)

                host.save()
                updated_count += 1

            flash(f'Template applied to {updated_count} hosts', 'success')

        except Exception as e:  # pylint: disable=broad-exception-caught
            flash(f'Error applying template: {str(e)}', 'error')

        return redirect(return_to)

    def get_template_list(self):
        """Get available CMDB templates for the action form"""
        try:
            templates = Host.objects(is_object=True, object_type='template')
            return list(templates)
        except Exception:  # pylint: disable=broad-exception-caught
            return []

    @expose('/csv')
    def export_csv(self):  # pylint: disable=too-many-locals
        """
        Export all hosts as CSV
        """
        if not current_user.is_authenticated or not current_user.has_right('host'):
            return Response("Unauthorized", status=401)


        try:
            config = Config.objects().first()
            export_labels = (
                config.export_labels_list
                if config and config.export_labels_list
                else []
            )
            export_inventory = (
                config.export_inventory_list
                if config and config.export_inventory_list
                else []
            )
        except Exception:  # pylint: disable=broad-exception-caught
            export_labels = []
            export_inventory = []

        # Create CSV string in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write CSV header
        headers = [
            'hostname',
            'object_type',
            'lifecycle_state',
            'source_account_name',
            'folder',
            'last_import_seen',
            'last_import_sync',
            'no_autodelete'
        ]

        # Add configured label fields
        for label_field in export_labels:
            headers.append(f'label_{label_field}')

        # Add configured inventory fields
        for inventory_field in export_inventory:
            headers.append(f'inventory_{inventory_field}')

        writer.writerow(headers)

        # Get all hosts (excluding objects/templates)
        hosts = Host.objects(is_object__ne=True).order_by('hostname')

        # Write host data
        for host in hosts:
            row = [
                host.hostname or '',
                host.object_type or '',
                host.lifecycle_state or 'active',
                host.source_account_name or '',
                host.folder or '',
                host.last_import_seen.strftime(
                    '%Y-%m-%d %H:%M:%S'
                ) if host.last_import_seen else '',
                host.last_import_sync.strftime(
                    '%Y-%m-%d %H:%M:%S'
                ) if host.last_import_sync else '',
                host.no_autodelete if host.no_autodelete is not None else ''
            ]

            # Add configured label values
            for label_field in export_labels:
                value = host.labels.get(label_field, '') if host.labels else ''
                row.append(value)

            # Add configured inventory values
            for inventory_field in export_inventory:
                value = host.inventory.get(inventory_field, '') if host.inventory else ''
                row.append(value)

            writer.writerow(row)

        # Create response with CSV content
        csv_content = output.getvalue()
        output.close()

        # Generate filename with timestamp
        now = datetime.now()
        filename = f"hosts_export_{now.strftime('%Y%m%d_%H%M%S')}.csv"

        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

        return response


class HostArchiveView(HostnameAndLabelSearchMixin, DefaultModelView):
    # pylint: disable=too-many-ancestors
    """
    Archive of soft-deleted hosts. Read-only by default; the only ways
    out are Restore (clears deleted_at, transitions back to active) and
    Hard-Delete (drops the row permanently).
    """
    can_create = False
    can_edit = False
    can_delete = False  # disable per-row delete; bulk action is gated
    can_export = False
    can_view_details = True
    can_set_page_size = True

    def is_accessible(self):
        # The Archive only exists in CMDB mode (soft-delete is a
        # CMDB-only flow). Returning False here also hides the menu link.
        if not app.config.get('CMDB_MODE'):
            return False
        return super().is_accessible()

    page_size = app.config['HOST_PAGESIZE']

    column_list = [
        'hostname',
        'lifecycle_state',
        'source_account_name',
        'deleted_at',
        'delete_reason',
        'last_import_seen',
    ]
    column_details_list = column_list + ['labels', 'inventory', 'log']
    column_sortable_list = ('hostname', 'deleted_at', 'last_import_seen')

    column_formatters = {
        'lifecycle_state': _render_lifecycle_state,
        'deleted_at': _render_datetime,
        'last_import_seen': _render_datetime,
    }
    column_formatters_detail = {
        'lifecycle_state': _render_lifecycle_state,
        'deleted_at': _render_datetime,
        'last_import_seen': _render_datetime,
        'labels': _render_labels_with_origin,
        'inventory': _render_inventory_grid,
        'log': _render_log_grid,
    }
    column_labels = {
        'source_account_name': 'Account',
        'lifecycle_state': 'Lifecycle',
        'deleted_at': 'Deleted At',
        'delete_reason': 'Reason',
    }

    column_filters = (
        FilterHostnameRegex(Host, 'Hostname'),
        FilterAccountRegex(Host, 'Account'),
    )

    def get_query(self):
        return Host.objects(is_object__ne=True, deleted_at__exists=True)

    @action('restore', 'Restore', 'Restore the selected hosts to active?')
    def action_restore(self, ids):
        """Bring archived hosts back as active."""
        restored = 0
        for host in Host.objects(id__in=ids):
            if host.restore():
                host.save()
                restored += 1
        flash(f'Restored {restored} host(s) to active.', 'success')
        return redirect(request.referrer or url_for('.index_view'))

    @action('hard_delete',
            'Hard Delete (irreversible)',
            'Permanently delete the selected hosts? This cannot be undone.')
    def action_hard_delete(self, ids):
        """Permanently drop archived hosts from the database."""
        # pylint: disable=import-outside-toplevel
        from application.models.host_inventory_tree import HostInventoryTree
        if not current_user.has_right('hard_delete'):
            flash('Hard delete requires the "Permanently delete archived '
                  'objects" role.', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        # Snapshot the hostnames before deletion so the side-doc cleanup
        # has something to match against. Side docs are keyed by
        # hostname (string), not by Host reference, so orphans would
        # otherwise survive and silently resurface if a host with the
        # same name is re-imported later.
        hostnames = list(
            Host.objects(id__in=ids, deleted_at__exists=True).distinct('hostname')
        )
        deleted = Host.objects(id__in=ids, deleted_at__exists=True).delete()
        if hostnames:
            HostInventoryTree.objects(hostname__in=hostnames).delete()
        flash(f'Hard-deleted {deleted} host(s).', 'success')
        return redirect(request.referrer or url_for('.index_view'))
