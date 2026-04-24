"""
Notification Hub — Flask-Admin views.

Five model views (contacts, groups, calendars, vacations, rules) plus
a RAM-backed Dispatch Queue page. Everything uses the shared card
layout so it looks like the rest of the modernised admin.
"""
# pylint: disable=duplicate-code
from flask import flash, redirect, url_for
from flask_admin import BaseView, expose
from flask_admin.actions import action
from flask_admin.form import rules
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_login import current_user

from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section

from .models import (
    NotifyContact,
    NotifyContactGroup,
    NotifyShiftCalendar,
    NotifyVacation,
    NotifyDispatchRule,
)
from .queue import snapshot as queue_snapshot, clear_history


def _requires_account(view):
    """Every Notify view uses the existing 'account' right for now."""
    return view


def _is_accessible():
    return (current_user.is_authenticated
            and (current_user.has_right('account')
                 or current_user.global_admin))


class NotifyContactView(DefaultModelView):
    """List of alert recipients."""
    column_list = ('name', 'email', 'phone', 'enabled', 'source', 'tags')
    column_sortable_list = ('name', 'email', 'enabled', 'source')
    column_filters = (FilterLike('name', 'Name'),
                      BooleanEqualFilter('enabled', 'Enabled'))
    column_editable_list = ['enabled']

    form_rules = modern_form(
        section('1', 'main', 'Identity',
                'Display name (must be unique) and contact endpoints.',
                [rules.Field('name'),
                 rules.Field('email'),
                 rules.Field('phone'),
                 rules.Field('timezone')]),
        section('2', 'cond', 'Membership & Source',
                'Tags for dynamic group membership and the provenance '
                'of this contact record.',
                [rules.Field('source'),
                 rules.Field('tags'),
                 rules.Field('enabled'),
                 rules.Field('description')]),
        section('3', 'out', 'Dynamic LDAP Lookup',
                'Optional: when set, email/phone are fetched from LDAP '
                'at dispatch time (fallback to the fields above).',
                [rules.Field('ldap_account'),
                 rules.Field('ldap_filter')]),
        section('4', 'aux', 'Default Channels',
                'Channels to use when a dispatch rule doesn\'t name '
                'its own. OSS ships email; Enterprise adds Slack, '
                'Teams and generic webhook.',
                [rules.Field('default_channels')]),
    )

    def is_accessible(self):
        return _is_accessible()


class NotifyContactGroupView(DefaultModelView):
    """Named set of recipients."""
    column_list = ('name', 'enabled', 'dynamic_tag', 'ldap_account')
    column_sortable_list = ('name', 'enabled')
    column_filters = (FilterLike('name', 'Name'),
                      BooleanEqualFilter('enabled', 'Enabled'))
    column_editable_list = ['enabled']

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name the group is addressed by, plus activation.',
                [rules.Field('name'),
                 rules.Field('description'),
                 rules.Field('enabled')]),
        section('2', 'cond', 'Static Members',
                'Named contacts that are always in the group.',
                [rules.Field('members')]),
        section('3', 'out', 'Dynamic Members',
                'Everyone carrying this tag is added at dispatch time.',
                [rules.Field('dynamic_tag')]),
        section('4', 'aux', 'LDAP-Expanded Members',
                'Optional: expand an LDAP search at dispatch time. The '
                'LDAP account holds the base DN and bind credentials.',
                [rules.Field('ldap_account'),
                 rules.Field('ldap_filter')]),
    )

    def is_accessible(self):
        return _is_accessible()


class NotifyVacationView(DefaultModelView):
    """Away windows that re-route or drop dispatches."""
    column_list = ('contact', 'from_date', 'to_date', 'substitute', 'reason')
    column_sortable_list = ('contact', 'from_date', 'to_date')
    column_default_sort = ('from_date', True)

    form_rules = modern_form(
        section('1', 'main', 'Who',
                'The contact who is away.',
                [rules.Field('contact')]),
        section('2', 'cond', 'When',
                'Inclusive window. Time-of-day is honoured.',
                [rules.Field('from_date'),
                 rules.Field('to_date')]),
        section('3', 'out', 'Substitute & Reason',
                'Optional: who picks up the alerts (blank = drop). '
                'The reason is printed on the Vacation list view only.',
                [rules.Field('substitute'),
                 rules.Field('reason')]),
    )

    def is_accessible(self):
        return _is_accessible()


