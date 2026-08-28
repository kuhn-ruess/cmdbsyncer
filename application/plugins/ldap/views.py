"""
Search an LDAP directory from the web interface
"""
from flask import request
from flask_admin import BaseView, expose
from flask_login import current_user

from application.models.account import Account
from application.helpers.get_account import get_account_by_name, AccountNotFoundError

from .ldap import LDAP_AVAILABLE, LdapSearchError, build_search_filter, search_objects

# Value and label of the search modes, the value is what build_search_filter expects
SEARCH_MODES = [
    ('hostname', "Hostname — with or without domain"),
    ('contains', "Hostname contains"),
    ('attribute', "Attribute contains"),
    ('filter', "Own LDAP filter"),
]

# Fields the search needs, the search cannot run without them
REQUIRED_FIELDS = ('base_dn', 'hostname_field', 'encoding')

DEFAULT_LIMIT = 25
MAX_LIMIT = 500


def _custom_field(account, name):
    """
    One custom field of an Account document, empty string if it has none
    """
    for entry in account.custom_fields:
        if entry.name == name:
            return entry.value or ''
    return ''


class LdapSearchView(BaseView):
    """
    Search the directory of one LDAP account.

    Reads only: the search asks the server the same way the import does,
    with the account's own connection, base DN and search filter. It is
    the way to find out under which name an object really is in the
    directory — a search for a hostname without domain also finds the
    object that carries the domain — and to try out filters before they
    go into an account.
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('ldap')

    @staticmethod
    def _accounts():
        """
        The LDAP accounts a search can run against, together with the
        settings the form shows as the defaults of the account
        """
        return [{
            'name': account.name,
            'address': account.address,
            'base_dn': _custom_field(account, 'base_dn'),
            'search_filter': _custom_field(account, 'search_filter'),
            'hostname_field': _custom_field(account, 'hostname_field'),
        } for account in Account.objects(enabled=True, type='ldap').order_by('name')]

    @staticmethod
    def _limit(value):
        """
        Number of objects to fetch, kept in a sane range
        """
        try:
            return max(1, min(int(value), MAX_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    def _config(self, form):
        """
        Account settings of the search, with the overwrites of the form
        applied. Raises LdapSearchError if the account cannot be searched.
        """
        try:
            config = get_account_by_name(form['account'])
        except AccountNotFoundError as error:
            raise LdapSearchError(f"Account '{form['account']}' not found") from error

        config['base_dn'] = form['base_dn'] or config.get('base_dn') or ''
        # An empty attribute list asks the server for everything, which is
        # what makes a search useful — the account's list is only meant for
        # the import
        config['attributes'] = form['attributes']
        for field in REQUIRED_FIELDS:
            if not config.get(field):
                raise LdapSearchError(f"The account has no '{field}' set")
        return config

    @expose('/')
    def index(self):
        """
        Show the search form and, if one was asked for, its result
        """
        # A search is read only, so it travels in the URL and stays linkable
        args = request.args
        submitted = bool(args.get('searched'))
        form = {
            'account': args.get('account', ''),
            'mode': args.get('mode', 'hostname'),
            'term': args.get('term', ''),
            'attribute': args.get('attribute', ''),
            'base_dn': args.get('base_dn', '').strip(),
            'attributes': args.get('attributes', '').strip(),
            'limit': args.get('limit', str(DEFAULT_LIMIT)),
            # Only a submitted form can say the filter is unwanted
            'use_account_filter': args.get('use_account_filter') == 'on' if submitted else True,
        }

        error = None
        query = ''
        results = None
        limit = self._limit(form['limit'])
        if submitted:
            try:
                config = self._config(form)
                query = build_search_filter(config, form['mode'], form['term'],
                                            form['attribute'], form['use_account_filter'])
                results = search_objects(config, query, limit=limit)
            except LdapSearchError as search_error:
                error = str(search_error)

        return self.render(
            'admin/ldap_search.html',
            accounts=self._accounts(),
            modes=SEARCH_MODES,
            form=form,
            limit=limit,
            query=query,
            results=results,
            error=error,
            ldap_available=LDAP_AVAILABLE,
        )
