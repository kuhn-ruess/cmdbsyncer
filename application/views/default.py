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


def _changelog_search_dirs():
    """Return the directories we look into for changelog files."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    package_root = os.path.dirname(os.path.dirname(__file__))
    return [
        os.path.join(repo_root, 'changelog'),
        os.path.join(package_root, 'changelog'),
    ]


def _load_changelog():
    """Return the current release's changelog markdown.

    In source checkouts the symlink ``<repo>/changelog.md`` points at the
    active ``changelog/v{MAJOR}.{MINOR}.md`` file. PyPI installs ship that
    same file as ``application/changelog.md`` via package-data, generated
    by ``tools/sync_changelog.py`` at build time. The repo-root sources
    win when present so a stale packaged copy in a source checkout cannot
    shadow the live file.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    packaged = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'changelog.md')
    for candidate in (
        os.path.join(repo_root, 'changelog.md'),
        os.path.join(repo_root, 'changelog', _major_minor_filename()),
        packaged,
    ):
        if os.path.isfile(candidate):
            with open(candidate, 'r', encoding='utf-8') as fh:
                return fh.read()
    raise FileNotFoundError('changelog')


def _load_changelog_file(name):
    """Return markdown for a specific ``v{MAJOR}.{MINOR}.md`` file or None."""
    if not _CHANGELOG_FILENAME_RE.match(name):
        return None
    for base in _changelog_search_dirs():
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            with open(candidate, 'r', encoding='utf-8') as fh:
                return fh.read()
    return None


def _list_other_changelogs():
    """Return previous ``v*.md`` files, newest first, excluding the current one.

    Deduplicates between the repo source directory and the packaged copy so
    the same ``vX.Y.md`` is not offered twice.
    """
    current = _major_minor_filename()
    seen = {}
    for base in _changelog_search_dirs():
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if not _CHANGELOG_FILENAME_RE.match(name):
                continue
            if name == current:
                continue
            seen.setdefault(name, name)

    def _version_tuple(name):
        # "v3.12.md" → (3, 12). Used to order newest-first.
        parts = name[1:-3].split('.')
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)

    return sorted(seen, key=_version_tuple, reverse=True)


def _major_minor_filename():
    """Return ``v{MAJOR}.{MINOR}.md`` for the running version."""
    parts = __version__.split('.')
    return f"v{parts[0]}.{parts[1]}.md"


class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """
    page_size = 300
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-clone", ".clone_view"),
    ]

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

    def _markdown_to_html(self, text, collapse_sections=False):
        """
        Simple Markdown to HTML converter for basic formatting.

        If ``collapse_sections`` is True, every ``## ...`` heading starts
        a ``<details>`` block — the first one is ``open`` by default, the
        rest are collapsed. That keeps the changelog discoverable but
        stops the admin index from turning into a wall of history.
        """
        if not text:
            return text

        lines = text.split('\n')
        html_lines = []
        in_list = False
        open_details = False
        seen_h2 = False

        def _close_list():
            nonlocal in_list
            if in_list:
                html_lines.append('</ul>')
                in_list = False

        def _close_details():
            nonlocal open_details
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
                _close_list()
                title = stripped[2:].strip()
                if collapse_sections:
                    _close_details()
                    open_attr = '' if seen_h2 else ' open'
                    html_lines.append(f'<details{open_attr}>')
                    html_lines.append(f'<summary><h2 style="display:inline">{html.escape(title)}</h2></summary>')
                    open_details = True
                    seen_h2 = True
                else:
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
                else:  # Empty line
                    html_lines.append('<br>')

        _close_list()
        _close_details()

        return '\n'.join(html_lines)

    def _load_notices(self):
        """
        Load all notice files from the notices/ directory.
        Returns list of dicts with 'id' and 'content'.

        PyPI installs ship the files as ``application/notices/*.txt`` via
        package-data (synced by ``tools/sync_notices.py`` at build time);
        source checkouts fall back to the repo-root ``notices/`` directory.
        """
        notices = []
        packaged_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'notices')
        repo_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'notices')
        notices_dir = packaged_dir if os.path.isdir(packaged_dir) else repo_dir
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
