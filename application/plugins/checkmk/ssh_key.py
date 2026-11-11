"""
Check of the SSH private key the Checkmk Settings keep for the servers.
"""
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization


def check_ssh_private_key(key):
    """
    The key in the form ssh needs it (LF line ends, final newline), or a
    ValueError. The run happens in the background, so a key that needs a
    passphrase would only fail there: it is refused here.
    """
    key = key.replace('\r\n', '\n').strip() + '\n'
    loader = serialization.load_ssh_private_key \
        if 'OPENSSH PRIVATE KEY' in key else serialization.load_pem_private_key
    try:
        loader(key.encode(), password=None)
    except TypeError as exp:
        raise ValueError("The SSH private key is protected by a passphrase, "
                         "use a key without one") from exp
    except (ValueError, UnsupportedAlgorithm) as exp:
        raise ValueError("This is not an SSH private key") from exp
    return key
