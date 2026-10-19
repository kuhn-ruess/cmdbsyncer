"""
The "Secrets" row of the host Overview.

Lists the Secret Store entries bound to the host: key, kind, the reference
to use in rules and links to the entry. Values are never shown here; the
"Show value" link goes through the store's own reveal page, which checks
role and scope again. Who sees what follows ``secret_access``: without the
Secret Store role, or for a host outside the user's scope, the row stays
empty.
"""
from markupsafe import Markup, escape
from flask import url_for
from flask_login import current_user

from application.helpers.secret_access import can_manage, can_reveal, host_in_scope


def render_host_secrets(_view, _context, model, _name):
    """Detail formatter: the Secret Store entries bound to ``model``."""
    # pylint: disable=import-outside-toplevel
    from application.models.secret import Secret
    if model.id is None or not can_manage(current_user) \
            or not host_in_scope(current_user, model):
        return ''
    entries = list(Secret.objects(host_id=model.id).order_by('key'))
    if not entries:
        return Markup('<em class="text-muted">none</em>')
    rows = []
    for entry in entries:
        badges = f'<span class="badge badge-secondary">{escape(entry.kind or "password")}</span>'
        if entry.orphaned:
            badges += ' <span class="badge badge-warning">orphaned</span>'
        reference = "{{ secret('%s') }}" % entry.key
        links = (f'<a href="{url_for("secret.edit_view", id=entry.id)}">'
                 f'<i class="fa fa-pencil"></i> Entry</a>')
        if can_reveal(current_user, entry):
            links += (f' <a href="{url_for("secret.reveal_view", id=entry.id)}" '
                      f'class="ml-2"><i class="fa fa-eye"></i> Show value</a>')
        rows.append(
            f'<tr><td><code>{escape(entry.key)}</code></td><td>{badges}</td>'
            f'<td><code>{escape(reference)}</code></td><td>******</td>'
            f'<td style="white-space: nowrap;">{links}</td></tr>')
    return Markup(
        '<table class="table table-sm mb-0"><thead><tr><th>Key</th><th>Kind</th>'
        '<th>Reference in rules</th><th>Value</th><th></th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table>')
