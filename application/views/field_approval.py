"""
FieldApproval admin view + helpers.

The view shows the queue of label changes that were caught by
`enqueue_critical_label_changes()` in `host.py` and offers Approve /
Reject bulk actions. The badge in master.html is fed by the
`pending_count()` helper at the bottom of this file.
"""
import datetime

from flask import flash, redirect, request, url_for
from flask_admin.actions import action
from flask_admin.contrib.mongoengine import ModelView
from flask_login import current_user
from mongoengine.errors import DoesNotExist

from application import app
from application.models.field_approval import FieldApproval
from application.models.host import Host


class FieldApprovalView(ModelView):  # pylint: disable=too-many-public-methods,too-many-ancestors
    """
    Read-mostly queue. The form is hidden because the only way to
    apply a change is via the Approve / Reject bulk actions — direct
    edits would let an operator rewrite the captured `new_value` and
    bypass review.
    """
    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True

    column_list = (
        'status', 'hostname', 'field_name', 'old_value', 'new_value',
        'requested_by_email', 'requested_at',
    )
    column_default_sort = '-requested_at'
    column_filters = ('status', 'hostname', 'field_name', 'requested_by_email')

    def is_accessible(self):
        return current_user.is_authenticated and (
            current_user.global_admin
            or current_user.has_right('approval')
            or current_user.has_right('host')
        )

    def _can_decide(self):
        return current_user.global_admin or current_user.has_right('approval')

    @action('approve', 'Approve', 'Apply the selected changes to the hosts?')
    def action_approve(self, ids):
        """Apply each pending change to its host and mark the row approved."""
        if not self._can_decide():
            flash('Approval requires the "Approve or reject pending field '
                  'changes" role.', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        applied, skipped = 0, 0
        for approval in FieldApproval.objects(id__in=ids, status='pending'):
            host = Host.objects(id=approval.host_id).first()
            if host is None:
                approval.status = 'rejected'
                approval.decision_reason = 'host no longer exists'
                approval.decided_by_email = current_user.email
                approval.decided_at = datetime.datetime.utcnow()
                approval.save()
                skipped += 1
                continue
            labels = dict(host.labels or {})
            if approval.new_value is None or approval.new_value == '':
                labels.pop(approval.field_name, None)
            else:
                labels[approval.field_name] = approval.new_value
            # pylint: disable=protected-access
            host._label_change_source = 'approval'
            host._label_change_user = current_user.email
            host.update_host(labels)
            host.save()
            approval.status = 'approved'
            approval.decided_by_email = current_user.email
            approval.decided_at = datetime.datetime.utcnow()
            approval.save()
            applied += 1
        flash(f'Approved {applied} change(s)' +
              (f', {skipped} skipped' if skipped else ''),
              'success' if applied else 'warning')
        return redirect(request.referrer or url_for('.index_view'))

    @action('reject', 'Reject',
            'Reject the selected changes? The hosts keep their old values.')
    def action_reject(self, ids):
        """Mark each pending change as rejected without touching the host."""
        if not self._can_decide():
            flash('Approval requires the "Approve or reject pending field '
                  'changes" role.', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        rejected = 0
        for approval in FieldApproval.objects(id__in=ids, status='pending'):
            approval.status = 'rejected'
            approval.decided_by_email = current_user.email
            approval.decided_at = datetime.datetime.utcnow()
            approval.save()
            rejected += 1
        flash(f'Rejected {rejected} change(s)',
              'success' if rejected else 'warning')
        return redirect(request.referrer or url_for('.index_view'))


def enqueue_critical_label_changes(host, new_labels, current_labels):
    """
    Compare incoming `new_labels` against `current_labels` for every
    label listed in `APPROVAL_REQUIRED_LABELS`. For each mismatch:
      * stage a FieldApproval row with the requested change
      * roll the value back inside `new_labels` to its current state

    The caller (HostModelView.on_model_change) then writes the
    sanitised `new_labels` back to the host, so the protected fields
    only ever flip after a second pair of eyes.

    Returns the number of approvals queued.
    """
    if not current_user.is_authenticated:
        return 0
    if current_user.has_right('approval_bypass') or current_user.global_admin:
        return 0
    critical = list(app.config.get('APPROVAL_REQUIRED_LABELS') or [])
    if not critical:
        return 0

    queued = 0
    try:
        host_id_str = str(host.pk) if host.pk else ''
    except DoesNotExist:
        host_id_str = ''

    for key in critical:
        old_v = current_labels.get(key)
        new_v = new_labels.get(key)
        if (old_v or '') == (new_v or ''):
            continue
        FieldApproval(
            host_id=host_id_str,
            hostname=host.hostname,
            field_name=key,
            old_value=str(old_v) if old_v is not None else None,
            new_value=str(new_v) if new_v is not None else None,
            requested_by_email=getattr(current_user, 'email', '') or '',
        ).save()
        # Roll the change back so the caller's persistence path stays
        # untouched until an approver flips the value for real.
        if old_v is None:
            new_labels.pop(key, None)
        else:
            new_labels[key] = old_v
        queued += 1
    return queued


def pending_count():
    """Cheap count for the navbar badge — silent on errors."""
    try:
        return FieldApproval.objects(status='pending').count()
    except Exception:  # pylint: disable=broad-exception-caught
        return 0
