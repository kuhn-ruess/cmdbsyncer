"""
Export host attributes to Jira Cloud Assets objects.

Every enabled JiraExportRule is loaded into a single rule engine, every
referenced object type's existing objects are bulk-fetched once via AQL,
and hosts are iterated exactly once.  Per host the engine merges all
matching rules' outcomes; we then walk the resulting per-type field
bundles, diff against the cached existing values and only PUT/POST when
something actually changed.

The lookup attribute is always "Name" — Jira Assets' default label
attribute on every object type.
"""
# pylint: disable=too-many-locals,too-many-branches,too-many-nested-blocks
# pylint: disable=too-many-statements
import json
from collections import defaultdict

from rich.progress import Progress, SpinnerColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.text import Text

from syncerapi.v1 import (
    Host,
    cc,
)

from application import logger
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite
from application.plugins.jira_cloud.jira_cloud import JiraCloud
from application.plugins.jira_cloud.models import (
    JiraCloudFilterRule,
    JiraCloudRewriteAttributeRule,
    JiraExportRule,
    JiraSchemaCache,
)
from application.plugins.jira_cloud.rules import JiraExportAttributeRule


LOOKUP_ATTRIBUTE_NAME = "Name"


class JiraCloudExport(JiraCloud):
    """Export driver."""

    name = "Jira Cloud: Export Objects"
    source = "jira_cloud_export"

    def __init__(self, account):
        super().__init__(account)
        self._schema_cache = None
        # type_id -> (type_entry, name_to_id, lookup_attr_id, existing_map)
        self._type_state = {}

        # When the account's `update_only` setting is on, only existing
        # objects are updated — hosts without a matching Jira object are
        # skipped instead of created.
        self.update_only = bool(self.config.get('update_only'))

        # Honour rewrite + filter rules the same way Checkmk does —
        # the Plugin base class calls them inside `get_attributes`, so
        # we don't have to invoke them anywhere in here.
        self.rewrite = Rewrite()
        self.rewrite.cache_name = "jira_cloud_rewrite"
        self.rewrite.rules = (
            JiraCloudRewriteAttributeRule
            .objects(enabled=True).order_by('sort_field'))

        self.filter = Filter()
        self.filter.cache_name = "jira_cloud_filter"
        self.filter.rules = JiraCloudFilterRule.objects(enabled=True).order_by('sort_field')

    def _load_schema(self):
        """Cache lookup for the persisted schema; fail loud if missing."""
        if self._schema_cache is None:
            doc = JiraSchemaCache.objects(account=self.account_name).first()
            if not doc:
                raise ValueError(
                    f"No Jira schema cache for account '{self.account_name}'. "
                    f"Run `cmdbsyncer jira sync_schema {self.account_name}` first."
                )
            self._schema_cache = doc
        return self._schema_cache

    def _get_type(self, object_type_id):
        """Return the cached object type or None."""
        for entry in self._load_schema().object_types:
            if entry.object_type_id == object_type_id:
                return entry
        return None

    def _build_payload(self, object_type_id, attr_values):
        """Translate {attribute_id: value} into the Atlassian write format."""
        return {
            "objectTypeId": str(object_type_id),
            "attributes": [
                {
                    "objectTypeAttributeId": str(attr_id),
                    "objectAttributeValues": [{"value": str(value)}],
                }
                for attr_id, value in attr_values.items()
            ],
        }

    def _existing_objects(self, type_name, lookup_attr_id):
        """
        Map ``{lookup_value: (object_id, {attr_id: current_value})}`` for
        every existing object of the target type.

        The AQL response carries attributes only by id (no name), so the
        caller resolves the lookup attribute's id from the schema cache
        and passes it in.
        """
        existing = {}
        ql = f'objectType = "{type_name}"'
        for obj in self._iter_aql_objects(ql):
            current_attrs = {}
            lookup_value = None
            for attr in obj.get('attributes', []):
                attr_id = int(attr.get('objectTypeAttributeId', 0))
                values = attr.get('objectAttributeValues') or []
                if not values:
                    continue
                value = values[0].get('value')
                current_attrs[attr_id] = value
                if attr_id == lookup_attr_id:
                    lookup_value = value
            if lookup_value is not None:
                existing[lookup_value] = (obj['id'], current_attrs)
        return existing

    def _prepare_type(self, object_type_id):
        """
        Load schema + existing objects for one object type and remember
        the state.  Returns the state tuple or ``None`` when the type or
        its ``Name`` attribute isn't cached.
        """
        if object_type_id in self._type_state:
            return self._type_state[object_type_id]

        type_entry = self._get_type(object_type_id)
        if not type_entry:
            print(f"{cc.WARNING} -- {cc.ENDC}object_type_id={object_type_id} "
                  f"not in schema cache, skipping its outcomes")
            self._type_state[object_type_id] = None
            return None

        name_to_id = {a.name: a.attribute_id for a in type_entry.attributes}
        if LOOKUP_ATTRIBUTE_NAME not in name_to_id:
            print(f"{cc.WARNING} -- {cc.ENDC}'{type_entry.name}' has no "
                  f"'{LOOKUP_ATTRIBUTE_NAME}' attribute, skipping its outcomes")
            self._type_state[object_type_id] = None
            return None
        lookup_attr_id = name_to_id[LOOKUP_ATTRIBUTE_NAME]

        print(f"{cc.OKGREEN} -- {cc.ENDC}Preparing "
              f"{type_entry.schema_name} / {type_entry.name} "
              f"(type id {object_type_id})")
        existing = self._existing_objects(type_entry.name, lookup_attr_id)
        print(f"{cc.OKGREEN}  + {cc.ENDC}{len(existing)} existing object(s) loaded")

        state = (type_entry, name_to_id, lookup_attr_id, existing)
        self._type_state[object_type_id] = state
        return state

    @staticmethod
    def _write_error(resp):
        """
        Return a short error string if a Jira write was unsuccessful, else
        ``None``.

        ``inner_request`` returns the raw response without checking the
        status, so a missing write permission (HTTP 401/403) or a rejected
        payload (HTTP 400) would otherwise be silently counted as a
        successful update. The caller turns a non-None result into a logged
        failure for that single object and carries on with the next one —
        one rejected write must not abort the whole export run.
        """
        status = getattr(resp, 'status_code', None)
        if status is None or 200 <= status < 300:
            return None
        try:
            body = resp.text
        except Exception:  # pylint: disable=broad-exception-caught
            body = ''
        return f"HTTP {status} {body[:300]}"

    def _put_object(self, object_id, object_type_id, attr_values):
        """Update an existing Jira Assets object; return any write error."""
        payload = self._build_payload(object_type_id, attr_values)
        resp = self.inner_request(
            method="PUT",
            url=f"{self.base_url}/v1/object/{object_id}",
            headers=self.headers, auth=self.auth,
            data=json.dumps(payload),
        )
        return self._write_error(resp)

    def _post_object(self, object_type_id, attr_values):
        """Create a new Jira Assets object; return any write error."""
        payload = self._build_payload(object_type_id, attr_values)
        resp = self.inner_request(
            method="POST",
            url=f"{self.base_url}/v1/object/create",
            headers=self.headers, auth=self.auth,
            data=json.dumps(payload),
        )
        return self._write_error(resp)

    def export_objects(self):
        """Single-pass export: prepare types, iterate hosts once."""
        if self.dry_run:
            print(f"{cc.WARNING} == {cc.ENDC}Dry-run: no objects will be "
                  f"created or updated in Jira")
        if self.update_only:
            print(f"{cc.WARNING} == {cc.ENDC}Update-only: existing objects are "
                  f"updated, missing ones are skipped (never created)")
        rules = list(JiraExportRule.objects(enabled=True).order_by('sort_field'))
        if not rules:
            print(f"{cc.WARNING} -- {cc.ENDC}No enabled JiraExportRule rows, "
                  f"nothing to do")
            return

        all_type_ids = sorted({
            type_id
            for r in rules
            for o in (r.outcomes or [])
            if (type_id := o.object_type_id) is not None
        })
        if not all_type_ids:
            print(f"{cc.WARNING} -- {cc.ENDC}No outcomes on any enabled rule, "
                  f"nothing to do")
            return

        for type_id in all_type_ids:
            self._prepare_type(type_id)

        rule_engine = JiraExportAttributeRule()
        rule_engine.rules = rules
        rule_engine.debug = self.debug
        rule_engine.name = self.name
        cache_key = "jira_cloud_export"

        # Honour the per-account object_filter the user picks on the
        # Account → Plugin Settings line for this plugin, same as every
        # other outbound syncer.
        object_filter = self.config.get('settings', {}).get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        counts = defaultdict(lambda: {"updated": 0, "created": 0,
                                      "unchanged": 0, "skipped": 0,
                                      "failed": 0})

        with Progress(SpinnerColumn(), MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            # The status lines carry raw cc.* ANSI codes; rich's console
            # would escape them and print a literal "[92m". Parse the ANSI
            # so the colors render and the [type ...] brackets stay literal.
            def console(message):
                progress.console.print(Text.from_ansi(message))
            task = progress.add_task("Jira Cloud export", total=total)
            for db_host in db_objects:
                progress.advance(task)
                try:
                    self._process_host(db_host, rule_engine, cache_key,
                                       counts, console)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    if self.debug:
                        raise
                    logger.exception("Export failed for %s", db_host.hostname)
                    self.log_details.append(
                        (f'export_error {db_host.hostname}', str(error)))

        for type_id in all_type_ids:
            c = counts[type_id]
            summary = (f"updated={c['updated']} created={c['created']} "
                       f"unchanged={c['unchanged']} skipped={c['skipped']} "
                       f"failed={c['failed']}")
            type_entry = self._get_type(type_id)
            label = type_entry.name if type_entry else f"type {type_id}"
            print(f"{cc.OKGREEN} == {cc.ENDC}{label} [type {type_id}]: {summary}")
            self.log_details.append((f'type {type_id}', summary))

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _process_host(self, db_host, rule_engine, cache_key, counts, console):
        """Apply every matching rule to one host."""
        attrs = self.get_attributes(db_host, cache_key)
        if not attrs:
            return
        outcomes = rule_engine.get_outcomes(db_host, attrs['all'])
        fields_by_type = outcomes.get('fields_by_type') or {}
        if not fields_by_type:
            return
        lookup_value = db_host.hostname

        for type_id_str, fields in fields_by_type.items():
            type_id = int(type_id_str)
            state = self._type_state.get(type_id)
            if not state:
                counts[type_id]["skipped"] += 1
                continue
            _entry, name_to_id, lookup_attr_id, existing = state

            target_attrs = {}
            unknown = []
            for name, value in fields.items():
                if name not in name_to_id:
                    unknown.append(name)
                    continue
                target_attrs[name_to_id[name]] = value
            if unknown:
                console(f"{cc.WARNING}   ? {cc.ENDC}"
                        f"{db_host.hostname} [type {type_id}]: "
                        f"unknown Jira attribute(s) {unknown}")
            if not target_attrs:
                counts[type_id]["skipped"] += 1
                continue

            if lookup_value in existing:
                obj_id, current = existing[lookup_value]
                changed = {a: v for a, v in target_attrs.items()
                           if str(current.get(a, '')) != str(v)}
                if not changed:
                    counts[type_id]["unchanged"] += 1
                    continue
                if self.debug:
                    id_to_name = {i: n for n, i in name_to_id.items()}
                    for attr_id, new_value in changed.items():
                        old_value = current.get(attr_id, '<unset>')
                        console(f"{cc.OKBLUE}     · {cc.ENDC}"
                                f"{db_host.hostname} [type {type_id}] "
                                f"{id_to_name.get(attr_id, attr_id)}: "
                                f"{old_value!r} -> {new_value!r}")
                error = self._put_object(obj_id, type_id, changed)
                if error:
                    console(f"{cc.FAIL}   ✗ {cc.ENDC}"
                            f"{db_host.hostname} [type {type_id}] update "
                            f"rejected by Jira: {error}")
                    # 'error' in the key flags the whole run as errored in
                    # the web log so the rejection is visible there and
                    # error-only notifications fire.
                    self.log_details.append(
                        (f'export_error {db_host.hostname} [type {type_id}]',
                         f'update rejected: {error}'))
                    counts[type_id]["failed"] += 1
                    continue
                verb = "would update" if self.dry_run else "updated"
                console(f"{cc.OKGREEN}   ↻ {cc.ENDC}"
                        f"{db_host.hostname} [type {type_id}] {verb} "
                        f"({len(changed)} field(s))")
                counts[type_id]["updated"] += 1
            elif self.update_only:
                console(f"{cc.WARNING}   ⊘ {cc.ENDC}"
                        f"{db_host.hostname} [type {type_id}] "
                        f"(no existing object, skipped — update-only)")
                counts[type_id]["skipped"] += 1
            else:
                if lookup_attr_id not in target_attrs:
                    target_attrs[lookup_attr_id] = lookup_value
                error = self._post_object(type_id, target_attrs)
                if error:
                    console(f"{cc.FAIL}   ✗ {cc.ENDC}"
                            f"{db_host.hostname} [type {type_id}] create "
                            f"rejected by Jira: {error}")
                    self.log_details.append(
                        (f'export_error {db_host.hostname} [type {type_id}]',
                         f'create rejected: {error}'))
                    counts[type_id]["failed"] += 1
                    continue
                verb = "would create" if self.dry_run else "created"
                console(f"{cc.OKBLUE}   + {cc.ENDC}"
                        f"{db_host.hostname} [type {type_id}] ({verb})")
                counts[type_id]["created"] += 1


def export_jira_cloud(account, debug=False, dry_run=False):
    """Entry point for CLI / cronjob."""
    syncer = JiraCloudExport(account)
    syncer.debug = debug
    syncer.dry_run = dry_run
    syncer.export_objects()
