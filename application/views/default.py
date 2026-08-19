"""
Default Model Views
"""
# pylint: disable=trailing-whitespace,line-too-long,raise-missing-from,broad-exception-caught
import os
import re
import html
import time
from copy import deepcopy
from datetime import datetime, timedelta
from flask import url_for, redirect, flash, request, abort, current_app
from flask_login import current_user
from flask_admin import AdminIndexView
from flask_admin import expose
from flask_admin.contrib.mongoengine import ModelView
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_admin.model.template import EndpointLinkRowAction
from flask_admin.helpers import get_redirect_target, is_safe_url
from flask_admin.model.helpers import get_mdict_item_or_list

from wtforms.validators import ValidationError

from mongoengine.errors import NotUniqueError

from application._version import __version__
from application.models.user import is_readonly


# Only filenames matching this pattern can be served via the old-changelog
# endpoint. This is the whitelist that prevents path traversal / arbitrary
# file reads through a user-supplied ``name`` parameter.
_CHANGELOG_FILENAME_RE = re.compile(r'^v\d+\.\d+\.md$')


def name_and_enabled_filters():
    """Standard ``(name LIKE, enabled =)`` filter pair used by every
    list view that just needs a quick search and an active/inactive
    toggle (Accounts, CronGroups, NotificationChannels, ...)."""
    return (FilterLike('name', 'Name'),
            BooleanEqualFilter('enabled', 'Enabled'))


_CHANGELOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'changelog')


def _major_minor_filename():
    """Return ``v{MAJOR}.{MINOR}.md`` for the running version."""
    parts = __version__.split('.')
    return f"v{parts[0]}.{parts[1]}.md"


def _load_changelog():
    """Return the current release's ``v{MAJOR}.{MINOR}.md`` markdown."""
    path = os.path.join(_CHANGELOG_DIR, _major_minor_filename())
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _load_changelog_file(name):
    """Return markdown for a specific ``v{MAJOR}.{MINOR}.md`` file or None."""
    if not _CHANGELOG_FILENAME_RE.match(name):
        return None
    path = os.path.join(_CHANGELOG_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _list_other_changelogs():
    """Return previous ``v*.md`` files, newest first, excluding the current one."""
    if not os.path.isdir(_CHANGELOG_DIR):
        return []
    current = _major_minor_filename()
    names = [
        name for name in os.listdir(_CHANGELOG_DIR)
        if _CHANGELOG_FILENAME_RE.match(name) and name != current
    ]

    def _version_tuple(name):
        # "v3.12.md" → (3, 12). Used to order newest-first.
        parts = name[1:-3].split('.')
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)

    return sorted(names, key=_version_tuple, reverse=True)


def _may(right):
    """True if the logged-in user holds ``right`` (global admins hold all)."""
    return current_user.is_authenticated and (
        current_user.global_admin or current_user.has_right(right))


def _humanize_age(value, now=None):
    """
    Compact relative age of a timestamp ("3 min ago", "2 days ago").

    Every timestamp the dashboard shows (log entries, cron runs, imports)
    is written with ``datetime.now()``, so local time is the right
    reference here. Returns an empty string for a missing value.
    """
    if not value:
        return ''
    now = now or datetime.now()
    seconds = int((now - value).total_seconds())
    if seconds < 0:
        # Clock skew or a scheduled-in-the-future timestamp.
        return 'just now'
    if seconds < 60:
        return f"{seconds} sec ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _humanize_eta(value, now=None):
    """Compact time-until for a future timestamp ("in 4 min")."""
    if not value:
        return ''
    now = now or datetime.now()
    seconds = int((value - now).total_seconds())
    if seconds <= 0:
        return 'due'
    minutes = seconds // 60
    if minutes < 60:
        return f"in {max(minutes, 1)} min"
    hours = minutes // 60
    if hours < 24:
        return f"in {hours} h"
    days = hours // 24
    return "in 1 day" if days == 1 else f"in {days} days"


