"""
Syncer rule automation: build rules from host objects using templates.
"""
import importlib
import json

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.plugin import Plugin
from syncerapi.v1 import Host, render_jinja

from .models import SyncerRuleAutomation
from .rule_definitions import rules


class RuleCreation(Plugin):
    """
    Build and persist syncer rules from configured SyncerRuleAutomation
    entries by rendering templates against the current Host objects.
    """

    def __init__(self, account=False):
        super().__init__(account)
        # Per-instance cache. Keeping this on the class kept stale host
        # attribute snapshots around across repeated runs so later runs
        # generated rules from outdated data instead of the current DB.
        self.found_objects = {}

    def get_rule_model(self, rule_type):
        """
        Load the model for the given rule_type

        :param rule_type: The rule type from rule_definitions
        :return: The model class or None if not found
        """
        if rule_type not in rules:
            print(f"Rule type '{rule_type}' not found in rule_definitions")
            return None

        module_path, model_name = rules[rule_type]

        try:
            module = importlib.import_module(module_path)
            model_class = getattr(module, model_name)
            return model_class
        except (ImportError, AttributeError) as exc:
            print(f"Error loading model {model_name} from {module_path}: {exc}")
            return None


    def rule_exists(self, model_class, rule_body_json):
        """
        Check if a rule with the given rule_body already exists

        :param model_class: The model to search in
        :param rule_body_json: The rule_body as JSON dict
        :return: True if rule exists, False otherwise
        """
        try:
            if hasattr(model_class, 'objects'):
                if 'name' in rule_body_json:
                    existing = model_class.objects(name=rule_body_json['name']).first()
                    return existing is not None
                print("Rule Model does not have required name field")
                return False
            return False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Error checking for existing rule: {exc}")
            return False


    def filter_valid_fields(self, model_class, rule_body_json):
        """
        Filter out fields that don't exist in the model

        :param model_class: The model class to check against
        :param rule_body_json: The rule_body as JSON dict
        :return: Filtered dict with only valid fields
        """
        if not hasattr(model_class, '_fields'):
            return rule_body_json

        valid_fields = set(model_class._fields.keys())  # pylint: disable=protected-access
        filtered_data = {}

        for key, value in rule_body_json.items():
            if key in valid_fields:
                filtered_data[key] = value
            else:
                print(f"Skipping invalid field '{key}' for model {model_class.__name__}")

        return filtered_data


    def create_rule(self, model_class, rule_body_json):
        """
        Create a new rule in the given model

        :param model_class: The model in which to create the rule
        :param rule_body_json: The rule_body as JSON dict
        :return: True if successfully created, False otherwise
        """
        try:
            filtered_data = self.filter_valid_fields(model_class, rule_body_json)
            new_rule = model_class(**filtered_data)
            new_rule.save()
            print(f"New rule created: {filtered_data.get('name', 'Unnamed')}")
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Error creating rule: {exc}")
            return False


    # pylint: disable-next=too-many-locals
    def create_rules(self):
        """
        Iterate enabled SyncerRuleAutomation entries, render each rule
        body against matching Host objects, and create missing rules.
        """
        enabled_rules = list(SyncerRuleAutomation.objects(enabled=True))

        total_work = 0
        for rule in enabled_rules:
            object_filter = rule.object_filter
            host_count = Host.objects(object_type=object_filter).count()
            total_work += host_count

        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Processing Config", total=total_work)

            for rule in enabled_rules:
                object_filter = rule.object_filter
                rule_type = rule.rule_type

                progress.console.print(
                    f"- Processing rule type: {rule_type} for filter: {object_filter}"
                )

                model_class = self.get_rule_model(rule_type)
                if not model_class:
                    progress.console.print(
                        f"[red]Model for rule_type '{rule_type}' could not be loaded[/red]"
                    )
                    continue

                if object_filter not in self.found_objects:
                    self.found_objects[object_filter] = []
                    for host_obj in Host.objects(object_type=object_filter):
                        attributes = self.get_attributes(host_obj, 'syncer_rules')['all']
                        self.found_objects[object_filter].append(attributes)
                        progress.advance(task1)
                else:
                    progress.advance(task1, advance=len(self.found_objects[object_filter]))

                task2 = progress.add_task(
                    f"Creating Rules for {rule_type}",
                    total=len(self.found_objects[object_filter]),
                )
                for attribute_set in self.found_objects[object_filter]:
                    rule_body = render_jinja(rule.rule_body, **attribute_set)
                    rule_body_json = json.loads(rule_body)

                    name = rule_body_json.get('name', 'Unnamed')
                    if self.rule_exists(model_class, rule_body_json):
                        progress.console.print(
                            f"[yellow]→[/yellow] Rule '{name}' already exists"
                        )
                    elif self.create_rule(model_class, rule_body_json):
                        progress.console.print(f"[green]✓[/green] Created rule: {name}")
                    else:
                        progress.console.print(f"[red]✗[/red] Failed to create rule: {name}")
                    progress.advance(task2)


def create_rules(account=False, debug=False):  # pylint: disable=unused-argument
    """
    Trigger Rule Creation Functions

    :param account: Not used
    :param debug: Trigger Debug Mode
    """

    rule_creation = RuleCreation()
    rule_creation.debug = debug
    rule_creation.create_rules()
