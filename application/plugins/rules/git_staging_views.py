"""
Flask-Admin page to push rules into a Git repository and pull them back.
"""
from flask import request
from flask_admin import BaseView, expose
from flask_login import current_user

from application.docu_links import docu_links
from application.models.account import Account
from application.models.user import is_readonly

from .git_staging import (
    ACCOUNT_TYPE,
    GitStagingError,
    format_pull_result,
    pull_rules,
    push_rules,
    staging_rule_types,
)


class RuleGitView(BaseView):
    """
    Move rules between instances, e.g. from test to production: one
    instance pushes the selected rule types into a Git repository, the
    other one pulls them from there.

    Both directions touch rules of every module, so the page is for
    global admins only.
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.global_admin

    def _render(self, **kwargs):
        """Render the page with the accounts and rule types to choose from."""
        accounts = Account.objects(enabled=True, type=ACCOUNT_TYPE).order_by('name')
        return self.render(
            'admin/rule_git.html',
            accounts=[{'name': x.name, 'address': x.address} for x in accounts],
            rule_types=staging_rule_types(),
            readonly=is_readonly(current_user),
            docu_link=docu_links['rules_in_git'],
            form=request.form,
            **kwargs,
        )

    @expose('/')
    def index(self):
        """Show the push and pull forms."""
        return self._render()

    @expose('/push', methods=['POST'])
    def push(self):
        """Push the selected rule types into the repository."""
        if is_readonly(current_user):
            return self._render(error="Read only users can not push rules")
        author = (current_user.name or current_user.email, current_user.email)
        try:
            result = push_rules(request.form.get('account', ''),
                                request.form.getlist('rule_types'),
                                request.form.get('message', ''), author)
        except GitStagingError as error:
            return self._render(error=str(error), action='push')
        if not result['commit']:
            lines = ["Nothing changed, no commit created"]
        else:
            lines = [f"Pushed commit {result['commit']}"] + result['changed']
        return self._render(result=lines, action='push')

    @expose('/pull', methods=['POST'])
    def pull(self):
        """Load the rules from the repository."""
        if is_readonly(current_user):
            return self._render(error="Read only users can not pull rules")
        try:
            result = pull_rules(request.form.get('account', ''),
                                request.form.getlist('rule_types'),
                                bool(request.form.get('delete_missing')))
        except GitStagingError as error:
            return self._render(error=str(error), action='pull')
        failed = any(x.get('error') for x in result['types'].values())
        return self._render(result=format_pull_result(result), action='pull',
                            failed=failed)
