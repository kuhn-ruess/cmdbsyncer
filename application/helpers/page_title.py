"""
Browser tab title of the admin pages.

Flask-Admin titles every page "Category - View - cmdbsyncer <version>":
the tab cuts that off before the part that tells the pages apart, and an
edit, a debug or the list of the same view all read the same. This puts
the most specific part first: what the page does, on which object, in
which view and menu — "Edit web01 · Hosts · Objects – cmdbsyncer".
"""
from flask import current_app, request

# Flask-Admin endpoints of a model view and how the title names them.
# The list is the view itself and needs no extra word.
_PAGE_NAMES = {
    'index': '',
    'index_view': '',
    'create_view': 'New',
    'edit_view': 'Edit',
    'details_view': 'Details',
    'clone_view': 'Clone',
}

# Attributes that name a document, in the order they are tried.
_NAME_FIELDS = ('hostname', 'name', 'email')


def _page_name():
    """What the page does, from the endpoint of the request."""
    endpoint = (request.endpoint or '').rsplit('.', 1)[-1]
    if endpoint in _PAGE_NAMES:
        return _PAGE_NAMES[endpoint]
    # Own pages: `set_template_form` -> "Set Template"
    for suffix in ('_form', '_view'):
        endpoint = endpoint.removesuffix(suffix)
    return endpoint.replace('_', ' ').title()


def _object_name(obj):
    """The name of the document the page is about, if it has one."""
    for field in _NAME_FIELDS:
        value = getattr(obj, field, None)
        if isinstance(value, str) and value:
            return value
    return ''


def _menu_path(view):
    """
    The menu categories of the view, innermost first. The top level
    ("Modules", "Settings") is dropped below a sub menu: "Rules · Ansible"
    already says where the page is.
    """
    path = []
    category = view.admin.get_category_menu_item(view.category) \
        if view.category else None
    while category is not None:
        path.append(category.name)
        category = category.parent
    if len(path) > 1:
        path.pop()
    return [name for name in path if name != view.name]


def page_title(view, obj=None):
    """Title of an admin page, most specific part first."""
    page = ' '.join(part for part in (_page_name(), _object_name(obj)) if part)
    parts = [page, view.name, *_menu_path(view)]
    title = ' · '.join(part for part in parts if part)
    brand = f"cmdbsyncer {current_app.config.get('HEADER_HINT') or ''}".strip()
    return f'{title} – {brand}'
