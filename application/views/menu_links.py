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


class NavDivider(AccessMenuLink):  # pylint: disable=too-few-public-methods
    """
    A separator between groups of top bar entries.

    Flask-Admin only knows dividers inside a dropdown; in the horizontal
    navbar it renders every link as an ``<a class="nav-link ...">``. So
    this one carries no name and no icon and is turned into a thin rule by
    the ``nav-divider`` class (see ``templates/admin/master.html``).

    Pass an ``access`` predicate that is false whenever one of the groups
    it separates is empty for this user, otherwise the rule floats at the
    start or the end of the bar.
    """

    def __init__(self, access=None):
        super().__init__(name='', url='#', class_name='nav-divider',
                         access=access)
