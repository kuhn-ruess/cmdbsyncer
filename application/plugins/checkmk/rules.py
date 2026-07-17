#!/usr/bin/env python3
"""
Checkmk Rules
"""
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=too-many-nested-blocks,logging-fstring-interpolation
import ast
import re
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from application import app
from application.helpers.syncer_jinja import render_jinja
from application import logger, log
from application.modules.rule.rule import Rule
from application.modules.debug import debug as print_debug
from application.modules.debug import ColorCodes
from . import poolfolder


def _maybe_render(value, **context):
    """
    Render through Jinja only when the value actually contains template
    syntax (`{{` or `{%`). For the common literal-string case this skips
    a parse+render round-trip per host per matched rule.
    """
    if (isinstance(value, str)
            and '{{' not in value
            and '{%' not in value):
        return value
    return render_jinja(value, mode="nullify", **context)


_JINJA_BLOCK_RE = re.compile(r'\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}')
# {{ACCOUNT:name:field}} macros are resolved before Jinja compiles; their bare
# colons are not valid Jinja, so neutralise them before the syntax check.
_ACCOUNT_MACRO_RE = re.compile(r'\{\{\s*ACCOUNT:[^}]+\}\}')
# Own environment for the compile-only syntax check — mirrors syncer_jinja's
# SandboxedEnvironment so parsing matches the real render, without importing it
# (keeps the validator free of any render-time/DB dependency).
_SYNTAX_CHECK_ENV = SandboxedEnvironment(autoescape=False)


def validate_folder_option_param(param):
    """
    Validate a move_folder/create_folder action parameter at save time, without
    host data.

    Two classes of mistake are silently swallowed at export time and hard to
    spot, because a failed render just yields an empty string and the host
    quietly loses its target folder:

    * broken Jinja — e.g. chaining ``.replace(...)`` after a ``|join(...)``
      filter — which raises a ``TemplateSyntaxError`` and nullifies the whole
      value. The template is compiled here (syntax only) to catch it.
    * malformed ``|{options}`` after a valid render: an unbalanced brace
      (``...True}}``), or ``contactgroups`` written as a bare list ``['grp']`` /
      a bare Jinja expression ``{{ groups.split(',') }}`` instead of the Checkmk
      shape ``{'groups': ['grp'], 'use': True}``.

    Host attributes are unknown at save time, so every Jinja construct is
    replaced with ``None`` — a valid literal that is quote-neutral (so it never
    corrupts a surrounding string) and lets ``ast.literal_eval`` parse the dict
    even when a value comes from a ``{{ ... }}`` expression.

    Returns a human-readable error string, or ``None`` when it looks valid (or
    there is nothing to check).
    """
    if not param:
        return None
    # 1. The Jinja must at least compile. A syntax error otherwise renders to
    #    an empty string at export and drops the entire folder path silently.
    try:
        _SYNTAX_CHECK_ENV.from_string(_ACCOUNT_MACRO_RE.sub('x', param))
    except TemplateSyntaxError as exc:
        return (f"The Jinja in the folder value is not valid: {exc.message}. "
                "Check filters and method calls — e.g. you cannot chain "
                "'.replace(...)' directly after a '|join(...)' filter.")
    if '|' not in param:
        return None
    literal = _JINJA_BLOCK_RE.sub('None', param)
    for segment in literal.split('/'):
        parts = segment.split('|')
        if len(parts) != 2:
            continue
        suffix = parts[1].strip()
        if not suffix:
            continue
        try:
            parsed = ast.literal_eval(suffix)
        except SyntaxError as exc:
            return (f"Folder options after '|' are not valid: {exc}. "
                    "Check for a stray or missing brace (e.g. a doubled '}}').")
        except ValueError:
            # Still not a literal (e.g. a Jinja block glued to a bareword) —
            # cannot be judged at save time, leave it to the export.
            continue
        if isinstance(parsed, dict) and 'contactgroups' in parsed \
                and not isinstance(parsed['contactgroups'], dict):
            return ("Folder option 'contactgroups' must be a dict like "
                    "{'groups': [...], 'use': True}, not a bare list or "
                    "expression. Keep the {'groups': ..., 'use': True} wrapper "
                    "even when 'groups' comes from Jinja.")
    return None


