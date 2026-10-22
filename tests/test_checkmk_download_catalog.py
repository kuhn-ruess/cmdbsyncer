"""
The versions and installation files of checkmk.com, reduced for the
fill-in help of the Checkmk Settings form.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import patch, MagicMock

import requests

from application.plugins.checkmk import download_catalog


def _catalog():
    return {'checkmk': {
        '2.4.0': {'version': '2.4.0p12', 'class': 'stable', 'editions': {
            'pro': {
                'noble': ['check-mk-enterprise-2.4.0p12_0.noble_amd64.deb', 'sha'],
                'el9': ['check-mk-enterprise-2.4.0p12-el9-38.x86_64.rpm', 'sha'],
                'docker': ['check-mk-enterprise-docker-2.4.0p12.tar.gz', 'sha'],
            },
        }},
        '2.5.0': {'version': '2.5.0p3', 'class': 'stable', 'editions': {
            'pro': {'cma-4': ['check-mk-pro-2.5.0p3-4-x86_64.cma', 'sha']},
        }},
        '2.10.0': {'version': '2.10.0', 'class': 'beta', 'editions': {
            'community': {'noble': ['check-mk-community-2.10.0_0.noble_amd64.deb', 'sha']},
        }},
        '2.0.0': {'version': '2.0.0p39', 'class': 'oldstable', 'editions': {
            'pro': {},
        }},
    }}


class TestSimplify(unittest.TestCase):

    def test_newest_major_first(self):
        majors = download_catalog.simplify(_catalog())
        # Compared as numbers: 2.10 is newer than 2.5
        self.assertEqual([m['major'] for m in majors], ['2.10.0', '2.5.0', '2.4.0'])

    def test_the_version_becomes_a_placeholder(self):
        majors = {m['major']: m for m in download_catalog.simplify(_catalog())}
        files = majors['2.4.0']['editions']['pro']
        self.assertEqual(files['noble'],
                         'check-mk-enterprise-{{CMK_VERSION}}_0.noble_amd64.deb')
        self.assertEqual(files['el9'],
                         'check-mk-enterprise-{{CMK_VERSION}}-el9-38.x86_64.rpm')
        self.assertEqual(majors['2.4.0']['version'], '2.4.0p12')

    def test_docker_images_and_empty_majors_are_left_out(self):
        majors = {m['major']: m for m in download_catalog.simplify(_catalog())}
        self.assertNotIn('docker', majors['2.4.0']['editions']['pro'])
        self.assertNotIn('2.0.0', majors)

    def test_an_empty_answer_gives_no_versions(self):
        self.assertEqual(download_catalog.simplify({}), [])


class TestFetch(unittest.TestCase):

    @patch('application.modules.plugin.render_jinja', side_effect=lambda value: value)
    def test_the_proxy_is_used(self, _render):
        response = MagicMock()
        response.json.return_value = _catalog()
        with patch.object(download_catalog.requests, 'get',
                          return_value=response) as get:
            download_catalog.fetch('http://proxy.example.com:3128')
        self.assertEqual(get.call_args.kwargs['proxies'],
                         {'http': 'http://proxy.example.com:3128',
                          'https': 'http://proxy.example.com:3128'})

    def test_no_internet_access_raises_for_the_view(self):
        with patch.object(download_catalog.requests, 'get',
                          side_effect=requests.exceptions.ConnectionError('down')):
            with self.assertRaises(requests.exceptions.RequestException):
                download_catalog.fetch()


if __name__ == '__main__':
    unittest.main()
