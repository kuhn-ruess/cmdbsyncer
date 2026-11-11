"""
The SSH private key of the Checkmk Settings is checked before it is stored.
"""
# pylint: disable=missing-function-docstring
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from application.plugins.checkmk.ssh_key import check_ssh_private_key


def _key(private_format=serialization.PrivateFormat.OpenSSH,
         encryption=serialization.NoEncryption()):
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, private_format, encryption).decode()


class SshKeyTest(unittest.TestCase):
    """Accepted keys come back in the form ssh needs"""

    def test_key_gets_unix_line_ends_and_final_newline(self):
        pasted = _key().strip().replace('\n', '\r\n')
        key = check_ssh_private_key(pasted)
        self.assertNotIn('\r', key)
        self.assertTrue(key.endswith('-----\n'))

    def test_pem_key_is_accepted(self):
        pem = _key(serialization.PrivateFormat.PKCS8)
        self.assertIn('BEGIN PRIVATE KEY', check_ssh_private_key(pem))

    def test_key_with_passphrase_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'passphrase'):
            check_ssh_private_key(_key(
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b'secret')))

    def test_public_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'not an SSH private key'):
            check_ssh_private_key('ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI srv01')


if __name__ == '__main__':
    unittest.main()
