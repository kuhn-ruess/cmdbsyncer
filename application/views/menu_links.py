"""
Access-aware Flask-Admin menu links.

A plain ``MenuLink`` (including the divider links) is always visible, which
keeps its whole category on screen even for users who can reach none of the
category's real views. ``AccessMenuLink`` ties a link's visibility to a
predicate so, e.g., the "Edit local_config.py" link and the Settings
dividers disappear for users without the matching permission — and with no
visible children left, the Settings menu itself hides.
"""
from flask_admin.menu import MenuLink


class AccessMenuLink(MenuLink):  # pylint: disable=too-few-public-methods
    """A MenuLink whose visibility is gated by an ``access`` predicate."""

    def __init__(self, *args, access=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._access = access or (lambda: True)

    def is_accessible(self):
        try:
            return bool(self._access())
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def is_visible(self):
        # Tie visibility to access so a hidden link never keeps its category
        # (Settings) on screen for a user who cannot use it.
        return self.is_accessible()
