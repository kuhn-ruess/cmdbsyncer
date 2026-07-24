"""
Project Views
"""
import json

from markupsafe import Markup, escape

from flask import request, flash, redirect, url_for, Response
from flask_admin.actions import action
from flask_admin.base import expose
from flask_admin.contrib.mongoengine.filters import FilterLike
from flask_login import current_user

from application.models.account import Account
from application.models.project import Project
from application.views.default import DefaultModelView
from application.views.account_select import AccountsMultiSelectField
from application.modules.rule.views import invalidate_host_rule_caches

# Projects currently scope the Checkmk exports (Setup rules, DCD rules and
# hosts) — the members shown and re-pointed here are those documents. When
# other plugins adopt projects, extend these imports and the counters below.
from application.plugins.checkmk.models import CheckmkRuleMngmt, CheckmkDCDRule


def _render_project_rule_count(_view, _context, model, _name):
    """Assigned Setup-rule count, linking to the filtered Setup-rule list."""
    count = CheckmkRuleMngmt.objects(project=model.name).count()
    url = url_for('checkmkrulemngmt.index_view', flt0_1=model.name)
    return Markup(f'<a href="{escape(url)}">{count}</a>')


def _render_project_dcd_count(_view, _context, model, _name):
    """Assigned DCD-rule count, linking to the filtered DCD-rule list."""
    count = CheckmkDCDRule.objects(project=model.name).count()
    url = url_for('checkmkdcdrule.index_view', flt0_0=model.name)
    return Markup(f'<a href="{escape(url)}">{count}</a>')


def _render_project_host_count(_view, _context, model, _name):
    """Assigned host count."""
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    return Host.objects(project=model.name).count()


def _render_project_name_link(_view, _context, model, _name):
    """Make the project name open its overview (rules + import/export)."""
    url = url_for('.overview_view', id=model.id)
    return Markup(f'<a href="{escape(url)}">{escape(model.name)}</a>')


def _render_project_accounts(_view, _context, model, _name):
    """List-column formatter: the accounts a project's members are exported to."""
    if model.limit_by_accounts:
        text = escape(', '.join(model.limit_by_accounts))
    else:
        text = Markup('<em>all accounts</em>')
    denied = [name for name in (model.deny_by_accounts or []) if name]
    if denied:
        return Markup(f'{text} <em>except</em> {escape(", ".join(denied))}')
    return text


def _import_project_rules(model, rule_dicts, project_name):
    """
    (Re)create rules of one model from exported JSON dicts and assign them to
    ``project_name``. Existing rules with the same name are overwritten. Shared
    by the project JSON import for both Setup rules and DCD rules. Returns the
    number of rules imported.
    """
    count = 0
    for rule_data in rule_dicts or []:
        rule_data = dict(rule_data)
        rule_data.pop('_id', None)
        rule_name = rule_data.get('name')
        if not rule_name:
            continue
        existing = model.objects(name=rule_name).first()
        rule = model.from_json(json.dumps(rule_data))
        if existing:
            rule.id = existing.id
        rule.project = project_name
        rule.save()
        count += 1
    return count


