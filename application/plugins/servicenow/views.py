"""
Query a ServiceNow table from the web interface
"""
from flask import flash, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application.models.account import Account, CustomEntry
from application.models.host import Host

from .syncer import ServiceNowError, SyncServiceNow

DEFAULT_LIMIT = 25
MAX_LIMIT = 500


def saved_tables(current, table):
    """
    The table list of an account after a save: a table the account does
    not read yet replaces a single one and joins several
    """
    tables = [x.strip() for x in current.split(',') if x.strip()]
    if not table or table in tables:
        return ','.join(tables)
    if len(tables) <= 1:
        return table
    return ','.join(tables + [table])


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
    def _query(form, limit, compare=False):
        """
        Run one query with the settings of the form. Raises ServiceNowError
        if it could not be done. With `compare` the whole table is read
        and held against the hosts an export would send.
        """
        if not form['table']:
            raise ServiceNowError("No table given")
        try:
            syncer = SyncServiceNow(form['account'])
        except ValueError as error:
            raise ServiceNowError(f"Account '{form['account']}' not found") from error
        # A failed query shows the whole request, proxy and headers
        syncer.debug = True
        try:
            # Taken literally, not filled in from the account: an empty
            # query is what asks for every record of the table, and an
            # empty field list is what asks for every field of a record —
            # which is what a query is used for. The form offers the
            # settings of the account to start from.
            syncer.config['api_path'] = form['api_path']
            syncer.config['sysparm_query'] = form['sysparm_query']
            # "All fields" keeps the list in the form for the next try
            syncer.config['sysparm_fields'] = '' if form['all_fields'] else form['sysparm_fields']
            syncer.config['sysparm_display_value'] = form['sysparm_display_value']
            if form['hostname_field']:
                syncer.config['hostname_field'] = form['hostname_field']
            if compare:
                hostnames = Host.get_export_hosts().scalar('hostname')
                return syncer.compare_hosts(form['table'], hostnames)
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
            'all_fields': args.get('all_fields') == '1',
        }

        error = None
        result = None
        comparison = None
        limit = self._limit(form['limit'])
        if args.get('searched'):
            try:
                if args.get('action') == 'compare':
                    comparison = self._query(form, limit, compare=True)
                else:
                    result = self._query(form, limit)
            except ServiceNowError as query_error:
                error = str(query_error)

        return self.render(
            'admin/servicenow_query.html',
            accounts=self._accounts(),
            form=form,
            limit=limit,
            result=result,
            comparison=comparison,
            error=error,
            may_save=current_user.has_right('account'),
        )

    @expose('/save-account', methods=('POST',))
    def save_account(self):
        """
        Write the settings of the form into the account, so what was
        debugged here is what the next import does
        """
        values = request.form
        name = values.get('account', '')
        account = Account.objects(name=name, type='servicenow').first()
        if not current_user.has_right('account'):
            flash("Saving into an account needs the right to edit accounts", 'danger')
        elif not account:
            flash(f"Account '{name}' not found", 'danger')
        else:
            settings = {
                'tables': saved_tables(account.custom_field('tables'),
                                             values.get('table', '').strip()),
                'api_path': values.get('api_path', '').strip(),
                'hostname_field': values.get('hostname_field', '').strip(),
                'sysparm_query': values.get('sysparm_query', '').strip(),
                # "All fields" is what the query asked for
                'sysparm_fields': '' if values.get('all_fields') == '1'
                                  else values.get('sysparm_fields', '').strip(),
            }
            # Only these fields change, the rest of the account stays as
            # it is
            accounts = Account.objects(name=name, type='servicenow')
            for field, value in settings.items():
                if not accounts(custom_fields__name=field).update(
                        set__custom_fields__S__value=value):
                    accounts.update(push__custom_fields=CustomEntry(name=field, value=value))
            flash(f"Settings saved into account '{name}', tables: {settings['tables']}",
                  'success')
        back = {key: values.get(key, '') for key in
                ('account', 'table', 'api_path', 'hostname_field', 'sysparm_query',
                 'sysparm_fields', 'sysparm_display_value', 'limit', 'all_fields')}
        return redirect(url_for('.index', **{k: v for k, v in back.items() if v}))
