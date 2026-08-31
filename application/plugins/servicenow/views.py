"""
Query a ServiceNow table from the web interface
"""
from flask import request
from flask_admin import BaseView, expose
from flask_login import current_user

from application.models.account import Account

from .syncer import ServiceNowError, SyncServiceNow

DEFAULT_LIMIT = 25
MAX_LIMIT = 500


class ServiceNowQueryView(BaseView):
    """
    Query the table of one ServiceNow account.

    Reads only: the query asks the Table API the same way the import does,
    with the account's own connection, query and field list. It is the way
    to find out whether the login works, which fields a record really has,
    and which of them carries the name the objects should be imported
    under — before any of it goes into the account.
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('servicenow')

    @staticmethod
    def _accounts():
        """
        The ServiceNow accounts a query can run against, together with the
        settings the form offers as the defaults of the account
        """
        return [{
            'name': account.name,
            'address': account.address,
            'api_path': account.custom_field('api_path', '/api/now'),
            'tables': [x.strip() for x in account.custom_field('tables').split(',') if x.strip()],
            'hostname_field': account.custom_field('hostname_field', 'name'),
            'sysparm_query': account.custom_field('sysparm_query'),
            'sysparm_fields': account.custom_field('sysparm_fields'),
            'sysparm_display_value': account.custom_field('sysparm_display_value', 'true'),
        } for account in Account.objects(enabled=True, type='servicenow').order_by('name')]

    @staticmethod
    def _limit(value):
        """
        Number of records to fetch, kept in a sane range
        """
        try:
            return max(1, min(int(value), MAX_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    @staticmethod
    def _query(form, limit):
        """
        Run one query with the settings of the form. Raises ServiceNowError
        if it could not be done.
        """
        if not form['table']:
            raise ServiceNowError("No table given")
        try:
            syncer = SyncServiceNow(form['account'])
        except ValueError as error:
            raise ServiceNowError(f"Account '{form['account']}' not found") from error
        try:
            # Taken literally, not filled in from the account: an empty
            # query is what asks for every record of the table, and an
            # empty field list is what asks for every field of a record —
            # which is what a query is used for. The form offers the
            # settings of the account to start from.
            syncer.config['api_path'] = form['api_path']
            syncer.config['sysparm_query'] = form['sysparm_query']
            syncer.config['sysparm_fields'] = form['sysparm_fields']
            syncer.config['sysparm_display_value'] = form['sysparm_display_value']
            if form['hostname_field']:
                syncer.config['hostname_field'] = form['hostname_field']
            return syncer.query_table(form['table'], limit=limit)
        finally:
            # A query is no sync run, it leaves no log entry behind
            syncer.close()

    @expose('/')
    def index(self):
        """
        Show the query form and, if one was asked for, its result
        """
        # A query is read only, so it travels in the URL and stays linkable
        args = request.args
        form = {
            'account': args.get('account', ''),
            'table': args.get('table', '').strip(),
            'api_path': args.get('api_path', '').strip(),
            'hostname_field': args.get('hostname_field', '').strip(),
            'sysparm_query': args.get('sysparm_query', '').strip(),
            'sysparm_fields': args.get('sysparm_fields', '').strip(),
            'sysparm_display_value': args.get('sysparm_display_value', 'true'),
            'limit': args.get('limit', str(DEFAULT_LIMIT)),
        }

        error = None
        result = None
        limit = self._limit(form['limit'])
        if args.get('searched'):
            try:
                result = self._query(form, limit)
            except ServiceNowError as query_error:
                error = str(query_error)

        return self.render(
            'admin/servicenow_query.html',
            accounts=self._accounts(),
            form=form,
            limit=limit,
            result=result,
            error=error,
        )