def parse_folder_options_debug(extra_folder_options):
    """
    Parse an already-rendered ``folder|{options}`` string for the debug view.

    ``extra_folder_options`` is the outcome value the export would feed to the
    folder handler (Jinja already resolved). Returns ``(mapping, error)`` where
    ``mapping`` is ``{folder_path: attributes}`` for every option that parses,
    and ``error`` is a human-readable message for the first suffix that does
    not (else ``None``) — the same failure the export would silently skip.
    """
    mapping = {}
    if not extra_folder_options:
        return mapping, None
    config_path = ""
    for current_path in extra_folder_options.split('/'):
        parts = current_path.split('|')
        folder = parts[0].strip()
        if not folder:
            continue
        config_path += "/" + folder
        if len(parts) == 2 and parts[1].strip():
            suffix = parts[1].strip()
            try:
                mapping[config_path] = ast.literal_eval(suffix)
            except (ValueError, SyntaxError) as exc:
                return mapping, (f"{config_path}: {suffix} — {exc} "
                                 "(check for a stray or missing brace)")
    return mapping, None


class CheckmkRulesetRule(Rule):
    """
    Rule to create Rulesets in Checkmk
    """

    name = "Checkmk -> CMK Rules Managment"


    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add matching Rules to the set
        """
        for outcome in rule_outcomes:
            ruleset_type = outcome['ruleset']
            outcomes.setdefault(ruleset_type, [])
            outcomes[ruleset_type].append(outcome)
        return outcomes


class DefaultRule(Rule):
    """
    Just adds all to the set
    """

    def __init__(self, name="default"):
        """
        Init
        """
        super().__init__()

        if not self.name:
            self.name = name

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add matching Rules to the set
        """
        outcomes.setdefault('default', [])
        for outcome in rule_outcomes:
            outcomes['default'].append(outcome)
        return outcomes

