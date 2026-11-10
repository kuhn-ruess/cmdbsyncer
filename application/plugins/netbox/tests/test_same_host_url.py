"""
The page link of a Netbox answer carries the token on the next request,
so it is pinned to the host of the account.
"""
# pylint: disable=missing-function-docstring
import unittest

from application.plugins.netbox.utils import same_host_url


class TestSameHostUrl(unittest.TestCase):
    """Page links of the Dataflow sync."""

    def test_link_to_another_host_stays_on_the_account(self):
        self.assertEqual(
            same_host_url('https://evil.example/api/plugins/data-flows/x/?limit=50&offset=50',
                          'https://netbox.example.com'),
            'https://netbox.example.com/api/plugins/data-flows/x/?limit=50&offset=50')

    def test_link_of_the_own_host_is_kept(self):
        url = 'https://netbox.example.com:8443/api/plugins/data-flows/x/?offset=50'
        self.assertEqual(same_host_url(url, 'https://netbox.example.com:8443'), url)

    def test_scheme_follows_the_account(self):
        # Behind a TLS proxy Netbox may answer with http links
        self.assertEqual(
            same_host_url('http://netbox.example.com/api/x/?offset=50',
                          'https://netbox.example.com'),
            'https://netbox.example.com/api/x/?offset=50')
