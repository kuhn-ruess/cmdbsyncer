"""
Default Model Views
"""
# pylint: disable=trailing-whitespace,line-too-long,raise-missing-from,broad-exception-caught
import os
import re
import html
from copy import deepcopy
from flask import url_for, redirect, flash, request, abort
from flask_login import current_user
from flask_admin import AdminIndexView
from flask_admin import expose
from flask_admin.contrib.mongoengine import ModelView
from flask_admin.model.template import EndpointLinkRowAction
from flask_admin.helpers import get_redirect_target
from flask_admin.model.helpers import get_mdict_item_or_list

from wtforms.validators import ValidationError

from mongoengine.errors import NotUniqueError

from application._version import __version__


# Only filenames matching this pattern can be served via the old-changelog
# endpoint. This is the whitelist that prevents path traversal / arbitrary
# file reads through a user-supplied ``name`` parameter.
_CHANGELOG_FILENAME_RE = re.compile(r'^v\d+\.\d+\.md$')


_CHANGELOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'changelog')


def _major_minor_filename():
    """Return ``v{MAJOR}.{MINOR}.md`` for the running version."""
    parts = __version__.split('.')
    return f"v{parts[0]}.{parts[1]}.md"


def _load_changelog():
    """Return the current release's ``v{MAJOR}.{MINOR}.md`` markdown."""
    path = os.path.join(_CHANGELOG_DIR, _major_minor_filename())
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _load_changelog_file(name):
    """Return markdown for a specific ``v{MAJOR}.{MINOR}.md`` file or None."""
    if not _CHANGELOG_FILENAME_RE.match(name):
        return None
    path = os.path.join(_CHANGELOG_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _list_other_changelogs():
    """Return previous ``v*.md`` files, newest first, excluding the current one."""
    if not os.path.isdir(_CHANGELOG_DIR):
        return []
    current = _major_minor_filename()
    names = [
        name for name in os.listdir(_CHANGELOG_DIR)
        if _CHANGELOG_FILENAME_RE.match(name) and name != current
    ]

    def _version_tuple(name):
        # "v3.12.md" → (3, 12). Used to order newest-first.
        parts = name[1:-3].split('.')
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)

    return sorted(names, key=_version_tuple, reverse=True)


class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """
    page_size = 300
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-clone", ".clone_view"),
    ]

    def _run_view(self, fn, *args, **kwargs):
        """
        Skip Flask-Admin 2.0.2's silent retry-with-cls fallback.

        ``BaseView._run_view`` wraps the view call in
        ``try: fn(self, ...) except TypeError: fn(cls=self, ...)`` for
        backward compatibility with very old Flask-Admin views that took
        ``cls`` as their first arg. None of our views use that
        signature, so the fallback is dead code — and it actively hurts
        us: any genuine ``TypeError`` raised inside a view body gets
        swallowed and re-thrown as a misleading ``unexpected keyword
        argument 'cls'``, masking the real bug.

        Calling ``fn(self, ...)`` once and letting exceptions propagate
        gives us the actual stack trace.
        """
        return fn(self, *args, **kwargs)

    def create_model(self, form):
        """ 
        Create model with NotUniqueError handling
        """
        try:
            return super().create_model(form)
        except NotUniqueError:
            flash("Duplicate Fields in entry", "error")
            return False

    @expose("/clone", methods=("GET", "POST"))
    def clone_view(self):
        """
        Clone given model. GET renders a CSRF-protected confirmation form,
        POST performs the actual clone.
        """
        if request.method == "GET":
            entry_id = get_mdict_item_or_list(request.args, 'id')
            return_url = get_redirect_target() or self.get_url('.index_view')
            return self.render(
                'admin/model/clone_confirm.html',
                entry_id=entry_id,
                return_url=return_url,
            )

        entry_id = get_mdict_item_or_list(request.form, 'id')

        # Duplicate current record
        return_url = request.form.get('url') or self.get_url('.index_view')

        if not self.can_create:
            return redirect(return_url)

        old_model = self.get_one(entry_id)
        if old_model is None:
            flash('Entry does not exist.', 'error')
            return redirect(return_url)

        obj = deepcopy(old_model)
        obj.id = None
        if hasattr(obj, 'name'):
            obj.name += " (Clone)"
        try:
            obj.save()
        except NotUniqueError:
            flash('Entry with Name already exist', 'error')
            return redirect(return_url)

        flash("Entry Cloned", 'success')
        return redirect(return_url)

    def handle_view_exception(self, exc):
        """
        Handle view exceptions
        """
        if isinstance(exc, NotUniqueError):
            flash("Duplicate Entry Name - this name already exists", "error")
            return True  # Tell Flask-Admin we handled the exception
        
        # Let Flask-Admin handle other exceptions
        return super().handle_view_exception(exc)

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Fields
        """

        try:
            for attr in [x for x in dir(model) if not x.startswith('_')]:
                current = getattr(model, attr)
                if isinstance(current, str):
                    setattr(model, attr, current.strip())
            return super().on_model_change(form, model, is_created)
        except Exception as e:
            raise ValidationError(f"Error saving entry: {e}")


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))