class CheckmkRule(Rule):
    """
    Class to get actions for rule
    """

    name = "Checkmk -> Export Rules"

    found_poolfolder_rule = False # Spcific Helper for this kind of action
    db_host = False

    def fix_and_format_foldername(self, folder):
        """ Format Foldername
        Remove Extra Folder Attributes
        """
        parts = []
        for folder_part in folder.split('/'):
            splitted = folder_part.split('|')
            # Strip whitespace around the pipe boundary — admins (and our own
            # docs) write "folder | {options}" with spaces, and (' ', '_') in
            # REPLACERS would otherwise turn the trailing space into a "_" and
            # create a different folder than the one that already exists.
            folder_name = splitted[0].strip()
            if folder_name:
                parts.append(folder_name)
        new_folder = "/" + "/".join(parts)

        new_folder = self.replace(new_folder, exceptions=['/'])
        if app.config['CMK_LOWERCASE_FOLDERNAMES']:
            new_folder = new_folder.lower()
        new_path = self.replace(new_folder, regex='[^a-z A-Z 0-9/_-]')
        if new_path[-1] == '/':
            return new_path[:-1]
        return new_path

    def format_foldername(self, folder):
        """
        Fix invalid chars in Folder Path
        """
        parts = []
        for folder_part in folder.split('/'):
            splitted = folder_part.split('|')
            # Strip whitespace around the pipe boundary so "folder | {options}"
            # keeps the clean folder name — see fix_and_format_foldername.
            path = splitted[0].strip()
            if app.config['CMK_LOWERCASE_FOLDERNAMES']:
                path = path.lower()
            folder_name = self.replace(self.replace(path, exceptions=['/']),
                                       regex='[^a-z A-Z 0-9/_-]')
            if len(splitted) == 2:
                folder_name += "|" + splitted[1].strip()
            if folder_name:
                parts.append(folder_name)
        new_path = "/" + "/".join(parts)
        if new_path[-1] == '/':
            return new_path[:-1]
        return new_path

    def _apply_folder_outcome(self, action_param, outcomes, folder_key, options_key):
        """
        Render a move_folder/create_folder value and store the folder path plus
        its embedded ``|{options}`` dict.

        Rendering uses ``nullify`` so an undefined *folder* variable still skips
        the rule (documented behaviour). But when the value nullifies only
        because a variable inside the folder OPTIONS is undefined (e.g. a
        contact group), the folder PATH is salvaged from a tolerant render and
        the options are dropped. Otherwise a single missing option variable
        would empty the whole value and dump every affected host into the root
        folder.
        """
        rendered = _maybe_render(action_param, **self.attributes)
        if rendered:
            outcomes[options_key] += self.format_foldername(rendered)
            outcomes[folder_key] += self.fix_and_format_foldername(rendered)
            return
        # Nullified — keep the folder path if it still resolves without the
        # (unresolved) options, so the host stays in its folder.
        folder_only = self.fix_and_format_foldername(
            render_jinja(action_param, mode="ignore", **self.attributes))
        if folder_only and folder_only != '/':
            outcomes[folder_key] += folder_only
            outcomes[options_key] += folder_only
            if '|' in action_param:
                # The folder path is salvaged above, but a variable inside the
                # |{options} did not resolve, so the options are gone. Report it
                # instead of dropping them silently.
                hostname = getattr(self.db_host, 'hostname', '') or ''
                print(f"{ColorCodes.WARNING} !! {ColorCodes.ENDC}Checkmk folder "
                      f"options for {folder_only} dropped: a variable inside "
                      f"{action_param!r} did not resolve")
                log.log("Checkmk folder options dropped (unresolved variable)",
                        affected_hosts=[hostname] if hostname else [],
                        source="Checkmk Export",
                        details=[("folder", folder_only),
                                 ("action_param", action_param)])
            return
        # Nothing salvageable. A broken template (e.g. a Jinja syntax error)
        # renders to '' in every mode, so the host would silently lose its
        # folder. Tell the two apart without host data: a real defect trips the
        # validator, a merely-undefined folder variable does not (documented
        # skip) and stays quiet.
        defect = validate_folder_option_param(action_param)
        if defect:
            hostname = getattr(self.db_host, 'hostname', '') or ''
            print(f"{ColorCodes.FAIL} !! {ColorCodes.ENDC}Checkmk folder value "
                  f"{action_param!r} is broken and was skipped: {defect}")
            log.log("Checkmk folder value broken (skipped)",
                    affected_hosts=[hostname] if hostname else [],
                    source="Checkmk Export",
                    details=[("action_param", action_param),
                             ("error", defect)])

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """ Handle the Outcomes """

        possible_outcomes = [
            ('move_folder',""),
            ('extra_folder_options',""),
            ('attributes', []),
            ('custom_attributes', {}),
            ('remove_attributes', []),
            ('remove_if_attributes', []),
            ('create_cluster', []),
            ('create_folder', ""),
            ('create_folder_extra_folder_options', ""),
            ('prefix_labels', False),
            ('only_update_prefixed_labels', False),
            ('dont_update_prefixed_labels', []),
            ('parents', []),
            ('dont_move', False),
            ('dont_create', False),
            ('dont_update', False),
        ]
        for choice, default in possible_outcomes:
            outcomes.setdefault(choice, default)

        print_debug(self.debug,
                    "- Handle Special options")

        for outcome in rule_outcomes:
            # We add only the outcome of the
            # first matching rule action
            # exception are the folders



            action_param = outcome['action_param']
            if outcome['action'] == 'move_folder':
                self._apply_folder_outcome(
                    action_param, outcomes,
                    'move_folder', 'extra_folder_options')


            if outcome['action'] == 'dont_move':
                outcomes['dont_move'] = True

            if outcome['action'] == 'dont_create':
                outcomes['dont_create'] = True

            if outcome['action'] == 'dont_update':
                outcomes['dont_update'] = True

            if outcome['action'] == 'prefix_labels':
                outcomes['label_prefix'] = action_param

            if outcome['action'] == 'only_update_prefixed_labels':
                outcomes['only_update_prefixed_labels'] = action_param

            if outcome['action'] == 'dont_update_prefixed_labels':
                if action_param not in outcomes['dont_update_prefixed_labels']:
                    outcomes['dont_update_prefixed_labels'].append(action_param)

            if outcome['action'] == 'create_folder':
                self._apply_folder_outcome(
                    action_param, outcomes,
                    'create_folder', 'create_folder_extra_folder_options')

            if outcome['action'] == 'folder_pool':
                self.found_poolfolder_rule = True
                # Check if the Host is assigned to an folder already
                if self.db_host.get_folder():
                    folder_name = self.db_host.get_folder()
                    outcomes['extra_folder_options'] += folder_name
                    outcomes['move_folder'] += folder_name
                else:
                    # Assign an new, free folder to Host
                    only_pools = None
                    if action_param:
                        action_param = _maybe_render(action_param, **self.attributes)
                        only_pools = [x.strip() for x in action_param.split(',')]
                    folder = poolfolder.get_folder(only_pools)
                    if not folder:
                        log.log("No Pool Folder left",
                                affected_hosts=[self.db_host.hostname],
                                source="folder_pool",
                                details=[("error", f"No free pool folder for "\
                                          f"{self.db_host.hostname} (pools: {only_pools})")])
                        raise ValueError(f"No Pool Folder left for {self.db_host.hostname}")
                    folder_name = self.format_foldername(folder.folder_name)
                    self.db_host.lock_to_folder(folder_name)
                    extra_ops = {}
                    if folder.folder_title:
                        extra_ops['title'] = folder.folder_title
                    if folder.assigned_site_id:
                        extra_ops['site'] = folder.assigned_site_id
                    folder_w_ops = folder_name
                    if extra_ops:
                        folder_w_ops = f"{folder_name}|{str(extra_ops)}"

                    outcomes['extra_folder_options'] += self.format_foldername(folder_w_ops)
                    outcomes['move_folder'] += self.fix_and_format_foldername(folder_w_ops)

            if outcome['action'] == 'attribute':
                outcomes['attributes'].append(action_param)

            if outcome['action'] == "remove_attr_if_not_set":
                action_render = _maybe_render(action_param, **self.attributes)

                for attribute in action_render.split(','):
                    attribute = attribute.strip()
                    outcomes['remove_if_attributes'].append(attribute)

            if outcome['action'] == 'custom_attribute':
                action_render = _maybe_render(action_param, **self.attributes)

                action_render = self.replace(action_render, exceptions=[
                                                        " ", '/', ',','|'
                                                    ]) # Replace Chars not working in Checkmk


                python_detectors = ['[', '{']
                if action_render:
                    attrs = action_render.split('||')
                    for attr_pair in attrs:
                        if not attr_pair:
                            continue
                        try:
                            new_key, new_value = attr_pair.split(':', 1)
                            new_key = new_key.strip()
                            new_value = new_value.strip()
                            if any(x in new_value for x in python_detectors):
                                try:
                                    new_value = ast.literal_eval(new_value)
                                except SyntaxError:
                                    pass

                            if str(new_value).lower() in ['none', 'false']:
                                outcomes['remove_attributes'].append(new_key)
                            elif new_key and new_value:
                                outcomes['custom_attributes'][new_key] = new_value
                        except ValueError:
                            logger.debug(f"Cant split '{attr_pair}'")

            if outcome['action'] == "set_parent":
                value = action_param
                new_value = _maybe_render(value, **self.attributes)
                for parent in new_value.split(','):
                    parent = parent.strip()
                    if parent and parent not in outcomes['parents']:
                        outcomes['parents'].append(parent)


            if outcome['action'] == 'value_as_folder':
                search_tag = action_param
                print_debug(self.debug,
                            f"---- value_as_folder matched, search tag '{search_tag}'")
                for tag, value in self.attributes.items():
                    if search_tag == tag:
                        if value and value != 'null':
                            print_debug(self.debug, f"----- {ColorCodes.OKGREEN}Found tag"\
                                                    f"{ColorCodes.ENDC}, add folder: '{value}'")
                            outcomes['extra_folder_options'] += self.format_foldername(value)
                            outcomes['move_folder'] += self.fix_and_format_foldername(value)
                        else:
                            print_debug(self.debug, \
                                f"----- {ColorCodes.OKGREEN}Found tag but content null")

            if outcome['action'] == 'tag_as_folder':
                search_value = action_param
                print_debug(self.debug,
                            f"---- tag_as_folder matched, search value '{search_value}'")
                for tag, value in self.attributes.items():
                    if search_value == value:
                        if value and value != 'null':
                            print_debug(self.debug, f"------ {ColorCodes.OKGREEN}Found value"\
                                                    f"{ColorCodes.ENDC}, add folder: '{tag}'")
                            outcomes['extra_folder_options'] += self.format_foldername(tag)
                            outcomes['move_folder'] += self.fix_and_format_foldername(tag)
                        else:
                            print_debug(self.debug, \
                                f"----- {ColorCodes.OKGREEN}Found value but content null")

            if outcome['action'] == 'create_cluster':
                params = [x.strip() for x in action_param.split(',')]
                for node_tag in params:
                    if node_tag.endswith('*'):
                        for tag, value in self.attributes.items():
                            if tag.startswith(node_tag[:-1]):
                                outcomes['create_cluster'].append(value)
                    else:
                        if node := self.attributes.get(node_tag):
                            outcomes['create_cluster'].append(node)

        # Cleanup in case not folder rule applies,
        # we have nothing to return to the plugins
        for choice, _ in possible_outcomes:
            if not outcomes[choice]:
                del outcomes[choice]

        print_debug(self.debug, "")
        return outcomes

    def check_rule_match(self, db_host):
        """
        Overwritten cause of folder_pool
        """

        hostname = db_host.hostname

        # Variable will set possibly to true since
        # self.check_rules() will check the add_outcomes method.
        # @Todo something simpler to understand would be better.
        self.found_poolfolder_rule = False

        self.db_host = db_host
        outcomes = self.check_rules(hostname)
        # This Host does not match to an poolfolder rule
        if not self.found_poolfolder_rule:
            if db_host.get_folder():
                old_folder = db_host.get_folder()
                db_host.lock_to_folder(False)
                poolfolder.remove_seat(old_folder)
        return outcomes
