#!/usr/bin/env python3
"""
Handle Rule Matching
"""
# pylint: disable=too-many-return-statements,too-many-locals,too-many-branches
# pylint: disable=too-many-instance-attributes
import ast
import re
from rich.console import Console
from rich.table import Table
from rich import box

from application import logger, app
from application.modules.rule.match import match
from application.helpers.syncer_jinja import render_jinja


# Module-level constants to avoid per-call dict/string allocation in the
# rule-engine hot path.
_RULE_DESCRIPTIONS = {
    'any': "ANY can match",
    'all': "ALL must match",
    'anyway': "ALWAYS match",
}

class Rule():
    """
    Base Rule Class
    """
    debug = False
    debug_lines = []
    rules = []
    name = ""
    attributes = {}
    hostname = False
    db_host = False
    cache_name = False
    first_matching_tag = None # Is this set here, it can be accessed in Ninja currently for rewrites
    first_matching_value = None


    def __init__(self):
        """
        Init
        """
        # Reset Debug Lines in Order for each child
        # of this class having a new log
        self.debug_lines = []
        # Cached (id(self.rules), [rule objs], [rule.to_mongo() docs]).
        # Invalidated automatically when self.rules is reassigned.
        self._rule_docs_cache = None
        # Default cache key derived from the concrete rule-engine class.
        # Computed once — get_outcomes is otherwise on the hot path.
        self._default_cache_key = self.__class__.__qualname__.replace('.', '')


    @staticmethod
    def replace(input_raw, exceptions=None, regex=None):
        """
        Replace all given inputs
        """
        if regex:
            result = re.sub(regex, '', input_raw.strip())
            return result
        if not exceptions:
            exceptions = []
        input_str = str(input_raw)
        for needle, replacer in app.config['REPLACERS']:
            if needle in exceptions:
                continue
            input_str = input_str.replace(needle, replacer)
        return input_str.strip()

    def _check_attribute_match(self, condition):
        """
        Check if on of the given attributes match the rule
        """
        needed_tag = condition['tag']
        tag_match = condition['tag_match']
        tag_match_negate = condition['tag_match_negate']

        needed_value = condition['value']
        value_match = condition['value_match']
        value_match_negate = condition['value_match_negate']


        # Skip the Jinja render pipeline when the value is plainly literal —
        # that is the common case (concrete strings / numbers from the rule
        # form) and render_jinja is non-trivially hot when called for every
        # condition * every host.
        if (not isinstance(needed_value, str)
                or '{{' in needed_value
                or '{%' in needed_value):
            needed_value = render_jinja(needed_value, **self.attributes)

        if tag_match == 'ignore' and tag_match_negate:
            # This Case Checks that Tag NOT Exists
            if needed_tag not in self.attributes.keys():
                return True
            return False

        # Fast path: `equal` tag match with a concrete target is a dict
        # lookup, not a linear scan of every attribute. Skipped when the
        # target is a custom_fields expression because that branch rewrites
        # tag/value mid-iteration below.
        if (tag_match == 'equal' and not tag_match_negate
                and 'custom_fields' not in needed_tag):
            if needed_tag not in self.attributes:
                return False
            value = self.attributes[needed_tag]
            if match(value, needed_value, value_match, value_match_negate):
                if app.config['ADVANCED_RULE_DEBUG']:
                    logger.debug('--> HIT (fast tag lookup)')
                    self.first_matching_tag = needed_tag
                    self.first_matching_value = value
                return True
            return False

        # Wee need to find out if tag AND tag value match
        for tag, value in self.attributes.items():
            # Handle special dict key custom_fields
            # @Todo Find out where this is used and add it to the documentation
            # the clue is Idoit.
            if "custom_fields" == tag and isinstance(value, dict):
                for name, content in value.items():
                    if f'custom_fields["{name}"]' == needed_tag:
                        # User writting custom_fields["name"]
                        tag = f'custom_fields["{name}"]'
                        value = content
                    elif f"custom_fields['{name}']" == needed_tag:
                        # User writting custom_fields['name']
                        tag = f"custom_fields['{name}']"
                        value = content

            # Check if Tag matchs
            if app.config['ADVANCED_RULE_DEBUG']:
                logger.debug(
                    "Check Tag: %s vs needed: %s for %s, Negate: %s",
                    tag,
                    needed_tag,
                    tag_match,
                    tag_match_negate,
                )
            # If the Tag with the Name matches, we cann check if the value is allright
            if match(tag, needed_tag, tag_match, tag_match_negate):
                if app.config['ADVANCED_RULE_DEBUG']:
                    logger.debug('--> HIT')
                    logger.debug(
                        "Check Attr Value: %r vs needed: %r for %s, Negate: %s",
                        value,
                        needed_value,
                        value_match,
                        value_match_negate,
                    )
                # Tag had Match, now see if Value Matches too
                if match(value, needed_value, value_match, value_match_negate):
                    if app.config['ADVANCED_RULE_DEBUG']:
                        logger.debug('--> HIT')
                        self.first_matching_tag = tag
                        self.first_matching_value = value
                    return True
        return False

    @staticmethod
    def _check_hostname_match(condition, hostname):
        """
        Check if Condition Matchs to Hostname
        """
        needed = condition['hostname'].lower()
        host_match = condition['hostname_match'].lower()
        negate = condition['hostname_match_negate']

        if match(hostname.lower(), needed, host_match, negate):
            return True
        return False


    def handle_match(self, condition, hostname):
        """
        Check if a Host or Attribute Condition has a match
        """
        if condition['match_type'] == 'tag':
            return self._check_attribute_match(condition)
        return self._check_hostname_match(condition, hostname)

    def _iter_rule_docs(self):
        """
        Materialise `rule.to_mongo()` once per rules QuerySet and cache
        the result in hot-path-friendly shapes. `self.rules` is typically
        a mongoengine QuerySet that is evaluated repeatedly — one
        `.to_mongo()` per rule per host — even though the rules themselves
        don't change across the run. Cache is invalidated when the
        identity of `self.rules` changes.

        Returns two parallel lists:
        - rule objects (kept for .name access during debug)
        - prepared rule dicts with plain-dict conditions and outcomes so
          the hot loop does cheap dict access instead of SON lookups.
        """
        current_key = id(self.rules)
        cache = self._rule_docs_cache
        if cache is not None and cache[0] == current_key:
            return cache[1], cache[2]
        objs = list(self.rules)
        prepared = []
        for rule_obj in objs:
            doc = rule_obj.to_mongo()
            prepared.append({
                'condition_typ': doc.get('condition_typ'),
                'conditions': [dict(c) for c in doc.get('conditions', [])],
                'outcomes': [dict(o) for o in doc.get('outcomes', [])],
                'last_match': doc.get('last_match', False),
                'name': doc.get('name', ''),
                '_id': doc.get('_id'),
            })
        self._rule_docs_cache = (current_key, objs, prepared)
        return objs, prepared

    # pylint: disable=too-many-branches
    def check_rules(self, hostname):
        """
        Handle Rule Match logic
        """
        # Reset per-host match state so a prior host's hit cannot leak
        # into this host's FIRST_MATCHING_TAG/VALUE when the engine
        # instance is reused across hosts (e.g. persisted CustomAttribute
        # engine, or anyway-condition rules that never call handle_match).
        self.first_matching_tag = None
        self.first_matching_value = None
        debug_advanced = app.config['ADVANCED_RULE_DEBUG']
        if self.debug:
            title = f"Debug '{self.name}' Rules for {hostname}"

            table = Table(title=title, box=box.ASCII_DOUBLE_HEAD,\
                        header_style="bold blue", title_style="yellow", \
                        title_justify="left", width=90)
            table.add_column("Hit")
            table.add_column("Description")
            table.add_column("Rule Name")
            table.add_column("Rule ID")
            table.add_column("Last Match")

        outcomes = {}
        rule_objs, prepared_rules = self._iter_rule_docs()
        for rule_obj, rule in zip(rule_objs, prepared_rules):
            if debug_advanced:
                logger.debug('##########################')
                logger.debug('Check Rule: %s', rule_obj.name)
                logger.debug('##########################')
            rule_hit = False
            condition_typ = rule['condition_typ']
            conditions = rule['conditions']

            no_match_reason = None
            if condition_typ == 'any':
                for condition in conditions:
                    if self.handle_match(condition, hostname):
                        rule_hit = True
                        no_match_reason = None
                        break # We have a hit, no need to check more
                    if self.debug:
                        no_match_reason = dict(condition)

            elif condition_typ == 'all':
                rule_hit = True
                for condition in conditions:
                    if not self.handle_match(condition, hostname):
                        rule_hit = False
                        if self.debug:
                            no_match_reason = dict(condition)
                        break # One was no hit, no need for loop

            elif condition_typ == 'anyway':
                rule_hit = True


            if self.debug:
                debug_data = {
                    "group": self.name,
                    "hit": rule_hit,
                    'no_match_reason': no_match_reason,
                    "condition_type": _RULE_DESCRIPTIONS[condition_typ],
                    "name": rule['name'],
                    "id": str(rule['_id']),
                    "last_match": str(rule['last_match']),
                }
                self.debug_lines.append(debug_data)
                table.add_row(str(rule_hit), _RULE_DESCRIPTIONS[condition_typ],\
                              rule['name'][:30], str(rule['_id']), str(rule['last_match']))
            if rule_hit:
                # outcomes were pre-converted to plain dicts in
                # _iter_rule_docs so we don't rebuild them per host.
                outcomes = self.add_outcomes(rule, rule['outcomes'], outcomes)
                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    break
        if self.debug:
            console = Console()
            console.print(table)
            print()
        return outcomes

    def handle_fields(self, _field_name, field_value):
        """
        Default, overwrite if needed
        Rewrites Attributes if needed in get_multilist_outcomes mode
        """
        return field_value

    # pylint: disable=too-many-locals,too-many-nested-blocks,too-many-branches
    def get_multilist_outcomes(self, rule_outcomes, ignore_field):
        """
        Central Function which helps 
        with list based outcomes to prevent the need of to many rules
        """
        outcome_selection = []

        defaults_for_list = {}
        defaults_by_id = {}
        #hostname = self.db_host.hostname

        ignore_list = []

        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']
            if outcome['list_variable_name']:
                varname = outcome['list_variable_name']

                if input_list := self.attributes.get(varname):
                    if isinstance(input_list, str):
                        input_list = ast.literal_eval(input_list.replace('\n',''))
                    for idx, data in enumerate(input_list):
                        defaults_by_id.setdefault(idx, {})

                        if isinstance(action_param, list):
                            new_list = []
                            for entry in action_param:
                                new_value  = render_jinja(entry, mode="nullify",
                                                         LIST_VAR=data,
                                                         **self.attributes)
                                if new_value:
                                    new_list.append(new_value)
                            new_value = new_list
                        else:
                            new_value  = render_jinja(action_param, mode="nullify",
                                                     LIST_VAR=data,
                                                     **self.attributes)

                        new_value = new_value.strip()
                        if new_value.startswith('[') and new_value.endswith(']'):
                            new_value = ast.literal_eval(new_value.replace('\n',''))
                            # Remove empty entries
                            new_value = [x for x in new_value if x]

                        new_value = self.handle_fields(action, new_value)

                        if new_value == 'SKIP_RULE':
                            defaults_by_id[idx] = False
                        elif new_value != 'SKIP_FIELD':
                            defaults_by_id[idx][action] = new_value
                        #else:
                        #    defaults_by_id[idx][action] = False
            else:
                new_value  = render_jinja(action_param, mode="nullify", **self.attributes)
                new_value = new_value.strip()
                new_value = self.handle_fields(action, new_value)
                if new_value != 'SKIP_FIELD':
                    defaults_for_list[action] = new_value
                #else:
                #    defaults_for_list[action] = False

            if action == ignore_field:
                ignore_list += [x.strip() for x in new_value.split(',')]
                continue


        if defaults_by_id:
            for collection_data in defaults_by_id.values():
                collection_data.update(defaults_for_list)
                outcome_selection.append(collection_data)
        else:
            outcome_selection.append(defaults_for_list)

        return outcome_selection, ignore_list


    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Please implement
        """
        raise NotImplementedError

    def check_rule_match(self, db_host):
        """
        Handle Return of outcomes.
        This Function in needed in case a plugin needs to overwrite
        content in the class. In this case the plugin like checkmk rule overwrite this function
        """
        return self.check_rules(db_host.hostname)


    def get_outcomes(self, db_host, attributes, persist_cache=True):
        """
        Handle Return of outcomes.
        """
        cache = self.cache_name or self._default_cache_key
        if cache in db_host.cache:
            logger.debug("Using Rule Cache for %s", db_host.hostname)
            return db_host.cache[cache]

        self.attributes = attributes
        self.hostname = db_host.hostname
        self.db_host = db_host
        rules = self.check_rule_match(db_host)
        db_host.cache[cache] = rules
        if persist_cache:
            db_host.save()
        else:
            setattr(db_host, '_cache_dirty', True)
        return rules
