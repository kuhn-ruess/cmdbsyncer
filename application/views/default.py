"""
Default Model Views
"""
# pylint: disable=trailing-whitespace,line-too-long,raise-missing-from,broad-exception-caught
import os
import re
import html
from copy import deepcopy
from flask import url_for, redirect, flash, request
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


def _load_changelog():
    """Return the current release's changelog markdown.

    In source checkouts the symlink ``<repo>/changelog.md`` points at the
    active ``changelog/v{MAJOR}.{MINOR}.md`` file. PyPI installs ship that
    same file as ``application/changelog.md`` via package-data, generated
    by ``tools/sync_changelog.py`` at build time.
    """
    packaged = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'changelog.md')
    if os.path.isfile(packaged):
        with open(packaged, 'r', encoding='utf-8') as fh:
            return fh.read()
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    for candidate in (
        os.path.join(repo_root, 'changelog.md'),
        os.path.join(repo_root, 'changelog', _major_minor_filename()),
    ):
        if os.path.isfile(candidate):
            with open(candidate, 'r', encoding='utf-8') as fh:
                return fh.read()
    raise FileNotFoundError('changelog')


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

    def _markdown_to_html(self, text):
        """
        Simple Markdown to HTML converter for basic formatting
        """
        if not text:
            return text
            
        lines = text.split('\n')
        html_lines = []
        in_list = False
        
        for line in lines:
            stripped = line.strip()
            
            # Handle headers
            if stripped.startswith('###'):
                html_lines.append(f'<h3>{html.escape(stripped[3:].strip())}</h3>')
            elif stripped.startswith('##'):
                html_lines.append(f'<h2>{html.escape(stripped[2:].strip())}</h2>')
            elif stripped.startswith('#'):
                html_lines.append(f'<h1>{html.escape(stripped[1:].strip())}</h1>')
            # Handle list items
            elif stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul>')
                    in_list = True
                html_lines.append(f'<li>{html.escape(stripped[2:].strip())}</li>')
            # Handle empty lines and regular text
            else:
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                if stripped:  # Non-empty line
                    html_lines.append(f'<p>{html.escape(stripped)}</p>')
                else:  # Empty line
                    html_lines.append('<br>')
        
        # Close any open list
        if in_list:
            html_lines.append('</ul>')
            
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
            changelog_html = self._markdown_to_html(_load_changelog())
        except FileNotFoundError:
            changelog_html = "<p>Changelog not found.</p>"
        except Exception:
            changelog_html = "<p>Error loading changelog.</p>"

        notices = self._load_notices()

        return self.render('admin/index.html', changelog_html=changelog_html, notices=notices)
