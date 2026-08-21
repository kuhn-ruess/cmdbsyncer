"""
CMDB template matching

A CMDB template is a Host document with `object_type='template'`. Its
`cmdb_match` pattern ("label:value") decides which hosts carry it.
Matching a single host happens on save (`Host.get_cmdb_template`);
re-matching the whole database is a deliberate, operator-triggered step
and lives here.
"""


def parse_cmdb_match(cmdb_match):
    """
    Split a template's `cmdb_match` pattern into its label key and
    value. Whitespace around the colon is stripped.

    Returns:
        tuple|None: (key, value), or None if the pattern is unusable.
    """
    if not cmdb_match or ':' not in cmdb_match:
        return None
    key, value = cmdb_match.split(':', 1)
    key, value = key.strip(), value.strip()
    if not key:
        return None
    return key, value


def sync_template_assignment(template, remove_stale=False):
    """
    Re-run one template's label match over the whole database and give
    the template to everything matching its current `cmdb_match`.

    A host can also carry the template because somebody assigned it by
    hand, and that is indistinguishable from a leftover of an older
    pattern. Dropping it is therefore never implied: only with
    `remove_stale` do hosts that do not match lose the template again.

    A template without a usable `cmdb_match` is never assigned
    automatically at all, so all of its assignments are manual — it is
    skipped entirely.

    Args:
        template (Host): The template document to re-apply.
        remove_stale (bool): Also take the template off every host that
            does not match the pattern.

    Returns:
        tuple|None: (added, removed) host counts, or None when the
        template has no usable `cmdb_match`.
    """
    parsed = parse_cmdb_match(template.cmdb_match)
    if not parsed:
        return None
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    key, value = parsed
    # Templates never carry templates, and a soft-deleted row is on its
    # way out — neither takes part in the match.
    candidates = Host.objects(object_type__ne='template',
                              deleted_at__exists=False)
    matching = set(candidates.filter(__raw__={f'labels.{key}': value})
                   .only('id').scalar('id'))
    assigned = set(candidates.filter(cmdb_templates=template.id)
                   .only('id').scalar('id'))
    to_add = list(matching - assigned)
    to_remove = list(assigned - matching) if remove_stale else []
    # Template values are merged into the cached export attributes, so a
    # changed assignment has to take the cache with it.
    if to_add:
        Host.objects(id__in=to_add).update(
            add_to_set__cmdb_templates=template.id, set__cache={})
    if to_remove:
        Host.objects(id__in=to_remove).update(
            pull__cmdb_templates=template.id, set__cache={})
    return len(to_add), len(to_remove)