class NotifyShiftCalendarView(DefaultModelView):
    """iCal / CalDAV backed on-call calendars."""
    column_list = ('name', 'enabled', 'last_sync_at', 'last_sync_error')
    column_sortable_list = ('name', 'enabled', 'last_sync_at')
    column_editable_list = ['enabled']

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Display name, timezone and activation.',
                [rules.Field('name'),
                 rules.Field('description'),
                 rules.Field('timezone'),
                 rules.Field('enabled')]),
        section('2', 'cond', 'Source URL',
                'HTTPS URL of the iCal feed (Google "public ics", '
                'Outlook published calendar, CalDAV .../calendar.ics). '
                'HTTP basic auth credentials are pulled from the '
                'named Account — leave blank for unauthenticated feeds.',
                [rules.Field('ical_url'),
                 rules.Field('auth_account')]),
        section('3', 'out', 'Sync State',
                'Read-only: populated by `cmdbsyncer notify sync_calendars`. '
                'Wire that command into a cron group for automatic refresh.',
                [rules.Field('last_sync_at'),
                 rules.Field('last_sync_error')]),
    )

    form_widget_args = {
        'last_sync_at': {'readonly': True},
        'last_sync_error': {'readonly': True},
    }

    @action('sync_now', 'Sync now', 'Refresh the iCal feed for the selected calendar(s)?')
    def action_sync_now(self, ids):
        """Manually refresh the iCal feed for every selected calendar."""
        # pylint: disable=import-outside-toplevel
        from .ical import sync_calendar
        ok, failed = 0, 0
        for cal in NotifyShiftCalendar.objects(id__in=ids):
            sync_calendar(cal)
            if cal.last_sync_error:
                failed += 1
            else:
                ok += 1
        flash(f'Synced {ok} calendar(s), {failed} failed.',
              'success' if ok else 'warning')

    def is_accessible(self):
        return _is_accessible()


class NotifyDispatchRuleView(DefaultModelView):
    """Event → recipients routing rules."""
    column_list = ('name', 'enabled', 'sort_field', 'source_match',
                   'event_type_match', 'target_groups')
    column_sortable_list = ('name', 'sort_field', 'enabled')
    column_filters = (FilterLike('name', 'Name'),
                      BooleanEqualFilter('enabled', 'Enabled'))
    column_editable_list = ['enabled', 'sort_field']
    column_default_sort = ('sort_field', False)

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name, evaluation order, activation and whether this '
                'rule is the final stop.',
                [rules.Field('name'),
                 rules.Field('documentation'),
                 rules.Field('enabled'),
                 rules.Field('sort_field'),
                 rules.Field('last_match')]),
        section('2', 'cond', 'Match',
                'When should this rule fire? Event source + event type '
                'regex + an optional extra context-key regex.',
                [rules.Field('source_match'),
                 rules.Field('event_type_match'),
                 rules.Field('context_key'),
                 rules.Field('context_value_match')]),
        section('3', 'out', 'Who',
                'Recipient groups. Filter by shift calendar to alert '
                'only the on-call subset.',
                [rules.Field('target_groups'),
                 rules.Field('shift_calendar')]),
        section('4', 'aux', 'How',
                'Override the contacts\' default_channels with these. '
                'Empty = use each contact\'s defaults.',
                [rules.Field('channels')]),
    )

    def is_accessible(self):
        return _is_accessible()


class NotifyDispatchQueueView(BaseView):
    """RAM-backed queue / history view.

    Backed by `queue.snapshot()` (no Mongo hop) so it stays fast even
    under heavy load. Displays the current queue depth, whatever is
    in-flight right now, and the last N completed jobs. "Clear
    History" wipes the ring buffer; it cannot affect in-flight work.
    """

    @expose('/')
    def index(self):
        """Render the live queue snapshot."""
        snap = queue_snapshot()
        return self.render('admin/notify_queue.html', snap=snap)

    @expose('/clear', methods=['POST'])
    def clear(self):
        """Drop the recent-jobs ring buffer."""
        clear_history()
        flash('Notification queue history cleared.', 'success')
        return redirect(url_for('.index'))

    def is_accessible(self):
        return _is_accessible()


def register_admin_views(admin):
    """Hook entry point — called once at startup from application/__init__."""
    admin.add_sub_category(name='Notification Hub', parent_name='Modules')

    admin.add_view(NotifyContactView(
        NotifyContact, name='Contacts', category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-user-circle'))
    admin.add_view(NotifyContactGroupView(
        NotifyContactGroup, name='Groups', category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-users'))
    # Channels live in OSS (Settings → Notifications → Channels) — the
    # Hub just references them. No view registered here.
    admin.add_view(NotifyShiftCalendarView(
        NotifyShiftCalendar, name='Shift Calendars',
        category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-calendar'))
    admin.add_view(NotifyVacationView(
        NotifyVacation, name='Vacations', category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-umbrella-beach'))
    admin.add_view(NotifyDispatchRuleView(
        NotifyDispatchRule, name='Dispatch Rules',
        category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-random'))
    admin.add_view(NotifyDispatchQueueView(
        name='Dispatch Queue',
        endpoint='notify_queue',
        category='Notification Hub',
        menu_icon_type='fa', menu_icon_value='fa-inbox'))
