"""
Which search filter one LDAP search in the web interface really runs
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest

from application.plugins.ldap.ldap import (
    LDAP_AVAILABLE,
    build_search_filter,
    default_account_filter,
)


ACCOUNT = {
    'hostname_field': 'cn',
    'search_filter': '(objectClass=computer)',
}


class DefaultAccountFilterTest(unittest.TestCase):
    """application.plugins.ldap.ldap"""

    def test_a_hostname_search_keeps_the_filter_of_the_account(self):
        # Searching a host is what the account describes, so its filter
        # is what makes the result match the import
        self.assertTrue(default_account_filter('hostname'))
        self.assertTrue(default_account_filter('contains'))
        self.assertTrue(default_account_filter('attribute'))

    def test_an_own_filter_starts_without_the_one_of_the_account(self):
        # A typed filter and a group name describe the objects
        # themselves; the account's filter matches the imported hosts and
        # would only ever exclude them
        self.assertFalse(default_account_filter('filter'))
        self.assertFalse(default_account_filter('group'))


@unittest.skipUnless(LDAP_AVAILABLE, "python-ldap escapes the search term")
class BuildSearchFilterTest(unittest.TestCase):
    """application.plugins.ldap.ldap"""

    def test_an_own_filter_is_used_alone(self):
        query = build_search_filter(ACCOUNT, 'filter', '(objectClass=group)',
                                    use_account_filter=False)
        self.assertEqual(query, '(objectClass=group)')

    def test_an_own_filter_can_be_combined_with_the_account(self):
        query = build_search_filter(ACCOUNT, 'filter', '(cn=srv*)',
                                    use_account_filter=True)
        self.assertEqual(query, '(&(objectClass=computer)(cn=srv*))')

    def test_a_term_without_brackets_becomes_a_filter(self):
        query = build_search_filter(ACCOUNT, 'filter', 'objectClass=group',
                                    use_account_filter=False)
        self.assertEqual(query, '(objectClass=group)')


if __name__ == '__main__':
    unittest.main()