# The per-source host figures come from a $group over the whole host
# collection — one pass, but a pass the start page would otherwise pay for
# on every single load. A short TTL keeps the dashboard cheap on large
# installations without making the numbers feel stale.
# Account types no cron group can ever drive: their objects arrive over the
# REST API or are maintained inside the Syncer. Calling those "not
# scheduled" reads like a misconfiguration when it is simply how they work.
_UNSCHEDULED_TYPES = {
    'from_api': 'pushed via API',
    'cmdb': 'managed in the syncer',
    'restapi': 'API credentials only',
}


def _cadence(account_type, name=''):
    """What drives a system when no cron group does."""
    # pylint: disable=import-outside-toplevel
    from application.models.account import CMDB_SOURCE_ACCOUNT_NAME
    if account_type in _UNSCHEDULED_TYPES:
        return _UNSCHEDULED_TYPES[account_type]
    # Objects in CMDB mode carry the reserved source name, not an account.
    if name == CMDB_SOURCE_ACCOUNT_NAME:
        return _UNSCHEDULED_TYPES['cmdb']
    return 'not scheduled'


# Configured Accounts are always listed in full — they are the install's
# actual wiring. Only the tail of historical source names that no Account
# belongs to any more is cut, and the card says how many it dropped.
_FLOW_SOURCE_LIMIT = 5

_HOST_SOURCE_TTL = 60
_host_source_cache = {}


