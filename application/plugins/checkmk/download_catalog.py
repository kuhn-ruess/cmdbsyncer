"""
The Checkmk versions and installation files checkmk.com offers, for the
fill-in help of the Checkmk Settings form.
"""
import requests

from application.modules.plugin import parse_proxy

CATALOG_URL = 'https://download.checkmk.com/stable_downloads.json'

# Edition of the Checkmk Settings (the omd version suffix) -> the edition
# name the catalog uses. The catalog names every version by the editions
# of 2.5, the suffixes up to 2.4 were cee/cre/cce/cme.
CATALOG_EDITION = {
    'cee': 'pro',
    'cre': 'community',
    'cce': 'ultimate',
    'cme': 'ultimatemt',
    'pro': 'pro',
    'community': 'community',
    'ultimate': 'ultimate',
    'ultimatemt': 'ultimatemt',
}

# Platforms without an installation file the site management can use.
_SKIPPED_PLATFORMS = {'docker'}


def _major_key(major):
    return tuple(int(part) for part in major.split('.') if part.isdigit())


def simplify(catalog):
    """
    The catalog reduced to what the form needs: per major version, newest
    first, its current version and per edition and platform the filename
    with the version replaced by ``{{CMK_VERSION}}``, so the filename keeps
    fitting when only the version is changed later.
    """
    majors = []
    for major, entry in (catalog.get('checkmk') or {}).items():
        version = entry.get('version')
        if not version:
            continue
        editions = {}
        for edition, platforms in (entry.get('editions') or {}).items():
            files = {platform: data[0].replace(version, '{{CMK_VERSION}}')
                     for platform, data in platforms.items()
                     if platform not in _SKIPPED_PLATFORMS and data}
            if files:
                editions[edition] = files
        if editions:
            majors.append({'major': major, 'version': version,
                           'class': entry.get('class', ''),
                           'editions': editions})
    majors.sort(key=lambda entry: _major_key(entry['major']), reverse=True)
    return majors


def fetch(proxy=None):
    """
    Load and simplify the catalog, through ``proxy`` when one is given
    (a URL, see parse_proxy). Raises requests exceptions on failure.
    Only called when a user asks for it in the form, never on its own.
    """
    # Short timeouts: the Syncer often has no internet access at all, the
    # form must answer quickly then instead of hanging.
    response = requests.get(CATALOG_URL, timeout=(5, 10),
                            proxies=parse_proxy(proxy, 'Checkmk Settings'))
    response.raise_for_status()
    return simplify(response.json())
