"""
First Steps Wizard
"""
from flask import redirect, url_for, flash
from flask_admin import BaseView
from flask_admin.base import expose
from flask_login import current_user


def _docs(page):
    """Absolute link into the public documentation."""
    return f"https://docs.cmdbsyncer.de/{page}/"


def get_first_steps():
    """
    The setup checklist: every step carries a ``done`` flag computed
    live from the database, so the wizard reflects the real system
    state on every visit — finishing a step outside the wizard (CLI,
    another browser tab) checks it off too.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.account import Account
    from application.models.host import Host
    from application.models.cron import CronGroup
    from application.models.user import User
    from application.plugins.checkmk.models import (
        CheckmkRule,
        CheckmkRuleMngmt,
        CheckmkFilterRule,
        CheckmkRewriteAttributeRule,
    )

    # Outbound target types the syncer can export to. Inbound-only or
    # internal types deliberately excluded — an install that only has a
    # 'restapi' account has not connected a target yet.
    outbound_types = ('cmkv2', 'netbox', 'idoit', 'jira_cloud')

    steps = [
        {
            'key': 'account',
            'title': 'Create your first Account',
            'description': (
                "Accounts are the connections of the syncer — every system "
                "it talks to is one Account record: import sources (CSV "
                "file, Netbox, LDAP, a database, …) just like export "
                "targets (Checkmk, Netbox, …). Create one for each system "
                "you want to connect."
            ),
            'done': Account.objects(enabled=True).count() > 0,
            'action': ('Create Account', url_for('account.create_view')),
            'docs': _docs('basics/accounts'),
        },
        {
            'key': 'import',
            'title': 'Import your first objects',
            'description': (
                "Run the account's import so hosts (or other objects) land "
                "in the syncer. Imports run from the command line — e.g. "
                "./cmdbsyncer csv import_hosts <ACCOUNT> — or later "
                "automatically via cron jobs."
            ),
            'done': Host.objects().count() > 0,
            'action': ('Show Hosts', url_for('host.index_view')),
            'docs': _docs('basics/import'),
        },
        {
            'key': 'target',
            'title': 'Connect an export target',
            'description': (
                "Add the Account for the system the syncer should export "
                "to — for example your Checkmk instance (type 'Checkmk "
                "Version 2.x') with its URL and automation credentials."
            ),
            'done': Account.objects(
                enabled=True, type__in=outbound_types).count() > 0,
            'action': ('Create Account', url_for('account.create_view')),
            'docs': _docs('checkmk/accounts'),
        },
        {
            'key': 'rules',
            'title': 'Define your export rules',
            'description': (
                "Rules decide what happens on export: which folder a host "
                "lands in, which attributes become labels, what is filtered. "
                "Start with 'Set Folder and Attributes of Host' under "
                "Modules → Checkmk."
            ),
            'done': (
                CheckmkRule.objects().count() > 0
                or CheckmkRuleMngmt.objects().count() > 0
                or CheckmkFilterRule.objects().count() > 0
                or CheckmkRewriteAttributeRule.objects().count() > 0
            ),
            'action': ('Create Rule', url_for('checkmkrule.index_view')),
            'docs': _docs('checkmk/export_rules'),
        },
        {
            'key': 'cron',
            'title': 'Schedule the sync',
            'description': (
                "Group your import and export jobs into a Cronjob Group so "
                "the sync runs on its own. The syncer's cron daemon (or your "
                "system crontab) executes the groups on their interval."
            ),
            'done': CronGroup.objects().count() > 0,
            'action': ('Create Cronjob Group', url_for('crongroup.index_view')),
            'docs': _docs('basics/cron'),
        },
        {
            'key': 'users',
            'title': 'Invite your team',
            'description': (
                "Create additional users with the rights they need — "
                "colleagues get their own login instead of a shared one."
            ),
            'done': User.objects().count() > 1,
            'action': ('Manage Users', url_for('user.index_view')),
            'docs': _docs('basics/first_steps'),
        },
    ]
    return steps


def first_steps_pending():
    """
    True while the wizard should be the landing page: at least one step
    is open and no admin has dismissed it yet. Any failure (fresh DB
    without collections, race during setup) counts as "not pending" so
    the start page never breaks over the wizard.
    """
    # pylint: disable=import-outside-toplevel,broad-exception-caught
    from application.models.config import Config
    try:
        config = Config.objects().first()
        if config and config.first_steps_dismissed:
            return False
        return any(not step['done'] for step in get_first_steps())
    except Exception:
        return False


class FirstStepsView(BaseView):
    """
    Guided first-steps checklist: shows the initial setup path —
    account, import, target, rules, cron, users — with live completion
    state and links into the right views.
    """

    def is_visible(self):
        """
        Not part of the main menu — the page is linked from the profile
        icon menu (see master.html) and used as the landing page while
        the setup is incomplete.
        """
        return False

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('.index')))

    @expose('/')
    def index(self):
        """Render the checklist with live progress."""
        steps = get_first_steps()
        done_count = sum(1 for step in steps if step['done'])
        # pylint: disable=import-outside-toplevel
        from application.models.config import Config
        config = Config.objects().first()
        dismissed = bool(config and config.first_steps_dismissed)
        return self.render(
            'admin/first_steps.html',
            steps=steps,
            done_count=done_count,
            total_count=len(steps),
            dismissed=dismissed,
            docs_url=_docs('basics/first_steps'),
        )

    @expose('/dismiss', methods=['POST'])
    def dismiss(self):
        """Stop using the wizard as the landing page."""
        # pylint: disable=import-outside-toplevel
        from application.models.config import Config
        config = Config.objects().first() or Config()
        config.first_steps_dismissed = True
        config.save()
        flash('First steps hidden — the page stays available via '
              '"First Steps" in the profile menu.', 'info')
        return redirect(url_for('admin.index'))

    @expose('/show_again', methods=['POST'])
    def show_again(self):
        """Re-enable the wizard as the landing page."""
        # pylint: disable=import-outside-toplevel
        from application.models.config import Config
        config = Config.objects().first() or Config()
        config.first_steps_dismissed = False
        config.save()
        return redirect(url_for('.index'))
