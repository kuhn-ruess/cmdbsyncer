"""
The edition suffixes of omd, renamed with Checkmk 2.5
"""
import re

# The edition up to 2.4 and its name since 2.5
EDITION_RENAMES = {'cee': 'pro', 'cre': 'community', 'cce': 'ultimate', 'cme': 'ultimatemt'}


def edition_for_version(edition, version):
    """
    The edition suffix omd uses for ``version``: an edition of the other
    naming is translated, cee for 2.5 is pro, pro for 2.4 is cee.
    Unchanged without a version to compare.
    """
    match = re.match(r'(\d+)\.(\d+)\.', version or '')
    if not match or not edition:
        return edition
    if (int(match.group(1)), int(match.group(2))) >= (2, 5):
        return EDITION_RENAMES.get(edition, edition)
    return {new: old for old, new in EDITION_RENAMES.items()}.get(edition, edition)
