"""
Checkmk Helpers
"""
import re

def cmk_cleanup_tag_id(input_str):
    """
    Cleans Invalid Chars out
    of strings you wan't to use as tag_id in cmk
    """
    return re.sub('[^a-zA-Z0-9_-]', '_', input_str.strip()).lower()