def _host_sources(scope):
    """
    ``{source_account_name: {'count': int, 'last_seen': datetime}}`` over
    the hosts the Host list shows (no objects, not archived), limited to
    the user's account scope.

    ``scope`` is the user's account allowlist or None for unrestricted.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host

    key = tuple(sorted(scope)) if scope else None
    cached = _host_source_cache.get(key)
    if cached and time.monotonic() - cached[0] < _HOST_SOURCE_TTL:
        return cached[1]

    query = Host.objects(is_object__ne=True, deleted_at__exists=False)
    if scope:
        query = query.filter(source_account_name__in=list(scope))
    result = {}
    try:
        for row in query.aggregate([
                {'$group': {
                    '_id': '$source_account_name',
                    'count': {'$sum': 1},
                    'last_seen': {'$max': '$last_import_seen'},
                }}]):
            result[row['_id'] or ''] = {
                'count': row['count'],
                'last_seen': row.get('last_seen'),
            }
    except Exception:  # pylint: disable=broad-exception-caught
        return {}
    _host_source_cache[key] = (time.monotonic(), result)
    return result


# Row actions that lead to a create/restore flow. Read-only users get them
# taken out of the list — the endpoints themselves are refused anyway, this
# just keeps the icons from promising something that will not happen.
_WRITING_ROW_ACTIONS = ('clone_view', 'copy_as_new_form', 'restore_row')


def row_action_target(action):
    """
    Where a row action points, as one searchable string.

    Flask-Admin has two flavours: ``EndpointLinkRowAction`` carries an
    ``endpoint``, ``LinkRowAction`` a ready-made ``url``. Callers that want
    to drop an action by what it does should not have to know which.
    """
    endpoint = getattr(action, 'endpoint', '') or ''
    url = getattr(action, 'url', '') or ''
    return f"{endpoint} {url}"


class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """
    page_size = 300
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-clone", ".clone_view", title="Clone"),
    ]

    #   .-- Read only users
    # Flask-Admin reads these three off the view on every list, form and
    # write, so making them properties takes the whole model layer out of a
    # read-only user's reach in one place — new views inherit it. The write
    # itself is refused centrally (see ``_enforce_readonly``); these only
    # keep the UI from offering buttons that would be turned away.
    #
    # A subclass must therefore not assign ``can_create``/``can_edit``/
    # ``can_delete`` as a class attribute of its own — that shadows the
    # property. Assigning ``False`` is harmless (it stays False for
    # everyone), assigning ``True`` would hand the right back to read-only
    # users, which is why no subclass does it.
    @property
    def can_create(self):
        """Flask-Admin's create flag, off for read-only users."""
        return not is_readonly(current_user)

    @property
    def can_edit(self):
        """Flask-Admin's edit flag, off for read-only users."""
        return not is_readonly(current_user)

    @property
    def can_delete(self):
        """Flask-Admin's delete flag, off for read-only users."""
        return not is_readonly(current_user)

    def is_action_allowed(self, name):
        """Bulk actions all write, so a read-only user gets none of them."""
        if is_readonly(current_user):
            return False
        return super().is_action_allowed(name)

    def get_list_row_actions(self):
        """
        Row actions minus the ones that write, for read-only users — they
        would only lead to a refusal. Edit and delete are already gone
        through the properties above; what is left are the hand-made link
        actions, matched by where they point.
        """
        actions = super().get_list_row_actions()
        if not is_readonly(current_user):
            return actions

        def writes(action):
            target = row_action_target(action)
            return any(marker in target for marker in _WRITING_ROW_ACTIONS)

        return [action for action in actions if not writes(action)]
    #.

    def _run_view(self, fn, *args, **kwargs):
        """
        Skip Flask-Admin 2.0.2's silent retry-with-cls fallback.

        ``BaseView._run_view`` wraps the view call in
        ``try: fn(self, ...) except TypeError: fn(cls=self, ...)`` for
        backward compatibility with very old Flask-Admin views that took
        ``cls`` as their first arg. None of our views use that
        signature, so the fallback is dead code — and it actively hurts
        us: any genuine ``TypeError`` raised inside a view body gets
        swallowed and re-thrown as a misleading ``unexpected keyword
        argument 'cls'``, masking the real bug.

        Calling ``fn(self, ...)`` once and letting exceptions propagate
        gives us the actual stack trace.
        """
        return fn(self, *args, **kwargs)

    def create_model(self, form):
        """ 
        Create model with NotUniqueError handling
        """
        try:
            return super().create_model(form)
        except NotUniqueError:
            flash("Duplicate Fields in entry", "error")
            return False

    @expose("/clone", methods=("GET", "POST"))
    def clone_view(self):
        """
        Clone given model. GET renders a CSRF-protected confirmation form,
        POST performs the actual clone.
        """
        if request.method == "GET":
            entry_id = get_mdict_item_or_list(request.args, 'id')
            # Flask-Admin's row action doesn't pass `?url=...`, so
            # `get_redirect_target()` is almost always empty here.
            # Falling back to the same-host `request.referrer` keeps the
            # list filter, sort and page intact when the user returns
            # from the clone confirmation. Issue #121.
            referrer = request.referrer or ''
            referrer_target = referrer if referrer and is_safe_url(referrer) else None
            return_url = (
                get_redirect_target()
                or referrer_target
                or self.get_url('.index_view')
            )
            return self.render(
                'admin/model/clone_confirm.html',
                entry_id=entry_id,
                return_url=return_url,
            )

        entry_id = get_mdict_item_or_list(request.form, 'id')

        # Duplicate current record
        return_url = request.form.get('url') or self.get_url('.index_view')

        if not self.can_create:
            return redirect(return_url)

        old_model = self.get_one(entry_id)
        if old_model is None:
            flash('Entry does not exist.', 'error')
            return redirect(return_url)

        obj = deepcopy(old_model)
        obj.id = None
        if hasattr(obj, 'name'):
            obj.name += " (Clone)"
        try:
            obj.save()
        except NotUniqueError:
            flash('Entry with Name already exist', 'error')
            return redirect(return_url)

        flash("Entry Cloned", 'success')
        return redirect(return_url)

    def handle_view_exception(self, exc):
        """
        Handle view exceptions
        """
        if isinstance(exc, NotUniqueError):
            flash("Duplicate Entry Name - this name already exists", "error")
            return True  # Tell Flask-Admin we handled the exception
        
        # Let Flask-Admin handle other exceptions
        return super().handle_view_exception(exc)

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Fields
        """

        try:
            for attr in [x for x in dir(model) if not x.startswith('_')]:
                current = getattr(model, attr)
                if isinstance(current, str):
                    setattr(model, attr, current.strip())
            return super().on_model_change(form, model, is_created)
        except Exception as e:
            raise ValidationError(f"Error saving entry: {e}")


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))

class IndexView(AdminIndexView):
    """
    Index View Overwrite for auth
    """
    def is_visible(self):
        return False

    def is_accessible(self):
        return current_user.is_authenticated \
                and not current_user.force_password_change

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))

    # pylint: disable-next=too-many-statements,too-many-locals
    def _markdown_to_html(self, text, collapse_sections=False):
        """
        Simple Markdown to HTML converter for basic formatting.

        If ``collapse_sections`` is True, every ``## ...`` heading starts
        a ``<details>`` block — the first one is ``open`` by default, the
        rest are collapsed. The inner body goes into a dedicated
        ``<div class="changelog-body">`` sibling of ``<summary>`` so the
        rendering does not rely on the quirky "heading inside summary"
        pattern (which some browsers / admin themes hid, making the
        expanded sections look empty).
        """
        if not text:
            return text

        lines = text.split('\n')
        html_lines = []
        in_list = False
        in_body = False
        open_details = False
        seen_h2 = False

        def _close_list():
            nonlocal in_list
            if in_list:
                html_lines.append('</ul>')
                in_list = False

        def _close_body():
            nonlocal in_body
            if in_body:
                _close_list()
                html_lines.append('</div>')
                in_body = False

        def _close_details():
            nonlocal open_details
            _close_body()
            if open_details:
                html_lines.append('</details>')
                open_details = False

        for line in lines:
            stripped = line.strip()

            # Handle headers
            if stripped.startswith('###'):
                _close_list()
                html_lines.append(f'<h3>{html.escape(stripped[3:].strip())}</h3>')
            elif stripped.startswith('##'):
                title = stripped[2:].strip()
                if collapse_sections:
                    _close_details()
                    open_attr = '' if seen_h2 else ' open'
                    html_lines.append(f'<details{open_attr}>')
                    html_lines.append(
                        '<summary class="changelog-version">'
                        f'<span class="changelog-version-title">{html.escape(title)}</span>'
                        '</summary>'
                    )
                    html_lines.append('<div class="changelog-body">')
                    open_details = True
                    in_body = True
                    seen_h2 = True
                else:
                    _close_list()
                    html_lines.append(f'<h2>{html.escape(title)}</h2>')
            elif stripped.startswith('#'):
                _close_list()
                html_lines.append(f'<h1>{html.escape(stripped[1:].strip())}</h1>')
            # Handle list items
            elif stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul>')
                    in_list = True
                html_lines.append(f'<li>{html.escape(stripped[2:].strip())}</li>')
            # Handle empty lines and regular text
            else:
                _close_list()
                if stripped:  # Non-empty line
                    html_lines.append(f'<p>{html.escape(stripped)}</p>')
                # Intentional: blank lines no longer emit <br>. With the
                # new body wrapper the <ul>/<p> block model provides the
                # vertical rhythm; stray <br> inside <details> pushed the
                # first list item far enough down that some themes clipped
                # it out of view.

        _close_details()

        return '\n'.join(html_lines)

    def _load_notices(self):
        """
        Load all notice files from ``application/notices/``.
        Returns list of dicts with 'id' and 'content'.

        Empty while ``START_PAGE_NOTICES_ENABLED`` is off, which also takes
        the "Messages" card off the start page — the template only draws it
        when there is something to show. The files stay where they are, so
        turning the switch back on brings them back.
        """
        notices = []
        if not current_app.config.get('START_PAGE_NOTICES_ENABLED', False):
            return notices
        notices_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'notices')
        if not os.path.isdir(notices_dir):
            return notices
        for filename in sorted(os.listdir(notices_dir)):
            if filename.endswith('.txt'):
                notice_id = filename[:-4]  # strip .txt
                filepath = os.path.join(notices_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    escaped = html.escape(content)
                    linked = re.sub(
                        r'(https?://[^\s]+)',
                        r'<a href="\1" target="_blank">\1</a>',
                        escaped
                    )
                    notices.append({'id': notice_id, 'content': linked})
                except Exception:
                    pass
        return notices

    @expose('/')
    def index(self):
        """
        Index view: setup state, what the sync is doing, and the changelog.
        """
        # A fresh installation lands on the First Steps wizard until the
        # setup checklist is complete or an admin dismissed it.
        # pylint: disable=import-outside-toplevel
        from application.views.first_steps import first_steps_pending
        if first_steps_pending():
            return redirect(url_for('first_steps.index'))

        context = self._changelog_context()
        context.update(self._status_context())
        return self.render('admin/index.html', **context)

    def _changelog_context(self):
        """Release notes and operator messages for the right-hand column."""
        try:
            changelog_html = self._markdown_to_html(
                _load_changelog(), collapse_sections=True,
            )
        except FileNotFoundError:
            changelog_html = "<p>Changelog not found.</p>"
        except Exception:  # pylint: disable=broad-exception-caught
            changelog_html = "<p>Error loading changelog.</p>"
        return {
            'changelog_html': changelog_html,
            'notices': self._load_notices(),
            'older_changelogs': _list_other_changelogs(),
        }

    def _status_context(self):
        """
        The operational half of the start page. Every card is gated on the
        right that guards the views it exposes and links into, so a user
        never sees data on the dashboard they could not open themselves.
        """
        # Latest log entries that reported errors — failing sync jobs stay
        # visible without opening the Log.
        can_see_log = _may('log')
        error_logs, error_count_24h = \
            self._collect_error_logs() if can_see_log else ([], 0)

        # Cron status + one-click trigger.
        can_trigger_cron = _may('cron')
        cron_status = self._collect_cron_status() if can_trigger_cron else []

        # Warn users who can edit Checkmk rules about deprecated actions still
        # in use — those actions will be removed with 4.4 and rules carrying
        # them can no longer be saved until migrated.
        deprecated_rules, deprecation_warning = \
            self._collect_deprecated_rules() if _may('checkmk') else ([], '')

        # Data flow: which systems are connected, which of them carry data.
        # The card shows account names and host counts — the same information
        # the Host list exposes, hence the same right.
        can_see_flow = _may('host')
        connected_systems, total_hosts = \
            self._collect_connected_systems() if can_see_flow else ([], 0)
        orphans = [row for row in connected_systems if row['orphan']]
        visible_systems = [row for row in connected_systems if not row['orphan']] \
            + orphans[:_FLOW_SOURCE_LIMIT]
        hidden_systems = max(len(orphans) - _FLOW_SOURCE_LIMIT, 0)

        return {
            'error_logs': error_logs,
            'error_count_24h': error_count_24h,
            'can_see_log': can_see_log,
            'cron_status': cron_status,
            'can_trigger_cron': can_trigger_cron,
            'deprecated_rules': deprecated_rules,
            'deprecation_warning': deprecation_warning,
            'connected_systems': visible_systems,
            'connected_systems_hidden': hidden_systems,
            'total_hosts': total_hosts,
            'can_see_flow': can_see_flow,
            # Only link the flow rows the user may actually open.
            'can_edit_accounts': _may('account'),
            'setup_progress': self._collect_setup_progress(),
        }

    @staticmethod
    def _collect_deprecated_rules():
        """Checkmk rules whose outcomes still use a soon-to-be-removed action."""
        # pylint: disable=import-outside-toplevel
        try:
            from application.plugins.checkmk.models import (
                CheckmkRule, DEPRECATED_ACTIONS, DEPRECATION_WARNING)
        except Exception:  # pylint: disable=broad-exception-caught
            return [], ''
        rules = []
        try:
            for rule in CheckmkRule.objects(
                    outcomes__action__in=list(DEPRECATED_ACTIONS)):
                actions = sorted({
                    o.action for o in rule.outcomes
                    if o.action in DEPRECATED_ACTIONS})
                if actions:
                    rules.append({
                        'name': rule.name,
                        'id': str(rule.id),
                        'actions': actions,
                    })
        except Exception:  # pylint: disable=broad-exception-caught
            return [], DEPRECATION_WARNING
        return rules, DEPRECATION_WARNING

    @staticmethod
    def _collect_cron_status():
        """Per-group cron status for the dashboard widget."""
        # pylint: disable=import-outside-toplevel
        from application.models.cron import CronGroup, CronStats
        try:
            stats = {s.group: s for s in CronStats.objects()}
            now = datetime.now()
            rows = []
            for group in CronGroup.objects().order_by('name'):
                st = stats.get(group.name)
                last_start = st.last_start if st else None
                next_run = st.next_run if st else None
                rows.append({
                    'id': str(group.id),
                    'name': group.name,
                    'enabled': group.enabled,
                    'run_once_next': group.run_once_next,
                    'is_running': st.is_running if st else False,
                    'last_start': last_start,
                    'last_start_age': _humanize_age(last_start, now),
                    'next_run': next_run,
                    'next_run_eta': _humanize_eta(next_run, now),
                    'last_message': (st.last_message if st else '') or '',
                    'failure': st.failure if st else False,
                })
            return rows
        except Exception:  # pylint: disable=broad-exception-caught
            return []

    @staticmethod
    def _collect_error_logs():
        """
        ``([latest failed log entries], count of the last 24 h)``.

        The five newest entries alone cannot say whether the card is a live
        alarm or just history, so the 24 h count comes along with them.
        """
        # pylint: disable=import-outside-toplevel
        from application.modules.log.models import LogEntry
        try:
            now = datetime.now()
            entries = [{
                'id': str(entry.id),
                'datetime': entry.datetime,
                'age': _humanize_age(entry.datetime, now),
                'message': entry.message,
            } for entry in
                LogEntry.objects(has_error=True).order_by('-datetime')[:5]]
            recent = LogEntry.objects(
                has_error=True,
                datetime__gte=now - timedelta(hours=24)).count()
            return entries, recent
        except Exception:  # pylint: disable=broad-exception-caught
            return [], 0

    @staticmethod
    def _cron_jobs_by_account():
        """
        ``({account name: [(group name, group id)]}, {account name: newest
        run})`` over every cron group — what actually drives each account.
        """
        # pylint: disable=import-outside-toplevel
        from application.models.cron import CronGroup, CronStats
        jobs = {}
        last_runs = {}
        try:
            stats = {s.group: s for s in CronStats.objects()}
            for group in CronGroup.objects().order_by('name'):
                started = stats[group.name].last_start \
                    if group.name in stats else None
                for job in group.jobs:
                    if not job.account:
                        continue
                    name = job.account.name
                    entry = (group.name, str(group.id))
                    if entry not in jobs.setdefault(name, []):
                        jobs[name].append(entry)
                    if started and (not last_runs.get(name)
                                    or started > last_runs[name]):
                        last_runs[name] = started
        except Exception:  # pylint: disable=broad-exception-caught
            return {}, {}
        return jobs, last_runs

    @staticmethod
    def _collect_connected_systems():
        """
        One row per connected system for the "Data flow" card: the Account,
        how many hosts it imported, and which cron groups drive it.

        Everything is read from what the install actually does — hosts carry
        the account they came from, cron groups carry the account each job
        runs against — so an Account that is configured but never used shows
        up as exactly that.
        """
        # pylint: disable=import-outside-toplevel
        from application.models.account import Account

        scope = current_user.account_scope() if current_user.is_authenticated else None
        sources = _host_sources(scope)
        now = datetime.now()

        jobs, last_runs = IndexView._cron_jobs_by_account()

        rows = []
        seen = set()
        try:
            for account in Account.objects(enabled=True).order_by('name'):
                if scope and account.name not in scope:
                    continue
                seen.add(account.name)
                source = sources.get(account.name, {})
                rows.append({
                    'name': account.name,
                    'id': str(account.id),
                    'orphan': False,
                    'type': account.type or '',
                    'cadence': _cadence(account.type, account.name),
                    'hosts': source.get('count', 0),
                    'last_import_age': _humanize_age(source.get('last_seen'), now),
                    'groups': jobs.get(account.name, []),
                    'last_run_age': _humanize_age(last_runs.get(account.name), now),
                })
        except Exception:  # pylint: disable=broad-exception-caught
            return [], 0

        # Hosts whose source account no longer exists (or was disabled, or
        # were created by hand) still count — hiding them would make the
        # total on the card disagree with the Host list.
        for name, source in sorted(sources.items()):
            if name in seen:
                continue
            rows.append({
                'name': name or 'without account',
                'id': None,
                'orphan': True,
                'type': '',
                'cadence': _cadence('', name),
                'hosts': source.get('count', 0),
                'last_import_age': _humanize_age(source.get('last_seen'), now),
                'groups': jobs.get(name, []),
                'last_run_age': _humanize_age(last_runs.get(name), now),
            })

        # Configured Accounts first, each group by the data it carries, so
        # the install's wiring stays on top of its history.
        rows.sort(key=lambda row: (row['orphan'], -row['hosts'], row['name'].lower()))
        total_hosts = sum(entry.get('count', 0) for entry in sources.values())
        return rows, total_hosts

    @staticmethod
    def _collect_setup_progress():
        """
        ``(done, total, [open step titles])`` of the First Steps checklist,
        or None once every step is finished — the card only exists to point
        at the unfinished ones.
        """
        # pylint: disable=import-outside-toplevel
        from application.views.first_steps import get_first_steps
        try:
            steps = get_first_steps()
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        done = [s for s in steps if s['done']]
        if len(done) == len(steps):
            return None
        return {
            'done': len(done),
            'total': len(steps),
            'percent': int(len(done) * 100 / len(steps)) if steps else 0,
            'open_steps': [s['title'] for s in steps if not s['done']],
        }

    @expose('/trigger_cron', methods=['POST'])
    def trigger_cron(self):
        """Schedule a cron group to run on the next pass (dashboard button)."""
        # pylint: disable=import-outside-toplevel
        from application.models.cron import CronGroup
        if not (current_user.is_authenticated and (
                current_user.global_admin or current_user.has_right('cron'))):
            abort(403)
        group_name = request.form.get('group', '')
        group = CronGroup.objects(name=group_name).first()
        if not group:
            flash("Cron group not found.", 'error')
        elif not group.enabled:
            flash(f"Cron group '{group_name}' is disabled.", 'error')
        else:
            group.run_once_next = True
            group.save()
            flash(f"Scheduled '{group_name}' to run on the next cron pass.",
                  'success')
        return redirect(url_for('.index'))

    @expose('/changelog/<filename>')
    def changelog_archive(self, filename):
        """
        Render a previous ``vX.Y.md`` changelog file on its own page.

        ``filename`` is whitelisted against ``_CHANGELOG_FILENAME_RE`` so
        no arbitrary filesystem path can be requested via the URL.

        The URL parameter is ``filename`` and not ``name`` because
        Flask-Admin's ``BaseView._handle_view`` already takes a ``name``
        kwarg for view resolution, which would collide.
        """
        content = _load_changelog_file(filename)
        if content is None:
            abort(404)
        changelog_html = self._markdown_to_html(content, collapse_sections=True)
        return self.render(
            'admin/changelog_archive.html',
            title=filename[:-3],  # strip ".md"
            changelog_html=changelog_html,
        )
