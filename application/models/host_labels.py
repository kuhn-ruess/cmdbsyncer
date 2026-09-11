"""
Host Labels

The label side of the Host model: writing them, diffing them and the
history plus audit trail a change leaves behind. It lives next to
``host.py`` as a mixin rather than inside it — that module carries the
document itself and is at its size budget.
"""
import datetime

from application import app, logger
from application.helpers.mongo_keys import validate_mongo_keys
from application.helpers.label_history import label_history_enabled


class DeprecatedError(Exception):
    """
    Raise for Deprecated functions
    """


class HostLabelsMixin():
    """
    Label handling of :class:`application.models.host.Host`.

    Mixed into the document, so every method here works on a real Host
    and may use its fields (``labels``, ``cache``) and its other
    methods (``add_log``, ``set_import_sync``, …).
    """

    def replace_label(self, key, value):
        """
        Replace or Create a single Label

        Args:
            key (string): Label Name
            value (string): Label Value
        """
        key = self._fix_key(key)
        if current_value := self.labels.get(key):
            if current_value == value:
                return
        self.labels[key] = value
        self.cache = {}

    def update_host(self, labels):
        """
        Overwrite all Labels on Hosts,
        but checks first if needed and also sets
        set_import_sync and import_seen as needed

        The incoming dict is copied before it is flattened: the caller
        usually keeps using it and must not find its nested keys removed.
        """
        labels = dict(labels or {})
        if app.config['LABELS_ITERATE_FIRST_LEVEL']:
            for key, value in list(labels.items()):
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        labels[f'{key}_{sub_key}'] = sub_value
                    del labels[key]
        label_dict = dict(map(lambda kv: (self._fix_key(kv[0]), kv[1]), labels.items()))
        # Validate after _fix_key so a configured REPLACER still gets the
        # chance to neutralize a `$`-prefixed key before it is rejected.
        # Dots are allowed and pass through untouched.
        validate_mongo_keys(label_dict, "label")
        if self.get_labels() != label_dict:
            self.set_import_sync()
            self._set_labels(label_dict)
        self.set_import_seen()

    def _fix_key(self, key):
        key = str(key)
        if app.config['LOWERCASE_ATTRIBUTE_KEYS']:
            key = key.lower()
        if app.config['REPLACE_ATTRIBUTE_KEYS']:
            for needle, replacer in app.config['REPLACERS']:
                key = key.replace(needle, replacer)
        return key.replace(" ", "_").strip()

    def set_labels(self, _label_dictl):
        """
        Deprecated, migrate to update_host
        """
        raise DeprecatedError("Deprecated function set_labels(), migrate to update_host")

    def _set_labels(self, label_dict):
        """
        Overwrite all Labels on host

        Args:
            label_dict (dict): Key:Value pairs of labels
        """
        updates = []
        for key, value in label_dict.items():
            if self.labels.get(key) != value:
                updates.append(f"{key} to {value}")

        self.add_log(f"Label Change: {','.join(updates)}")
        self._record_label_changes(label_dict)
        self.labels = label_dict
        self.cache = {}

    def _diff_labels(self, new_labels):
        """Return (entries, added, updated, removed) for a label mutation."""
        existing = dict(self.labels or {})
        target = dict(new_labels or {})
        # pylint: disable=import-outside-toplevel
        from application.models.host_label_event import HostLabelChange
        source = getattr(self, '_label_change_source', None) or 'import'
        entries = []
        added, updated, removed = {}, {}, {}

        def _str(val):
            return None if val is None else str(val)

        for key, new_value in target.items():
            if key not in existing:
                entries.append(HostLabelChange(
                    key=key, old_value=None, new_value=_str(new_value),
                    change='add',
                ))
                added[key] = new_value
            elif existing[key] != new_value:
                entries.append(HostLabelChange(
                    key=key, old_value=_str(existing[key]),
                    new_value=_str(new_value), change='update',
                ))
                updated[key] = {'from': existing[key], 'to': new_value}
        for key, old_value in existing.items():
            if key not in target:
                entries.append(HostLabelChange(
                    key=key, old_value=_str(old_value),
                    new_value=None, change='remove',
                ))
                removed[key] = old_value
        return entries, added, updated, removed, source

    def _emit_label_audit(self, added, updated, removed, source):
        """Fan a host.label.changed event into the Enterprise audit log."""
        # pylint: disable=import-outside-toplevel
        from application.helpers.audit import audit
        changes = {}
        if added:
            changes['added'] = {k: str(v) for k, v in added.items()}
        if updated:
            changes['updated'] = {
                k: {
                    'from': (str(v['from']) if v['from'] is not None else None),
                    'to':   (str(v['to'])   if v['to']   is not None else None),
                }
                for k, v in updated.items()
            }
        if removed:
            changes['removed'] = {
                k: (str(v) if v is not None else None)
                for k, v in removed.items()
            }
        audit(
            'host.label.changed',
            target_type='Host',
            target_id=str(self.pk),
            target_name=self.hostname,
            metadata={'source': source},
            changes=changes,
        )

    def _record_label_changes(self, new_labels):
        """
        Write one `HostLabelEvent` for the difference between the
        currently-saved `self.labels` and the incoming `new_labels`, and
        emit a single `host.label.changed` event into the Enterprise
        audit log.

        The history document is only written when LABEL_HISTORY_ENABLED
        is set. The audit event follows its own switch: a label change
        made by a person is exactly what an audit log is for, while an
        import rewriting labels on every run is a firehose that buries
        it — so `source='import'` is skipped unless
        AUDIT_IMPORT_LABEL_CHANGES says otherwise.

        Best-effort: errors must never break the enclosing save — an
        operator losing a single change event is far cheaper than an
        import run falling over.
        """
        if not self.pk:
            return
        try:
            # Imported here: the models module imports Host to resolve
            # its CASCADE reference, so a module-level import would be
            # circular.
            # pylint: disable=import-outside-toplevel
            from application.models.host_label_event import HostLabelEvent
            entries, added, updated, removed, source = \
                self._diff_labels(new_labels)
            if not entries:
                return
            if label_history_enabled():
                HostLabelEvent(
                    host=self, changed_at=datetime.datetime.utcnow(),
                    source=source,
                    user_email=getattr(self, '_label_change_user', None),
                    changes=entries,
                ).save()
            try:
                if source != 'import' \
                        or app.config.get('AUDIT_IMPORT_LABEL_CHANGES', False):
                    self._emit_label_audit(added, updated, removed, source)
            except Exception as exp:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "audit(host.label.changed) dispatch failed for %s: %s",
                    getattr(self, 'hostname', '?'), exp,
                )
        except Exception as exp:  # pylint: disable=broad-exception-caught
            logger.warning("Could not record label history for %s: %s",
                           getattr(self, 'hostname', '?'), exp)

    def get_labels(self):
        """
        Return Hosts Labels dict.
        """
        return self.labels
