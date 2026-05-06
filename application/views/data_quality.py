"""
Data Quality / Reconciliation Dashboard

Shows what an operator usually has to discover by scrolling and
filtering through Hosts: how many objects each source delivered, how
many are stale or archived, which hostnames look like duplicates,
which configured CMDB fields are most often empty and which configured
accounts never delivered anything. The page is read-only — actions
stay on the relevant list views. CSV export is offered per section so
findings can be handed off to ticketing.
"""
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import re

from flask import Response, request, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application import app
from application.models.account import Account
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
_EMPTY_FIELD_HOST_LIMIT = 50
_MISSING_FIELD_FREQ_LIMIT = 25
_SOURCE_STALE_HOURS = 24
_SOURCE_VERY_STALE_DAYS = 7


def _normalize_hostname(name):
    """Strip known noise from a hostname so probable duplicates collide."""
    if not name:
        return ''
    base = name.lower().strip()
    base = re.split(r'[.\s]', base, maxsplit=1)[0]
    base = re.sub(r'[^a-z0-9]', '', base)
    return base


def _missing_cmdb_fields(host, cmdb_models, all_required):
    """
    Return the list of CMDB field names that the configured schema
    requires for this host's object_type but that are blank or absent.
    Empty list = nothing missing or no schema applies.
    """
    expected = set(cmdb_models.get(host.object_type, {}).keys()) | all_required
    if not expected:
        return []
    got = {f.field_name: (f.field_value or '').strip()
           for f in (host.cmdb_fields or [])
           if getattr(f, 'field_name', None)}
    return [k for k in expected if not got.get(k, '').strip()]


def _annotate_freshness(per_source, now):
    """
    Tag each per-source row with a freshness bucket so the template
    can colour-code in one lookup. Returns the number of sources that
    fall into the never/very_old buckets (the "silent" ones).
    """
    stale_24h = now - timedelta(hours=_SOURCE_STALE_HOURS)
    stale_7d = now - timedelta(days=_SOURCE_VERY_STALE_DAYS)
    silent = 0
    for row in per_source.values():
        ts = row['last_seen']
        if ts is None:
            row['freshness'] = 'never'
        elif ts < stale_7d:
            row['freshness'] = 'very_old'
        elif ts < stale_24h:
            row['freshness'] = 'old'
        else:
            row['freshness'] = 'fresh'
        if row['freshness'] in ('never', 'very_old'):
            silent += 1
    return silent


def _collect_silent_sources(seen_names):
    """
    Enabled, non-CMDB-store accounts that have not delivered any
    live host. Spots forgotten imports and quietly broken auth.
    """
    out = []
    try:
        for acc in Account.objects(enabled=True).only(
                'name', 'type', 'cmdb_object'):
            if acc.cmdb_object or acc.name in seen_names:
                continue
            out.append({
                'id': str(acc.id),
                'name': acc.name,
                'type': acc.type or '(unknown)',
            })
        out.sort(key=lambda r: r['name'])
    except Exception:  # pylint: disable=broad-except
        # Account collection issues should never break the dashboard.
        return []
    return out