class IndexView(AdminIndexView):
    """
    Index View Overwrite for auth
    """
    def is_visible(self):
        return False

    def is_accessible(self):
        return current_user.is_authenticated \
                and not current_user.force_password_change

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))

    # pylint: disable-next=too-many-statements,too-many-locals
    def _markdown_to_html(self, text, collapse_sections=False):
        """
        Simple Markdown to HTML converter for basic formatting.

        If ``collapse_sections`` is True, every ``## ...`` heading starts
        a ``<details>`` block — the first one is ``open`` by default, the
        rest are collapsed. The inner body goes into a dedicated
        ``<div class="changelog-body">`` sibling of ``<summary>`` so the
        rendering does not rely on the quirky "heading inside summary"
        pattern (which some browsers / admin themes hid, making the
        expanded sections look empty).
        """
        if not text:
            return text

        lines = text.split('\n')
        html_lines = []
        in_list = False
        in_body = False
        open_details = False
        seen_h2 = False

        def _close_list():
            nonlocal in_list
            if in_list:
                html_lines.append('</ul>')
                in_list = False

        def _close_body():
            nonlocal in_body
            if in_body:
                _close_list()
                html_lines.append('</div>')
                in_body = False

        def _close_details():
            nonlocal open_details
            _close_body()
            if open_details:
                html_lines.append('</details>')
                open_details = False

        for line in lines:
            stripped = line.strip()

            # Handle headers
            if stripped.startswith('###'):
                _close_list()
                html_lines.append(f'<h3>{html.escape(stripped[3:].strip())}</h3>')
            elif stripped.startswith('##'):
                title = stripped[2:].strip()
                if collapse_sections:
                    _close_details()
                    open_attr = '' if seen_h2 else ' open'
                    html_lines.append(f'<details{open_attr}>')
                    html_lines.append(
                        '<summary class="changelog-version">'
                        f'<span class="changelog-version-title">{html.escape(title)}</span>'
                        '</summary>'
                    )
                    html_lines.append('<div class="changelog-body">')
                    open_details = True
                    in_body = True
                    seen_h2 = True
                else:
                    _close_list()
                    html_lines.append(f'<h2>{html.escape(title)}</h2>')
            elif stripped.startswith('#'):
                _close_list()
                html_lines.append(f'<h1>{html.escape(stripped[1:].strip())}</h1>')
            # Handle list items
            elif stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul>')
                    in_list = True
                html_lines.append(f'<li>{html.escape(stripped[2:].strip())}</li>')
            # Handle empty lines and regular text
            else:
                _close_list()
                if stripped:  # Non-empty line
                    html_lines.append(f'<p>{html.escape(stripped)}</p>')
                # Intentional: blank lines no longer emit <br>. With the
                # new body wrapper the <ul>/<p> block model provides the
                # vertical rhythm; stray <br> inside <details> pushed the
                # first list item far enough down that some themes clipped
                # it out of view.

        _close_details()

        return '\n'.join(html_lines)

    def _load_notices(self):
        """
        Load all notice files from ``application/notices/``.
        Returns list of dicts with 'id' and 'content'.
        """
        notices = []
        notices_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'notices')
        if not os.path.isdir(notices_dir):
            return notices
        for filename in sorted(os.listdir(notices_dir)):
            if filename.endswith('.txt'):
                notice_id = filename[:-4]  # strip .txt
                filepath = os.path.join(notices_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    escaped = html.escape(content)
                    linked = re.sub(
                        r'(https?://[^\s]+)',
                        r'<a href="\1" target="_blank">\1</a>',
                        escaped
                    )
                    notices.append({'id': notice_id, 'content': linked})
                except Exception:
                    pass
        return notices

    @expose('/')
    def index(self):
        """
        Index view with changelog
        """
        changelog_html = None
        try:
            changelog_html = self._markdown_to_html(
                _load_changelog(), collapse_sections=True,
            )
        except FileNotFoundError:
            changelog_html = "<p>Changelog not found.</p>"
        except Exception:
            changelog_html = "<p>Error loading changelog.</p>"

        notices = self._load_notices()
        older_changelogs = _list_other_changelogs()

        return self.render(
            'admin/index.html',
            changelog_html=changelog_html,
            notices=notices,
            older_changelogs=older_changelogs,
        )

    @expose('/changelog/<filename>')
    def changelog_archive(self, filename):
        """
        Render a previous ``vX.Y.md`` changelog file on its own page.

        ``filename`` is whitelisted against ``_CHANGELOG_FILENAME_RE`` so
        no arbitrary filesystem path can be requested via the URL.

        The URL parameter is ``filename`` and not ``name`` because
        Flask-Admin's ``BaseView._handle_view`` already takes a ``name``
        kwarg for view resolution, which would collide.
        """
        content = _load_changelog_file(filename)
        if content is None:
            abort(404)
        changelog_html = self._markdown_to_html(content, collapse_sections=True)
        return self.render(
            'admin/changelog_archive.html',
            title=filename[:-3],  # strip ".md"
            changelog_html=changelog_html,
        )