class ProjectView(DefaultModelView):
    """
    Projects group syncer objects (currently Checkmk Setup Rules, DCD rules
    and hosts) and limit which accounts they are exported to.
    ``limit_by_accounts`` restricts a project's members to the listed
    accounts (empty = all accounts); ``deny_by_accounts`` excludes accounts
    and wins. Projects are im-/exportable as JSON to move them between
    separate syncer instances.
    """
    # Adds a direct link from the edit form to the Setup Rules of this project.
    edit_template = 'admin/project_edit.html'
    # Adds an "Import project from JSON" button to the list toolbar.
    list_template = 'admin/project_list.html'
    column_list = ('name', 'limit_by_accounts', 'rule_count', 'dcd_rule_count',
                   'host_count')
    column_default_sort = 'name'
    column_labels = {
        'rule_count': 'Rules',
        'dcd_rule_count': 'DCD Rules',
        'host_count': 'Hosts',
        'limit_by_accounts': 'Exported to Accounts',
        'deny_by_accounts': 'Never export to Accounts',
    }
    column_formatters = {
        'name': _render_project_name_link,
        'rule_count': _render_project_rule_count,
        'dcd_rule_count': _render_project_dcd_count,
        'host_count': _render_project_host_count,
        'limit_by_accounts': _render_project_accounts,
    }
    column_filters = (
        FilterLike('name', 'Name'),
    )

    form_columns = ('name', 'documentation', 'limit_by_accounts',
                    'deny_by_accounts')
    form_overrides = {
        'limit_by_accounts': AccountsMultiSelectField,
        'deny_by_accounts': AccountsMultiSelectField,
    }
    form_descriptions = {
        'limit_by_accounts': "Export this project's members (rules, hosts) "
                             "only to these accounts. Leave empty for no "
                             "restriction.",
        'deny_by_accounts': "Never export this project's members to these "
                            "accounts. The exclusion wins over 'Exported to "
                            "Accounts'.",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    def on_model_change(self, form, model, is_created):
        """
        A project decides which members reach which account, so edits must
        refresh the per-host rule outcome caches. On a rename, re-point the
        assigned members first — they reference the project by name and
        would otherwise be silently dropped from every export.
        """
        if not is_created:
            stored = Project.objects(id=model.id).only('name').first()
            if stored and stored.name != model.name:
                # pylint: disable=import-outside-toplevel
                from application.models.host import Host
                CheckmkRuleMngmt.objects(project=stored.name).update(
                    project=model.name)
                CheckmkDCDRule.objects(project=stored.name).update(
                    project=model.name)
                Host.objects(project=stored.name).update(
                    project=model.name)
        invalidate_host_rule_caches()
        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Deleting a project changes which members are exported — drop the
        per-host rule outcome caches.
        """
        invalidate_host_rule_caches()
        return super().on_model_delete(model)

    @expose('/overview')
    def overview_view(self):
        """
        Project detail page: list the Setup Rules assigned to this project and
        surface the folder import and JSON export on one page — the row actions
        in the list are otherwise easy to miss.
        """
        project_id = request.args.get('id')
        project = self.get_one(project_id) if project_id else None
        if project is None:
            flash('Project not found', 'error')
            return redirect(self.get_url('.index_view'))
        project_rules = CheckmkRuleMngmt.objects(
            project=project.name).order_by('primary_ruleset', 'name')
        # DCD rules assigned to the project are shown for overview only — they
        # are not part of the Setup-rule export/import workflow.
        dcd_rules = CheckmkDCDRule.objects(
            project=project.name).order_by('name')
        return self.render(
            'admin/project_overview.html',
            project=project,
            project_rules=project_rules,
            dcd_rules=dcd_rules,
            return_url=self.get_url('.index_view'))

    @action('export', 'Export as JSON',
            'Download the selected projects and their rules as JSON?')
    def action_export(self, ids):
        """Bundle each selected project plus its rules into one JSON file."""
        payload = []
        for project in Project.objects(id__in=ids):
            project_rules = CheckmkRuleMngmt.objects(project=project.name)
            project_dcd_rules = CheckmkDCDRule.objects(project=project.name)
            payload.append({
                'project': json.loads(project.to_json()),
                'rules': [json.loads(rule.to_json()) for rule in project_rules],
                'dcd_rules': [json.loads(rule.to_json())
                              for rule in project_dcd_rules],
            })
        body = json.dumps(payload, indent=2, default=str)
        return Response(
            body, mimetype='application/json',
            headers={'Content-Disposition':
                     'attachment; filename=projects.json'})

    @expose('/import', methods=['GET', 'POST'])
    def import_view(self):
        """Recreate a project and its rules from an exported JSON file."""
        return_url = self.get_url('.index_view')
        if request.method == 'GET':
            return self.render('admin/project_import.html',
                               return_url=return_url)

        upload = request.files.get('import_file')
        if not upload:
            flash('No file uploaded', 'error')
            return redirect(return_url)
        try:
            data = json.loads(upload.read().decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as error:
            flash(f'Invalid JSON: {error}', 'error')
            return redirect(return_url)

        # Accept a single {project, rules} object or a list of them.
        if isinstance(data, dict):
            data = [data]

        projects, imported_rules, imported_dcd_rules = 0, 0, 0
        for block in data:
            proj_data = dict((block or {}).get('project') or {})
            proj_data.pop('_id', None)
            name = proj_data.get('name')
            if not name:
                continue
            project = Project.objects(name=name).first() \
                or Project(name=name)
            project.documentation = proj_data.get('documentation')
            # Keep the account filters — without them an imported project
            # silently falls back to "all accounts".
            project.limit_by_accounts = [
                str(entry) for entry in
                (proj_data.get('limit_by_accounts') or []) if entry]
            project.deny_by_accounts = [
                str(entry) for entry in
                (proj_data.get('deny_by_accounts') or []) if entry]
            project.save()
            projects += 1

            imported_rules += _import_project_rules(
                CheckmkRuleMngmt, block.get('rules'), name)
            imported_dcd_rules += _import_project_rules(
                CheckmkDCDRule, block.get('dcd_rules'), name)

        if projects:
            # Imported rules are saved directly (not through the rule views),
            # so the per-host rule outcome caches must be dropped here.
            invalidate_host_rule_caches()
        flash(f'Imported {projects} project(s), {imported_rules} rule(s) and '
              f'{imported_dcd_rules} DCD rule(s)', 'success')
        return redirect(return_url)

    @action('import_from_cmk', 'Import Rules from Checkmk Folder', None)
    def action_import_from_cmk(self, ids):
        """Row action: open the folder-import form for one selected project."""
        if len(ids) != 1:
            flash('Select exactly one project to import into', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        return redirect(url_for('.import_from_cmk_view', id=ids[0]))

    @expose('/import_from_cmk', methods=['GET', 'POST'])
    def import_from_cmk_view(self):
        """
        Import every Checkmk Setup Rule of a chosen folder (on a chosen
        Checkmk account) into this project as static rules.
        """
        return_url = self.get_url('.index_view')
        project_id = request.args.get('id') or request.form.get('id')
        project = self.get_one(project_id) if project_id else None
        if project is None:
            flash('Select a project first', 'error')
            return redirect(return_url)

        if request.method == 'GET':
            accounts = [
                account.name for account in
                Account.objects(enabled=True, type='cmkv2').order_by('name')
            ]
            return self.render(
                'admin/project_import_cmk.html',
                project=project, project_id=project_id,
                accounts=accounts, return_url=return_url)

        account = request.form.get('account')
        folder = (request.form.get('folder') or '/').strip() or '/'
        recursive = bool(request.form.get('recursive'))
        if not account:
            flash('No Checkmk account selected', 'error')
            return redirect(return_url)

        # pylint: disable=import-outside-toplevel
        from application.plugins.checkmk.inits import import_project_rules_from_folder
        from application.plugins.checkmk.cmk2 import CmkException
        from application.plugins.checkmk.rule_passwords import referenced_password_names
        try:
            imported = import_project_rules_from_folder(
                project.name, account, folder, recursive)
        except CmkException as error_obj:
            flash(f"Checkmk import failed (account {account}): {error_obj}",
                  'error')
            return redirect(return_url)
        flash(
            f"Imported {imported} rule(s) from folder '{folder}' "
            f"(account {account})",
            'success' if imported else 'warning')
        # Rules that carried an explicit password were rewritten to reference
        # the syncer password store — tell the user which entries to create so
        # they deploy with the project.
        referenced = set().union(*(
            referenced_password_names(outcome.value_template)
            for rule in CheckmkRuleMngmt.objects(project=project.name)
            for outcome in rule.outcomes))
        if referenced:
            flash(
                "These rules reference password store entries: "
                f"{', '.join(sorted(referenced))}. Create a Checkmk Password "
                "in the syncer with each name (real secret), then run the "
                "password export so the reference resolves in the target "
                "Checkmk.",
                'warning')
        return redirect(return_url)
