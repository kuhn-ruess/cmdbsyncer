"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
import json
from json.decoder import JSONDecodeError
import importlib
from datetime import datetime

from mongoengine.errors import NotUniqueError, ValidationError
from application import app
from .rule_definitions import rules as enabled_rules



def get_ruletype_by_filename(filename):
    """
    Try to guess the rule_type using the filename
    """
    model_name = filename.split('/')[-1].split('_')[0]
    for rule_type, model_data in enabled_rules.items():
        if model_data[1] == model_name:
            return rule_type
    return False


def export_rules_from_model(rule_type):
    """
    Export Given Rulesets
    """
    model = importlib.import_module(enabled_rules[rule_type][0])
    for db_rule in getattr(model, enabled_rules[rule_type][1]).objects():
        yield db_rule.to_json()



def export_rules(rule_type):
    """
    Export Rules by Category
    """
    if rule_type.lower() in enabled_rules:
        print(json.dumps({"rule_type": rule_type}))
        for rule in export_rules_from_model(rule_type):
            print(rule)
    else:
        print("Ruletype not supported")
        print("Currently supported:")
        print()
        for rulename in sorted(enabled_rules):
            print(rulename)


HOST_COLLECTION_RULE_TYPE = 'host_objects'


def export_all_rules(target_path=None, include_hosts=False):
    """
    Export all Rules of every known type into a single file.

    Hosts and objects (both stored in the Host collection under the
    `host_objects` rule type) are skipped by default because they are usually
    not what you want in a rule backup. Pass `include_hosts=True` to include
    them.
    """
    if not target_path:
        target_path = f"syncer_rules_export_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    total = 0
    with open(target_path, 'w', encoding='utf-8') as outfile:
        for rule_type in sorted(enabled_rules):
            if rule_type == HOST_COLLECTION_RULE_TYPE and not include_hosts:
                print(f"* Skipped {rule_type} (use --include-hosts to export)")
                continue
            header_written = False
            for rule in export_rules_from_model(rule_type):
                if not header_written:
                    outfile.write(json.dumps({"rule_type": rule_type}) + "\n")
                    header_written = True
                outfile.write(rule + "\n")
                total += 1
            if header_written:
                print(f"* Exported {rule_type}")
    print(f"Wrote {total} rules to {target_path}")


def import_line(json_dict, model, rule_type):
    """
    Import a Single line
    """
    print(f"* Import {json_dict['_id']}")
    db_ref = getattr(model, enabled_rules[rule_type][1])()
    new = db_ref.from_json(json.dumps(json_dict))
    try:
        new.save(force_insert=True)
    except NotUniqueError:
        print("   Already existed")
    except ValidationError:
        print(f"Problem with entry: {json_dict}")

def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer.
    Supports single-type files and multi-type files with multiple
    {"rule_type": "..."} header lines.
    """
    with open(rulefile_path, encoding='utf-8') as rulefile:
        rule_type = False
        model = None
        first_json_line = True
        for line in rulefile.readlines():
            try:
                json_dict = json.loads(line)
            except JSONDecodeError:
                print(line)
                continue
            if 'rule_type' in json_dict and len(json_dict) == 1:
                rule_type = json_dict['rule_type']
                if rule_type not in enabled_rules:
                    print(f"Ruletype {rule_type} not supported, skipping block")
                    model = None
                    first_json_line = False
                    continue
                model = importlib.import_module(enabled_rules[rule_type][0])
                print(f"== Importing {rule_type} ==")
                first_json_line = False
                continue
            if not rule_type and first_json_line:
                # No header: guess the type by filename (GUI export mode)
                rule_type = get_ruletype_by_filename(rulefile_path)
                first_json_line = False
                if rule_type not in enabled_rules:
                    print("Ruletype not supported")
                    print(f"Currently supported: {', '.join(enabled_rules.keys())}")
                    return
                model = importlib.import_module(enabled_rules[rule_type][0])
                import_line(json_dict, model, rule_type)
                continue
            first_json_line = False
            if model is None:
                continue
            import_line(json_dict, model, rule_type)
