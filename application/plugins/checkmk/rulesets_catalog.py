"""
Checkmk Ruleset Catalog

Keeps a version-tagged list of every Checkmk ruleset (the "internal rules")
so the Setup-Rule edit form can offer autocomplete for the ``ruleset`` field
and pre-fill a matching ``value_template`` example.

Nothing about the catalog is hardcoded: the ruleset names come from live
Checkmk installations via ``checkmk export_rulesets`` (one JSON file per
minor version under ``data/``), and the example value templates live in a
separate, hand-maintained ``data/ruleset_examples.json`` for easy updates.
"""
import json
import os
import re

from application.plugins.checkmk.cmk2 import CMK2, CmkException

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
EXAMPLES_FILE = os.path.join(DATA_DIR, 'ruleset_examples.json')
# rulesets_2.4.json, rulesets_2.5.json, … — the minor version is the filename.
CATALOG_RE = re.compile(r'^rulesets_(\d+\.\d+)\.json$')


class RulesetCatalog(CMK2):
    """Fetch the full ruleset list from a Checkmk installation and dump it
    to a per-version JSON file the web UI can serve."""

    def export_to_file(self):
        """
        Ask Checkmk for every ruleset and write it to
        ``data/rulesets_<major.minor>.json``. Returns the written path.

        ``used`` is a *filter*, not a flag: ``used=true`` returns only
        rulesets that already have rules, ``used=false`` only the ones that
        don't. The complete registry is the union of both — querying only one
        silently drops the other half (e.g. the popular filesystem/ping
        rulesets, which are usually "used").
        """
        rulesets = {}
        for used in ('true', 'false'):
            data, _ = self.request(
                f'domain-types/ruleset/collections/all?used={used}',
                method='GET')
            for entry in (data.get('value') if isinstance(data, dict) else []) or []:
                ext = entry.get('extensions', {})
                name = ext.get('name') or entry.get('id')
                if not name:
                    continue
                rulesets[name] = {
                    'title': ext.get('title') or name,
                    'help': ext.get('help') or '',
                    'item_type': ext.get('item_type'),
                    'match_type': ext.get('match_type'),
                }
        if not rulesets:
            raise CmkException(
                "Checkmk returned no rulesets — check the account address "
                "and credentials.")

        minor = _minor_version(self.checkmk_version)
        out_path = os.path.join(DATA_DIR, f'rulesets_{minor}.json')
        payload = {
            'checkmk_version': self.checkmk_version,
            'rulesets': dict(sorted(rulesets.items())),
        }
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.write('\n')
        return out_path, len(rulesets)


def _minor_version(version):
    """'2.4.0p19.cee' -> '2.4'. Falls back to the raw string if unparseable."""
    parts = str(version or '').split('.')
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f'{parts[0]}.{parts[1]}'
    return str(version or 'unknown')


def _load_json(path):
    """Read a JSON file, returning {} on any problem (missing file, bad JSON)
    so a broken data file never takes down the edit form."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _example_for(raw, versions):
    """
    Resolve the example for a ruleset into (value_template, differs_by_version).

    ``raw`` is either a plain string (same example for every version) or a
    dict keyed by minor version ({"2.4": "...", "2.5": "..."}). For a dict we
    pick the newest version's template and flag whether the templates differ,
    so the UI can point that out.
    """
    if isinstance(raw, str):
        return raw, False
    if isinstance(raw, dict) and raw:
        # Prefer an example for a version the ruleset actually exists in.
        keys = [v for v in versions if v in raw] or list(raw.keys())
        newest = sorted(keys)[-1]
        differs = len(set(raw.values())) > 1
        return raw[newest], differs
    return '', False


def item_types_from_files(version=None):
    """
    ``{ruleset name: item_type}`` read from the shipped catalog files.

    Lets code that must not contact Checkmk still tell a host ruleset
    (``item_type`` None) from a service one. The file matching
    ``version``'s minor release wins; without a match every file is
    merged, oldest first, so the newest definition of a ruleset is the
    one that survives.
    """
    if not os.path.isdir(DATA_DIR):
        return {}
    per_version = {}
    for fname in os.listdir(DATA_DIR):
        match = CATALOG_RE.match(fname)
        if match:
            per_version[match.group(1)] = _load_json(
                os.path.join(DATA_DIR, fname)).get('rulesets', {})
    if not per_version:
        return {}
    wanted = _minor_version(version) if version else None
    if wanted in per_version:
        chosen = [wanted]
    else:
        chosen = sorted(per_version)
    item_types = {}
    for minor in chosen:
        for name, meta in per_version[minor].items():
            item_types[name] = meta.get('item_type')
    return item_types


def load_catalog():
    """
    Merge every ``data/rulesets_<ver>.json`` with the curated examples into a
    single version-tagged list for the browser.

    Returns ``{'versions': [...], 'rulesets': [ {name, title, versions,
    example, example_differs}, … ]}``. Read fresh on every call — the files
    only change when a maintainer re-runs the scraper or edits the examples,
    and the endpoint is hit once per edit-form load, so caching buys little
    and would only hide updates.
    """
    per_version = {}
    if os.path.isdir(DATA_DIR):
        for fname in os.listdir(DATA_DIR):
            match = CATALOG_RE.match(fname)
            if match:
                data = _load_json(os.path.join(DATA_DIR, fname))
                per_version[match.group(1)] = data.get('rulesets', {})

    all_versions = sorted(per_version.keys())
    examples = _load_json(EXAMPLES_FILE).get('examples', {})

    merged = {}
    for version, rulesets in per_version.items():
        for name, meta in rulesets.items():
            entry = merged.setdefault(name, {
                'name': name,
                'title': meta.get('title') or name,
                'versions': [],
            })
            entry['versions'].append(version)
            # A newer file's title wins so the shown label tracks the latest.
            if meta.get('title'):
                entry['title'] = meta['title']

    result = []
    for name in sorted(merged):
        entry = merged[name]
        entry['versions'] = sorted(entry['versions'])
        example, differs = _example_for(examples.get(name), entry['versions'])
        entry['example'] = example
        entry['example_differs'] = differs
        result.append(entry)

    return {'versions': all_versions, 'rulesets': result}
