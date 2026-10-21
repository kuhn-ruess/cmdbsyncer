"""
Smoke test of the Checkmk Configuration Checks PDF export against the real
web application: the Export PDF endpoint answers with a PDF download for
canned findings. Checkmk is not contacted, the checks are replaced.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


PDF_EXPORT = '''
from application.models.account import Account
from application.plugins.checkmk import config_checks
from application.plugins.checkmk.config_checks.httpv2 import (
    HttpV2Check, failing_findings)

Account(name='cmk-test', type='cmkv2', enabled=True).save()


class Report(HttpV2Check):
    """The real check with canned findings instead of Checkmk calls."""
    def analyze(self, cmk):
        findings = failing_findings([{
            'host_name': 'srv01', 'description': 'HTTPS Website', 'state': 2,
            'output': 'Connection refused', 'legacy': False}], [])
        return findings, [('HTTP checks not OK', 1)]


config_checks.run_checks = lambda account, names: [Report().run(None, account)]

body = client.get('/login').get_data(as_text=True)
token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body).group(1)
client.post('/login', data={'login_email': 'smoke@example.com',
                            'password': 'smoke-password', 'otp': '',
                            'login_submit': 'Login', 'csrf_token': token})

response = check('/admin/checkmk_config_checks/report', 200, method='post',
                 data={'account': 'cmk-test', 'checks': 'httpv2',
                       'csrf_token': csrf('/admin/checkmk_config_checks/')})
eq(response.mimetype, 'application/pdf', 'mimetype')
eq(response.data[:5], b'%PDF-', 'PDF header')
eq(response.data.rstrip()[-5:], b'%%EOF', 'PDF trailer')
disposition = response.headers.get('Content-Disposition', '')
if not re.match(r'attachment; filename="checkmk-config-checks-cmk-test-'
                r'\\d{4}-\\d{2}-\\d{2}\\.pdf"$', disposition):
    fail(f'Content-Disposition {disposition!r}')
print('PDF_EXPORT_OK')
'''


# fpdf2 made unimportable: the page still loads, the checks still run, the
# button is disabled with the install hint and the endpoint answers with a
# message instead of a 500.
WITHOUT_FPDF = """
import sys
sys.modules['fpdf'] = None
""" + PDF_EXPORT.split("response = check(", 1)[0] + """
page = check('/admin/checkmk_config_checks/', 200).get_data(as_text=True)
if 'pip install fpdf2' not in page:
    fail('install hint missing on the page')
check('/admin/checkmk_config_checks/run', 200, method='post',
      data={'account': 'cmk-test', 'checks': 'httpv2',
            'csrf_token': csrf('/admin/checkmk_config_checks/')})
response = check('/admin/checkmk_config_checks/report', 302, method='post',
                 data={'account': 'cmk-test', 'checks': 'httpv2',
                       'csrf_token': csrf('/admin/checkmk_config_checks/')})
page = client.get(response.headers['Location']).get_data(as_text=True)
if 'pip install fpdf2' not in page:
    fail('no install message after Export PDF')
print('WITHOUT_FPDF_OK')
"""

try:
    import fpdf  # noqa: F401  pylint: disable=unused-import
    HAVE_FPDF = True
except ImportError:
    HAVE_FPDF = False


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestConfigChecksPdfSmoke(unittest.TestCase):
    """Export PDF returns a PDF file download, or says what is missing."""

    def test_without_fpdf(self):
        """Page and checks work without fpdf2, the export explains why not."""
        result = run_against_app(WITHOUT_FPDF, 'False')
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn('WITHOUT_FPDF_OK', result.stdout)

    @unittest.skipUnless(HAVE_FPDF, "fpdf2 (cmdbsyncer[extras]) is not installed")
    def test_export_pdf_download(self):
        """Export PDF answers with a PDF attachment."""
        result = run_against_app(PDF_EXPORT, 'False')
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn('PDF_EXPORT_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
