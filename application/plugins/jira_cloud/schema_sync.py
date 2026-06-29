"""
Persist the Jira Cloud Assets schema (object types + attributes) into
Mongo so the GUI can autocomplete and the export plugin can resolve
attribute names to ids without one extra round-trip per host.
"""
from datetime import datetime

from syncerapi.v1 import cc

from application.plugins.jira_cloud.jira_cloud import JiraCloud
from application.plugins.jira_cloud.models import (
    JiraSchemaAttribute,
    JiraSchemaCache,
    JiraSchemaObjectType,
)


class JiraSchemaSync(JiraCloud):
    """Walk every schema/object type/attribute and cache it."""

    name = "Jira Cloud: Sync Schema"
    source = "jira_cloud_schema"

    def sync(self):
        """Fetch and persist."""
        schemas_resp = self.inner_request(
            method="GET",
            url=f"{self.base_url}/v1/objectschema/list",
            headers=self.headers, auth=self.auth,
        )
        schemas = schemas_resp.json().get('values', [])
        print(f"{cc.OKGREEN} -- {cc.ENDC}Found {len(schemas)} schema(s)")

        object_types = []
        for schema in schemas:
            schema_id = int(schema['id'])
            schema_name = schema.get('name', '')
            types_resp = self.inner_request(
                method="GET",
                url=f"{self.base_url}/v1/objectschema/{schema_id}/objecttypes/flat",
                headers=self.headers, auth=self.auth,
            )
            for otype in types_resp.json():
                type_id = int(otype['id'])
                attrs_resp = self.inner_request(
                    method="GET",
                    url=f"{self.base_url}/v1/objecttype/{type_id}/attributes",
                    headers=self.headers, auth=self.auth,
                )
                attributes = []
                for attr in attrs_resp.json():
                    attributes.append(JiraSchemaAttribute(
                        attribute_id=int(attr['id']),
                        name=attr.get('name', ''),
                        type_name=(attr.get('defaultType') or {}).get('name', ''),
                        editable=attr.get('editable', True),
                    ))
                object_types.append(JiraSchemaObjectType(
                    object_type_id=type_id,
                    name=otype.get('name', ''),
                    schema_id=schema_id,
                    schema_name=schema_name,
                    attributes=attributes,
                ))
                print(f"{cc.OKGREEN}  + {cc.ENDC}{schema_name} / "
                      f"{otype.get('name')} ({len(attributes)} attrs)")
                if self.debug:
                    for attr in attributes:
                        editable = "editable" if attr.editable else "read-only"
                        print(f"{cc.OKBLUE}      · {cc.ENDC}"
                              f"{attr.name} [#{attr.attribute_id}, "
                              f"{attr.type_name or '?'}, {editable}]")

        cache = JiraSchemaCache.objects(account=self.account_name).first()
        if not cache:
            cache = JiraSchemaCache(account=self.account_name)
        cache.updated = datetime.now()
        cache.object_types = object_types
        cache.save()
        print(f"{cc.OKGREEN} -- {cc.ENDC}Cached "
              f"{len(object_types)} object type(s) for '{self.account_name}'")


def sync_jira_schema(account, debug=False):
    """Entry point: walk the Cloud Assets schema and persist it."""
    syncer = JiraSchemaSync(account)
    syncer.debug = debug
    syncer.sync()