def _collect(now):  # pylint: disable=too-many-locals
    """
    One pass over the live host collection plus a tiny pass over the
    archive. Returns every aggregate the dashboard needs so the view
    function can stay declarative.
    """
    live_q = Host.objects(is_object__ne=True, deleted_at__exists=False)
    archive_q = Host.objects(is_object__ne=True, deleted_at__exists=True)

    cmdb_models = app.config.get('CMDB_MODELS', {}) or {}
    all_required = set(cmdb_models.get('all', {}).keys())
    has_cmdb_schema = bool(all_required) or any(
        cmdb_models.get(t) for t in cmdb_models if t != 'all'
    )

    per_source = defaultdict(lambda: {
        'total': 0, 'stale': 0, 'archived': 0, 'last_seen': None,
    })
    per_type = defaultdict(lambda: {
        'total': 0, 'stale': 0, 'with_missing_fields': 0,
    })
    lifecycle_counts = Counter()
    missing_field_freq = Counter()
    normalized = defaultdict(list)
    empty_fields = []
    hosts_with_missing = 0
    total_live = 0
    total_stale = 0

    fields = ('hostname', 'source_account_name', 'is_stale',
              'last_import_seen', 'lifecycle_state',
              'object_type', 'cmdb_fields')
    for host in live_q.only(*fields):
        total_live += 1
        src_row = per_source[host.source_account_name or '(none)']
        src_row['total'] += 1
        type_row = per_type[host.object_type or '(none)']
        type_row['total'] += 1
        if host.is_stale:
            src_row['stale'] += 1
            type_row['stale'] += 1
            total_stale += 1
        if host.last_import_seen and (src_row['last_seen'] is None
                                      or host.last_import_seen > src_row['last_seen']):
            src_row['last_seen'] = host.last_import_seen
        lifecycle_counts[host.lifecycle_state or 'active'] += 1

        key = _normalize_hostname(host.hostname)
        if key:
            normalized[key].append(host.hostname)

        if has_cmdb_schema:
            missing = _missing_cmdb_fields(host, cmdb_models, all_required)
            if missing:
                hosts_with_missing += 1
                type_row['with_missing_fields'] += 1
                missing_field_freq.update(missing)
                if len(empty_fields) < _EMPTY_FIELD_HOST_LIMIT:
                    empty_fields.append({
                        'hostname': host.hostname,
                        'object_type': host.object_type,
                        'missing': missing,
                    })

    total_archived = 0
    for host in archive_q.only('source_account_name'):
        total_archived += 1
        per_source[host.source_account_name or '(none)']['archived'] += 1

    sources_silent_count = _annotate_freshness(per_source, now)

    sources = sorted(({'name': k, **v} for k, v in per_source.items()),
                     key=lambda r: -r['total'])
    types = sorted(({'name': k, **v} for k, v in per_type.items()),
                   key=lambda r: -r['total'])
    duplicate_clusters = sorted(
        [cluster for cluster in normalized.values() if len(cluster) > 1],
        key=lambda lst: -len(lst),
    )[:_DUPLICATE_HOST_LIMIT]
    missing_top = missing_field_freq.most_common(_MISSING_FIELD_FREQ_LIMIT)

    seen_source_names = {n for n in per_source if n != '(none)'}
    silent_sources = _collect_silent_sources(seen_source_names)

    return {
        'sources': sources,
        'types': types,
        'lifecycle_counts': dict(lifecycle_counts),
        'duplicates': duplicate_clusters,
        'empty_fields': empty_fields,
        'missing_top': missing_top,
        'silent_sources': silent_sources,
        'totals': {
            'live': total_live,
            'stale': total_stale,
            'archived': total_archived,
            'with_missing': hosts_with_missing,
            'duplicate_clusters': len(duplicate_clusters),
            'silent_sources': len(silent_sources) + sources_silent_count,
        },
        'has_cmdb_schema': has_cmdb_schema,
    }


def _csv_response(filename, header, rows):
    """Build a streamed CSV response so operators can hand off findings."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition':
                 f'attachment; filename="{filename}"'},
    )


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
    def index(self):
        """Render the dashboard or stream a section as CSV."""
        now = datetime.utcnow()
        data = _collect(now)

        export = request.args.get('export')
        if export:
            return self._export(export, data)

        idx = _host_filter_indices()
        try:
            account_edit_url = url_for('accounts.edit_view')
        except Exception:  # pylint: disable=broad-except
            account_edit_url = None
        try:
            # Archive view has Hostname at flt0 and Account at flt1.
            archive_list_url = url_for('archive.index_view')
        except Exception:  # pylint: disable=broad-except
            archive_list_url = None
        return self.render(
            'admin/data_quality.html',
            now=now,
            host_list_url=url_for('host.index_view'),
            account_edit_url=account_edit_url,
            archive_list_url=archive_list_url,
            lifecycle_filter_idx=idx.get('Lifecycle State'),
            account_filter_idx=idx.get('Account'),
            hostname_filter_idx=idx.get('Hostname'),
            stale_filter_idx=idx.get('Stale'),
            **data,
        )

    @staticmethod
    def _export(section, data):
        """Stream one of the dashboard tables as CSV."""
        exporters = {
            'duplicates': lambda d: _csv_response(
                'duplicates.csv', ['count', 'hostnames'],
                [(len(c), ', '.join(c)) for c in d['duplicates']]),
            'empty_fields': lambda d: _csv_response(
                'empty_fields.csv', ['hostname', 'object_type', 'missing'],
                [(r['hostname'], r['object_type'], ', '.join(r['missing']))
                 for r in d['empty_fields']]),
            'missing_fields': lambda d: _csv_response(
                'missing_fields.csv', ['field', 'hosts_missing'],
                d['missing_top']),
            'silent_sources': lambda d: _csv_response(
                'silent_sources.csv', ['account', 'type'],
                [(r['name'], r['type']) for r in d['silent_sources']]),
            'sources': lambda d: _csv_response(
                'sources.csv',
                ['source', 'total', 'stale', 'archived',
                 'last_seen', 'freshness'],
                [(r['name'], r['total'], r['stale'], r['archived'],
                  r['last_seen'].isoformat() if r['last_seen'] else '',
                  r['freshness']) for r in d['sources']]),
            'types': lambda d: _csv_response(
                'object_types.csv',
                ['object_type', 'total', 'stale', 'with_missing_fields'],
                [(r['name'], r['total'], r['stale'], r['with_missing_fields'])
                 for r in d['types']]),
        }
        handler = exporters.get(section)
        if handler is None:
            return Response('unknown section', status=400)
        return handler(data)
