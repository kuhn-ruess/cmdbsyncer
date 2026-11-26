"""
Query a ServiceNow table from the web interface
"""
from contextlib import contextmanager

from flask import flash, jsonify, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application.models.account import Account, CustomEntry
from application.models.host import Host

from .syncer import (CLASS_FIELD, OUTSIDE_QUERY_CHUNK, ServiceNowError, SyncServiceNow,
                     get_record, note_outside_query, query_fields, split_tables)

DEFAULT_LIMIT = 25

# The lists of a comparison that open on a page of their own
COMPARE_LISTS = {
    'matched': 'Found in both',
    'missing_in_snow': 'Syncer hosts missing in ServiceNow',
    'missing_in_syncer': 'ServiceNow names without Syncer host',
}
MAX_LIMIT = 500


def saved_tables(current, table):
    """
    The table list of an account after a save: several tables of the form
    are the list, a single one the account does not read yet replaces a
    single one and joins several
    """
    tables = split_tables(current)
    if len(split_tables(table)) > 1:
        return ','.join(split_tables(table))
    if not table or table in tables:
        return ','.join(tables)
    if len(tables) <= 1:
        return table
    return ','.join(tables + [table])


def class_query(class_id):
    """ The encoded query that selects the records of one class """
    if not class_id:
        return f"{CLASS_FIELD}ISEMPTY"
    return f"{CLASS_FIELD}={class_id}"


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
    def _settings(account):
        """ The settings of an account the form offers as its defaults """
        return {
            'name': account.name,
            'address': account.address,
            'api_path': account.custom_field('api_path', '/api/now'),
            'tables': split_tables(account.custom_field('tables')),
            'hostname_field': account.custom_field('hostname_field', 'name'),
            'sysparm_query': account.custom_field('sysparm_query'),
            'sysparm_fields': account.custom_field('sysparm_fields'),
            'sysparm_display_value': account.custom_field('sysparm_display_value', 'true'),
            'exclude_accounts': split_tables(account.custom_field('compare_exclude_accounts')),
        }

    def _accounts(self):
        """ The ServiceNow accounts a query can run against, with their settings """
        return [self._settings(account) for account in
                Account.objects(enabled=True, type='servicenow').order_by('name')]

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
    @contextmanager
    def _syncer(form):
        """
        The syncer of the form's account with the settings of the form.
        Raises ServiceNowError if the account is not there.
        """
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
            yield syncer
        finally:
            # A query is no sync run, it leaves no log entry behind
            syncer.close()

    @classmethod
    def _query(cls, form, limit, compare=False):
        """
        Run one query with the settings of the form. Raises ServiceNowError
        if it could not be done. With `compare` the whole table is read
        and held against the hosts an export would send.
        """
        if not form['table']:
            raise ServiceNowError("No table given")
        with cls._syncer(form) as syncer:
            if compare:
                hostnames = Host.get_export_hosts().filter(
                    source_account_name__nin=form['exclude_accounts']).scalar('hostname')
                return syncer.compare_hosts(form['table'], hostnames)
            return syncer.query_table(form['table'], limit=limit)

    @staticmethod
    def _form(args):
        """ The settings of the query form, from the URL """
        return {
            'account': args.get('account', ''),
            'table': args.get('table', '').strip(),
            'api_path': args.get('api_path', '').strip(),
            'hostname_field': args.get('hostname_field', '').strip(),
            'sysparm_query': args.get('sysparm_query', '').strip(),
            'sysparm_fields': args.get('sysparm_fields', '').strip(),
            'sysparm_display_value': args.get('sysparm_display_value', 'true'),
            'limit': args.get('limit', str(DEFAULT_LIMIT)),
            'all_fields': args.get('all_fields') == '1',
            # Accounts whose hosts the comparison leaves out of the Syncer side
            'exclude_accounts': [x for x in args.getlist('exclude_accounts') if x],
        }

    @expose('/')
    def index(self):
        """
        Show the query form and, if one was asked for, its result
        """
        # A query is read only, so it travels in the URL and stays linkable
        args = request.args
        form = self._form(args)

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
            host_accounts=sorted(x for x in Host.objects.distinct('source_account_name') if x),
            form=form,
            limit=limit,
            result=result,
            comparison=comparison,
            # The form again, for the link to the names of one class
            class_args={key: ('1' if value is True else value) for key, value in form.items()
                        if value and key != 'limit'},
            error=error,
            may_save=current_user.has_right('account'),
        )

    @expose('/account-settings')
    def account_settings(self):
        """
        The current settings of one account, so the form can read them
        again without reloading the page
        """
        account = Account.objects(name=request.args.get('account', ''),
                                  type='servicenow').first()
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        return jsonify(self._settings(account))

    @expose('/class')
    def class_names(self):
        """
        The names of one class of a comparison, on a page of its own: a
        class holds thousands of them. Reads only the records of that
        class, with the query of the form on top.
        """
        args = request.args
        form = self._form(args)
        class_id = args.get('class_id', '').strip()
        form['sysparm_query'] = '^'.join(filter(None, [
            class_query(class_id), form['sysparm_query']]))
        error = None
        entry = None
        try:
            comparison = self._query(form, 0, compare=True)
            entry = next((x for x in comparison['by_class'] if x['class'] == class_id),
                         {'class': class_id, 'label': class_id, 'names': [],
                          'matched': 0, 'extra': 0, 'total': 0})
        except ServiceNowError as query_error:
            error = str(query_error)
        return self.render('admin/servicenow_class_names.html', form=form,
                           class_id=class_id, entry=entry, error=error)

    @expose('/list')
    def compare_list(self):
        """
        One list of a comparison on a page of its own, each name with the
        ServiceNow records it can show the fields of
        """
        form = self._form(request.args)
        key = request.args.get('list', '')
        error = None
        names = None
        if key in COMPARE_LISTS:
            try:
                names = self._query(form, 0, compare=True)[key]
            except ServiceNowError as query_error:
                error = str(query_error)
        else:
            error = f"Unknown list '{key}'"
        return self.render('admin/servicenow_compare_list.html', form=form,
                           title=COMPARE_LISTS.get(key, key), hosts=key != 'missing_in_syncer',
                           # Hosts ServiceNow does not have come with no class
                           classes=key != 'missing_in_snow',
                           compare_host=key == 'matched',
                           # Shown in the panel even when no attribute matches
                           key_fields=list(dict.fromkeys(
                               [CLASS_FIELD, form['hostname_field'] or 'name']
                               + query_fields(form['sysparm_query'])
                               + split_tables(form['sysparm_fields']))),
                           names=names, error=error,
                           record_args={k: v for k, v in request.args.items()
                                        if k in ('account', 'api_path', 'sysparm_display_value')},
                           # Syncer hosts missing in ServiceNow can be looked
                           # up without the query
                           outside_query=key == 'missing_in_snow' and form['sysparm_query'],
                           chunk=OUTSIDE_QUERY_CHUNK,
                           form_args=[(k, v) for k, v in request.args.items(multi=True)
                                      if k != 'list'])

    @expose('/outside-query')
    def outside_query(self):
        """
        Look up a few Syncer hosts missing in ServiceNow without the query
        of the form, for the list page. Asked one chunk at a time, so a
        long list neither blocks the comparison nor one request.
        """
        form = self._form(request.args)
        names = request.args.getlist('name')[:OUTSIDE_QUERY_CHUNK]
        entries = [{'name': x, 'note': '', 'records': []} for x in names]
        try:
            with self._syncer(form) as syncer:
                note_outside_query(syncer, form['table'], entries)
        except ServiceNowError as error:
            return jsonify({'error': str(error)}), 502
        return jsonify({'entries': entries})

    @expose('/record')
    def record(self):
        """ Every field of one ServiceNow record, for the list page """
        form = self._form(request.args)
        try:
            with self._syncer(form) as syncer:
                found = get_record(syncer, request.args.get('table', ''),
                                   request.args.get('sys_id', ''))
        except ServiceNowError as error:
            return jsonify({'error': str(error)}), 502
        if found is None:
            return jsonify({'error': 'Record not found'}), 404
        answer = {'fields': sorted(found.items())}
        # Found in both: the attributes of the Syncer host next to them
        if hostname := request.args.get('host'):
            host = Host.objects(hostname=hostname).first()
            answer['host'] = sorted((host.labels or {}).items()) if host else []
        return jsonify(answer)

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
                'compare_exclude_accounts': ','.join(
                    split_tables(values.get('exclude_accounts', ''))),
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
        back['exclude_accounts'] = split_tables(values.get('exclude_accounts', ''))
        return redirect(url_for('.index', **{k: v for k, v in back.items() if v}))
