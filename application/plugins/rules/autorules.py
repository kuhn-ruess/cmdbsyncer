from application.modules.plugin import Plugin
from syncerapi.v1 import Host, render_jinja
from .models import SyncerRuleAutomation
from .rule_definitions import rules
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
import json
import importlib



class RuleCreation(Plugin):

    found_objects = {}

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
            # Import the module dynamically
            module = importlib.import_module(module_path)
            # Get the model class
            model_class = getattr(module, model_name)
            return model_class
        except (ImportError, AttributeError) as e:
            print(f"Error loading model {model_name} from {module_path}: {e}")
            return None


    def rule_exists(self, model_class, rule_body_json):
        """
        Check if a rule with the given rule_body already exists
        
        :param model_class: The model to search in
        :param rule_body_json: The rule_body as JSON dict
        :return: True if rule exists, False otherwise
        """
        try:
            # Try to search for an existing rule
            # This depends on the specific model, but most have 'name' or similar fields
            if hasattr(model_class, 'objects'):
                # Search by name if available
                if 'name' in rule_body_json:
                    existing = model_class.objects(name=rule_body_json['name']).first()
                    return existing is not None
                print("Rule Model does not have required name field")  
                return False
        except Exception as e:
            print(f"Error checking for existing rule: {e}")
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
            
        valid_fields = set(model_class._fields.keys())
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
            # Filter out invalid fields
            filtered_data = self.filter_valid_fields(model_class, rule_body_json)
            
            # Create a new instance of the model class
            new_rule = model_class(**filtered_data)
            new_rule.save()
            print(f"New rule created: {filtered_data.get('name', 'Unnamed')}")
            return True
        except Exception as e:
            print(f"Error creating rule: {e}")
            return False


    def create_rules(self):
        enabled_rules = list(SyncerRuleAutomation.objects(enabled=True))
        
        # Calculate total work for progress bar
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
                
                progress.console.print(f"- Processing rule type: {rule_type} for filter: {object_filter}")
                
                # Load the model for the rule_type
                model_class = self.get_rule_model(rule_type)
                if not model_class:
                    progress.console.print(f"[red]Model for rule_type '{rule_type}' could not be loaded[/red]")
                    continue
                
                if object_filter not in self.found_objects:
                    self.found_objects[object_filter] = []
                    for object in Host.objects(object_type=object_filter):
                        attributes = self.get_attributes(object, 'syncer_rules')['all']
                        self.found_objects[object_filter].append(attributes)
                        progress.advance(task1)
                else:
                    progress.advance(task1, advance=len(self.found_objects[object_filter]))

                task2 = progress.add_task(f"Creating Rules for {rule_type}", total=len(self.found_objects[object_filter]))
                for attribute_set in self.found_objects[object_filter]:
                    rule_body = render_jinja(rule.rule_body, **attribute_set)
                    rule_body_json = json.loads(rule_body)
                    
                    # Check if the rule already exists
                    if not self.rule_exists(model_class, rule_body_json):
                        if self.create_rule(model_class, rule_body_json):
                            progress.console.print(f"[green]✓[/green] Created rule: {rule_body_json.get('name', 'Unnamed')}")
                        else:
                            progress.console.print(f"[red]✗[/red] Failed to create rule: {rule_body_json.get('name', 'Unnamed')}")
                    else:
                        progress.console.print(f"[yellow]→[/yellow] Rule '{rule_body_json.get('name', 'Unnamed')}' already exists")
                    progress.advance(task2)
                

def create_rules(account=False, debug=False):
    """
    Trigger Rule Creation Functions
    
    :param account: Not used
    :param debug: Trigger Debug Mode
    """

    rule_creation = RuleCreation()
    rule_creation.debug = debug
    rule_creation.create_rules()