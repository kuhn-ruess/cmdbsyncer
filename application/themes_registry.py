"""
Theme registry — discovers CSS theme files at startup.

Two roots are scanned:
  - ``application/themes/*.css``  — themes shipped with cmdbsyncer
  - ``plugins/themes/*.css``      — drop-in directory for operators
                                    (gitignored under plugins/)

Each ``.css`` file is one theme. The slug is the filename without
extension (``nord.css`` -> ``nord``); the human label is taken from a
``/* @name: ... */`` header comment in the first 1KB of the file, or
falls back to a title-cased slug.

Shipped themes win on slug collision so a user cannot shadow built-ins
without renaming.
"""
import os
import re
from flask import Blueprint, abort, send_from_directory, current_app

_NAME_RE = re.compile(r'/\*\s*@name\s*:\s*(.+?)\s*\*/', re.IGNORECASE)

# Populated by ``init_themes(app)`` at startup.
_REGISTRY = {}

themes_blueprint = Blueprint('themes', __name__)


def _read_label(path, slug):
    """Pull the ``@name`` from the file header; default to titleized slug."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            head = handle.read(1024)
    except OSError:
        return slug.replace('-', ' ').replace('_', ' ').title()
    match = _NAME_RE.search(head)
    if match:
        return match.group(1).strip()
    return slug.replace('-', ' ').replace('_', ' ').title()


def _scan(directory, source):
    """Yield ``(slug, label, path, source)`` for every .css file in ``directory``."""
    if not directory or not os.path.isdir(directory):
        return
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith('.css'):
            continue
        slug = entry[:-4]
        if not slug or slug == 'default':
            continue
        path = os.path.join(directory, entry)
        if not os.path.isfile(path):
            continue
        yield slug, _read_label(path, slug), path, source


def init_themes(app):
    """Discover all themes and register the serving blueprint."""
    shipped = os.path.join(app.root_path, 'themes')
    user = os.path.join(os.path.dirname(app.root_path), 'plugins', 'themes')
    os.makedirs(user, exist_ok=True)

    registry = {}
    for slug, label, path, source in _scan(shipped, 'shipped'):
        registry[slug] = {'label': label, 'path': path, 'source': source}
    for slug, label, path, source in _scan(user, 'plugin'):
        registry.setdefault(slug, {'label': label, 'path': path, 'source': source})

    _REGISTRY.clear()
    _REGISTRY.update(registry)
    app.extensions['theme_registry'] = _REGISTRY


def get_choices():
    """List of ``(slug, label)`` tuples for SelectField use; default first."""
    items = sorted(_REGISTRY.items(), key=lambda kv: kv[1]['label'].lower())
    return [('default', 'Default')] + [(slug, meta['label']) for slug, meta in items]


def is_known(slug):
    """True for the built-in ``default`` slug or any discovered theme."""
    return slug == 'default' or slug in _REGISTRY


@themes_blueprint.route('/themes/<slug>.css')
def serve(slug):
    """Serve a discovered theme CSS. Anything not in the registry 404s,
    which also blocks path traversal (slug is used as a key, never a
    path segment)."""
    meta = _REGISTRY.get(slug)
    if not meta:
        abort(404)
    directory, filename = os.path.split(meta['path'])
    response = send_from_directory(directory, filename, mimetype='text/css')
    # Always revalidate — themes are edited live (operators tweak
    # CSS, ship a new release). ``send_from_directory`` already adds
    # ETag + Last-Modified, so revalidation is a cheap 304 in the
    # common case.
    response.headers['Cache-Control'] = 'no-cache'
    return response


# Keep current_app import alive for IDE imports; used implicitly via
# the Flask blueprint's request context.
_ = current_app
