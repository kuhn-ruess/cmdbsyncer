"""
Overview page for a module menu.

Every module under "Modules" carries an "Overview" entry at the top of its
menu. It opens a page that lays out the same menu as tiles — one per entry,
each with a sentence on what it does — plus a short introduction to the
module itself. The tiles are read straight from the live Flask-Admin menu,
so an entry added by a plugin shows up here without a second list to keep
in sync; only its description comes from ``application.module_registry``.
"""
import re

from flask import redirect, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application.module_registry import (
    get_category_description,
    get_entry_description,
    get_module_icon,
    get_module_info,
)


def _endpoint_for(module):
    """A stable, unique Flask endpoint out of a menu name."""
    slug = re.sub(r'[^a-z0-9]+', '_', module.lower()).strip('_')
    return f'module_overview_{slug}'


class ModuleOverviewView(BaseView):
    """
    Tile overview of one module menu: introduction, the module's own
    entries, and a section per sub menu. Read-only — every tile just links
    to the view the menu entry points at.
    """

    def __init__(self, module, **kwargs):
        self.module = module
        super().__init__(**kwargs)

    #   .-- Menu access
    def _category(self):
        """The menu category this overview belongs to."""
        if self.admin is None:
            return None
        return self.admin.get_category_menu_item(self.module)

    def _siblings(self):
        """
        The category's other entries.

        Deliberately reads ``_children`` instead of ``get_children()``:
        the latter asks every child whether it is accessible, this view
        included, which would recurse straight back into ``is_accessible``.
        """
        category = self._category()
        if category is None:
            return []
        return [child for child in category._children  # pylint: disable=protected-access
                if getattr(child, '_view', None) is not self]

    @staticmethod
    def _visible(item):
        """Menu items a user may see."""
        return item.is_accessible() and item.is_visible()

    @staticmethod
    def _overview_url(category):
        """URL of a sub menu's own Overview entry, if it has one."""
        for child in category._children:  # pylint: disable=protected-access
            if isinstance(getattr(child, '_view', None), ModuleOverviewView):
                return child.get_url()
        return None
    #.

    def is_accessible(self):
        """
        Visible exactly as long as the module itself is: without a single
        reachable entry the overview would be an empty page — and would
        keep the whole module menu on screen for a user who may not use it.
        """
        if not current_user.is_authenticated:
            return False
        return any(self._visible(child) for child in self._siblings())

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin.index'))

    #   .-- Rendering
    def _tile(self, item, sub_menu=None):
        """One menu entry as a tile."""
        return {
            'name': item.name,
            'url': item.get_url(),
            'icon_type': item.get_icon_type(),
            'icon_value': item.get_icon_value(),
            'description': get_entry_description(self.module, item.name, sub_menu),
        }

    def _category_tile(self, category):
        """A sub menu that has its own overview page — one tile, one link."""
        return {
            'name': category.name,
            'url': self._overview_url(category),
            'icon_type': category.get_icon_type(),
            'icon_value': category.get_icon_value(),
            'description': (get_module_info(category.name).get('intro')
                            or get_category_description(category.name)),
        }

    def _sections(self):
        """
        The page content: the module's own entries first, then one section
        per sub menu that has no overview page of its own.
        """
        own = []
        sections = []
        for child in self._siblings():
            if not self._visible(child):
                continue
            if 'dropdown-divider' in (child.get_class_name() or ''):
                continue
            if not child.is_category():
                own.append(self._tile(child))
            elif self._overview_url(child):
                own.append(self._category_tile(child))
            else:
                tiles = [self._tile(entry, sub_menu=child.name)
                         for entry in child.get_children()
                         if not entry.is_category()]
                if tiles:
                    sections.append({
                        'name': child.name,
                        'description': get_category_description(child.name),
                        'tiles': tiles,
                    })
        if own:
            sections.insert(0, {'name': None, 'description': '', 'tiles': own})
        return sections
    #.

    @expose('/')
    def index(self):
        """Render the module's entries as tiles."""
        info = get_module_info(self.module)
        icon_type, icon_value = get_module_icon(self.module)
        return self.render(
            'admin/module_overview.html',
            module=self.module,
            intro=info.get('intro', ''),
            docs_url=info.get('docs'),
            icon_type=icon_type,
            icon_value=icon_value,
            sections=self._sections(),
        )


def register_module_menu(admin, module):
    """
    Prepare a module menu: put the vendor mark on the category and add the
    Overview entry.

    Call it directly after ``add_sub_category`` — Flask-Admin keeps the
    registration order, so registering first is what puts "Overview" at the
    top of the menu.
    """
    category = admin.get_category_menu_item(module)
    icon_type, icon_value = get_module_icon(module)
    if category is not None and icon_type:
        # add_sub_category() creates the category without any icon, so the
        # module marks have to be attached to the menu item afterwards.
        category.icon_type = icon_type
        category.icon_value = icon_value

    admin.add_view(ModuleOverviewView(
        module=module,
        name="Overview",
        endpoint=_endpoint_for(module),
        category=module,
        menu_icon_type='fa',
        menu_icon_value='fa-th-large',
    ))
