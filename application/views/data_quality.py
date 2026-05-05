"""
Data Quality / Reconciliation Dashboard

Shows what an operator usually has to discover by scrolling and
filtering through Hosts: how many objects each source delivered, how
many are stale or archived, which hostnames look like duplicates and
which hosts have configured CMDB fields still empty. The page is a
read-only snapshot — actions stay on the relevant list views.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import re

from flask import url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application import app
from application.models.host import Host


def _host_filter_indices():
    """
    Look up the Flask-Admin filter position for each caption used by
    the dashboard's deep-links. Computed from the HostModelView class
    so the indices stay correct if column_filters is reordered.
    """
    # pylint: disable=import-outside-toplevel
    from application.views.host import HostModelView
    by_name = {}
    for idx, flt in enumerate(HostModelView.column_filters):
        # BaseMongoEngineFilter.name carries the filter caption.
        caption = getattr(flt, 'name', None)
        if caption:
            by_name[caption] = idx
    return by_name


_DUPLICATE_HOST_LIMIT = 50
_DRIFT_LABEL_LIMIT = 20


def _normalize_hostname(name):
    """Strip known noise from a hostname so probable duplicates collide."""
    if not name:
        return ''
    base = name.lower().strip()
    base = re.split(r'[.\s]', base, maxsplit=1)[0]
    base = re.sub(r'[^a-z0-9]', '', base)
    return base


class DataQualityView(BaseView):
    """
    Read-only Reconciliation / Data Quality landing page. Lives next
    to the Hosts list rather than under any plugin so any account can
    see its own footprint.
    """

    def is_accessible(self):
        # CMDB-only dashboard: hide menu link and block direct access
        # when the install is running in plain syncer mode.
        if not app.config.get('CMDB_MODE'):
            return False
        return current_user.is_authenticated and current_user.has_right('host')

    @expose('/')
    def index(self):  # pylint: disable=too-many-locals,too-many-branches
        """Render the dashboard with per-source counts, drift and dupes."""
        live_q = Host.objects(is_object__ne=True, deleted_at__exists=False)
        archive_q = Host.objects(is_object__ne=True, deleted_at__exists=True)

        # Per-source headcount, stale and last-import-seen aggregates.
        per_source = defaultdict(lambda: {
            'total': 0, 'stale': 0,
            'archived': 0, 'last_seen': None,
        })
        for host in live_q.only('source_account_name', 'is_stale',
                                 'last_import_seen', 'lifecycle_state'):
            row = per_source[host.source_account_name or '(none)']
            row['total'] += 1
            if host.is_stale:
                row['stale'] += 1
            if host.last_import_seen and (row['last_seen'] is None
                                          or host.last_import_seen > row['last_seen']):
                row['last_seen'] = host.last_import_seen
        for host in archive_q.only('source_account_name'):
            per_source[host.source_account_name or '(none)']['archived'] += 1

        sources = sorted(
            ({'name': k, **v} for k, v in per_source.items()),
            key=lambda r: -r['total'],
        )

        # Lifecycle distribution across the live fleet.
        lifecycle_counts = Counter()
        for host in live_q.only('lifecycle_state'):
            lifecycle_counts[host.lifecycle_state or 'active'] += 1

        # Hostname-collision candidates: rows whose normalized form
        # repeats. Cheap to compute on the order of fleet sizes we
        # expect (tens of thousands), and sized-bound to keep render
        # times predictable.
        normalized = defaultdict(list)
        for host in live_q.only('hostname'):
            key = _normalize_hostname(host.hostname)
            if key:
                normalized[key].append(host.hostname)
        duplicate_clusters = sorted(
            ([cluster for cluster in normalized.values() if len(cluster) > 1]),
            key=lambda lst: -len(lst),
        )[:_DUPLICATE_HOST_LIMIT]

        # Label-value drift: same label key, different values from
        # different sources for the same host. One row per (key, host).
        drift = []
        for host in live_q.only('hostname', 'labels'):
            for k, v in (host.labels or {}).items():
                if isinstance(v, str) and '\n' in v:
                    drift.append({'host': host.hostname, 'key': k,
                                   'value': v[:80] + '…'})
        drift = drift[:_DRIFT_LABEL_LIMIT]

        # Configured CMDB fields that exist on the host but are empty.
        cmdb_models = app.config.get('CMDB_MODELS', {})
        all_required = set(cmdb_models.get('all', {}).keys())
        empty_fields = []
        if all_required or any(cmdb_models.get(t) for t in cmdb_models):
            for host in live_q.only('hostname', 'object_type', 'cmdb_fields'):
                expected = set(cmdb_models.get(host.object_type, {}).keys()) | all_required
                if not expected:
                    continue
                got = {f.field_name: (f.field_value or '').strip()
                       for f in (host.cmdb_fields or [])
                       if getattr(f, 'field_name', None)}
                missing = [k for k in expected
                           if not got.get(k, '').strip()]
                if missing:
                    empty_fields.append({
                        'hostname': host.hostname,
                        'object_type': host.object_type,
                        'missing': missing,
                    })
        empty_fields = empty_fields[:_DUPLICATE_HOST_LIMIT]

        now = datetime.utcnow()
        # Flask-Admin filter URL = ?flt0_<index>=<value>. Pre-compute
        # the relevant indices so the template can build deep-links
        # without knowing the filter order.
        idx = _host_filter_indices()
        host_list_url = url_for('host.index_view')
        return self.render(
            'admin/data_quality.html',
            sources=sources,
            lifecycle_counts=dict(lifecycle_counts),
            duplicates=duplicate_clusters,
            drift=drift,
            empty_fields=empty_fields,
            now=now,
            stale_recent_threshold=now - timedelta(days=7),
            host_list_url=host_list_url,
            lifecycle_filter_idx=idx.get('Lifecycle State'),
            account_filter_idx=idx.get('Account'),
            hostname_filter_idx=idx.get('Hostname'),
            stale_filter_idx=idx.get('Stale'),
        )
