"""
Create Checkmk Users out of Host Attributes
"""
import secrets
from collections import namedtuple

from application.modules.plugin import Plugin
from application.modules.rule.rule import Rule
from application.helpers.get_account import get_account_by_name
from application.plugins.checkmk.helpers import (
    collect_attribute_index,
    foreach_attribute_items,
)
from application.plugins.checkmk.user_models import (
    CheckmkUserGenerationRule,
    CheckmkUserMngmt,
)
from application.plugins.ldap.ldap import LdapSearchError, get_group_attributes

from application.helpers.syncer_jinja import get_list

from syncerapi.v1 import render_jinja, cc as CC, Host


str_replace = Rule.replace

# Chars a group name may keep when it becomes a Checkmk user id
REPLACE_EXCEPTIONS = ['-', '_']


# The LDAP search one rule describes. Rules describing the very same
# search share one connection and one query, so it is the key the lookup
# is grouped by — which is why it has to be hashable.
GroupSearch = namedtuple(
    'GroupSearch', 'account base_dn group_filter name_attribute attributes')


# One group a rule selected: the name that is searched in the directory
# and the attribute value it was built from. A rewrite may have changed
# the one, so both are Jinja variables of the user fields.
SelectedGroup = namedtuple('SelectedGroup', 'name original')


def rewritten_group_name(template, value):
    """
    The name a rewrite makes out of one attribute value.

    Whatever the template cannot produce for this value — a variable it
    does not carry, an expression that blows up on it, a filter chain
    ending in nothing — is an empty name, and an empty name means the
    value is skipped. Rendering it into the search instead would ask the
    directory for whatever the group filter alone matches.
    """
    try:
        return render_jinja(template, mode='nullify',
                            _ctx={'name': value, 'result': value}).strip()
    except Exception:  # pylint: disable=broad-exception-caught
        return ''


def group_search(outcome, group_filter=''):
    """
    The group search of one rule, normalised.

    `group_filter` overrules the filter the rule carries — that is the
    one filter a debug run tries out against every rule without anybody
    editing the rules first.
    """
    return GroupSearch(
        account=outcome.ldap_account,
        base_dn=(outcome.ldap_base_dn or '').strip(),
        group_filter=(group_filter or '').strip()
                     or (outcome.ldap_group_filter or '').strip(),
        name_attribute=(outcome.ldap_name_attribute or 'cn').strip(),
        attributes=tuple(x.strip() for x
                         in str(outcome.ldap_attributes or '').split(',') if x.strip()),
    )


def read_ldap_groups(search, group_names, debug=False):
    """
    Every attribute the LDAP groups carry, keyed by group name.

    The account contributes the connection and the credentials, nothing
    else: which subtree is searched, which objects count as a group and
    which attribute holds their name is what the rule says.
    """
    config = get_account_by_name(search.account)
    if not config:
        raise LdapSearchError(f"Account '{search.account}' not found")

    config['base_dn'] = search.base_dn or config.get('base_dn') or ''
    # Not the account's own search filter: that one matches the objects of
    # the host import, which are not the groups looked up here.
    config['search_filter'] = search.group_filter

    return get_group_attributes(config, group_names,
                                name_attribute=search.name_attribute,
                                attributes=list(search.attributes),
                                debug=debug)


def render_entries(templates, context):
    """
    The entries of a list field, every one of them a Jinja template.

    Roles and contact groups are names, but which names a group deserves
    is often what the group itself says — a `{{cmk_roles}}` attribute, a
    contact group named after the team. An entry that renders to nothing
    is dropped instead of writing an empty name, and one that renders to
    several names, comma separated or as a list, becomes all of them.
    A plain name without a template is its own result.
    """
    entries = []
    for template in templates or []:
        try:
            rendered = render_jinja(str(template), mode='nullify', _ctx=context)
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        for entry in get_list(rendered):
            entry = str(entry).strip()
            if entry and entry not in entries:
                entries.append(entry)
    return entries


def user_fields(rule, context, user_id, current=None):
    """
    What the Checkmk user of one group should look like.

    `current` is the stored user a former run created, so a template
    rendering to nothing can leave its field as it is instead of
    emptying it. Without one — the preview, a user about to be created —
    those fields simply stay out.

    Returns (wanted, rendered): the fields to write, and what each
    template produced on its own. A template that produced nothing is
    missing from the first and empty in the second, which is what a
    preview has to show instead of quietly leaving the field out.
    """
    outcome = rule.outcome
    wanted = {
        'generated_by_rule': rule.name,
        'full_name': render_jinja(outcome.rewrite_full_name or '',
                                  _ctx=context).strip() or user_id,
        'roles': render_entries(outcome.roles, context),
        'contact_groups': render_entries(outcome.contact_groups, context),
        'disable_login': bool(outcome.disable_login),
    }
    rendered = dict(wanted)
    # A template that renders to nothing — the group has no such
    # attribute — leaves the field as it is instead of emptying it.
    for field, template in (('email', outcome.rewrite_email),
                            ('pager_address', outcome.rewrite_pager_address)):
        value = render_jinja(template, _ctx=context).strip() if template else ''
        rendered[field] = value
        if value:
            wanted[field] = value
        elif current is not None and getattr(current, field, None):
            wanted[field] = getattr(current, field)
    return wanted, rendered


class CheckmkUserGeneration(Plugin):
    """
    Turn Host Attributes into Checkmk User entries
    """
    name = "Checkmk: Generate Users"
    source = "cmk_user_generation"

    # Set by --search-filter: tries one group filter against every rule
    # without anybody editing the rules first
    override_group_filter = ''

    def generate_users(self):
        """
        Run every enabled generation rule
        """
        print(f"\n{CC.HEADER}Read Internal Configuration{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Host Attributes")
        attribute_index = collect_attribute_index(self, Host.get_export_hosts())

        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Rules and collect their Groups")
        rule_groups = []
        for rule in CheckmkUserGenerationRule.objects(enabled=True):
            group_names = self.group_names(rule, attribute_index)
            print(f"{CC.OKBLUE} *{CC.ENDC} {rule.name}: "
                  f"{len(group_names)} group(s) found")
            rule_groups.append((rule, group_names))

        directory = self.lookup_groups(rule_groups)

        print(f"\n{CC.HEADER}Generate Users{CC.ENDC}")
        for rule, selected in rule_groups:
            search = group_search(rule.outcome, self.override_group_filter)
            if search.account and search not in directory:
                # The lookup failed and said so — creating the users now
                # would leave them without their directory data.
                continue
            groups = directory.get(search, {})
            for group in selected:
                self.sync_user(rule, group.name, groups.get(group.name, {}),
                               group.original)

    def group_names(self, rule, attribute_index):
        """
        The groups a single rule selects, each searched name only once.

        `rewrite_group_name` turns the value a host carries into the name
        the directory really knows — a prefix cut off, a domain dropped.
        The value it was made from travels along, so the user fields can
        still name the group the way the host spells it.
        """
        outcome = rule.outcome
        template = getattr(outcome, 'rewrite_group_name', '')
        groups = []
        seen = set()
        for item in foreach_attribute_items(attribute_index,
                                            outcome.foreach_type, outcome.foreach):
            item = str(item).strip()
            name = rewritten_group_name(template, item) if template else item
            if not name:
                if self.debug and item:
                    print(f"INFO: '{item}' rewrote to nothing, no group searched")
                continue
            if name not in seen:
                seen.add(name)
                groups.append(SelectedGroup(name=name, original=item))
        return groups

    def lookup_groups(self, rule_groups):
        """
        The LDAP groups behind the collected names, read once per search.

        Rules that describe the same search — same account, subtree,
        filter and attributes — share one connection and one query, so
        two rules reading the same group area cost one round trip.
        Returns {search: {group: {attribute: value}}}; a search that
        failed is missing, so its rules are skipped instead of creating
        users without their directory data.
        """
        wanted = {}
        for rule, selected in rule_groups:
            search = group_search(rule.outcome, self.override_group_filter)
            if not search.account:
                continue
            names = wanted.setdefault(search, [])
            for group in selected:
                if group.name not in names:
                    names.append(group.name)

        found = {}
        for search, names in wanted.items():
            print(f"{CC.OKGREEN} -- {CC.ENDC} Ask {search.account} for "
                  f"{len(names)} group(s)")
            if self.debug:
                print(f"INFO: Base DN: {search.base_dn or 'the one of the account'}")
                print(f"INFO: Group search filter: {search.group_filter or 'none'}")
                print(f"INFO: Group name attribute: {search.name_attribute}")
            try:
                found[search] = read_ldap_groups(search, names, debug=self.debug)
            except LdapSearchError as error:
                print(f"{CC.FAIL} * {search.account}: LDAP lookup failed: "
                      f"{error}{CC.ENDC}")
                self.log_details.append(
                    ("ERROR", f"{search.account}: LDAP lookup failed: {error}"))
            else:
                if self.debug and (missing := [x for x in names
                                               if x not in found[search]]):
                    print(f"INFO: Not in the directory: {', '.join(missing)}")
        return found

    def plan_user(self, rule, group_name, group, original_name=None):
        """
        What would become of the Checkmk user of one group.

        Every attribute of the LDAP group is a Jinja variable of the
        rule's templates; `name` is the name the group was searched under
        and `original_name` the attribute value it was built from — the
        same thing unless a rewrite changed it. Both win over an
        attribute of the same name.

        Returns the rendered fields, the user id they belong to and
        whether that user would be created, updated or left alone.
        Nothing is written: `sync_user` carries the plan out, the GUI
        preview only shows it.
        """
        context = dict(group)
        context['name'] = group_name
        context['original_name'] = group_name if original_name is None else original_name
        context['result'] = group_name

        plan = {
            'rule': rule.name,
            'name': group_name,
            'original_name': context['original_name'],
            'attributes': dict(group),
            'user_id': '',
            'fields': {},
            'rendered': {},
            'changed': [],
            'action': 'skipped',
            'note': '',
            'user': None,
        }

        user_id = str_replace(render_jinja(rule.outcome.rewrite_user_id or '',
                                           _ctx=context),
                              REPLACE_EXCEPTIONS).strip()
        plan['user_id'] = user_id
        if not user_id:
            plan['note'] = 'the user ID renders to nothing'
            return plan

        # pylint: disable=no-member
        user = CheckmkUserMngmt.objects(user_id=user_id).first()
        if user and not user.generated_by_rule:
            plan['note'] = 'exists and was created by hand'
            return plan

        plan['user'] = user
        plan['fields'], plan['rendered'] = user_fields(rule, context, user_id, user)
        plan['changed'] = [field for field, value in plan['fields'].items()
                           if getattr(user, field, None) != value] \
            if user else list(plan['fields'])
        if not user:
            plan['action'] = 'create'
        elif plan['changed']:
            plan['action'] = 'update'
        else:
            plan['action'] = 'unchanged'
        return plan

    def sync_user(self, rule, group_name, group, original_name=None):
        """
        Create the Checkmk user of one group, or update the one a former
        run created. A user someone made by hand is never touched.
        """
        plan = self.plan_user(rule, group_name, group, original_name)
        user_id = plan['user_id']

        if plan['action'] == 'skipped':
            if user_id:
                print(f"{CC.WARNING}  * {user_id}: {plan['note']}, "
                      f"not touched{CC.ENDC}")
            return
        if plan['action'] == 'unchanged':
            print(f"{CC.OKGREEN}  *{CC.ENDC} {user_id}: Nothing to do")
            return

        user = plan['user'] or CheckmkUserMngmt(
            user_id=user_id,
            # Generated users are contacts, not logins. A random secret
            # keeps the entry valid without anybody knowing a password.
            password=secrets.token_urlsafe(32))
        for field, value in plan['fields'].items():
            setattr(user, field, value)
        user.save()
        print(f"{CC.OKGREEN}  *{CC.ENDC} {user_id}: "
              f"Saved ({', '.join(plan['changed'])})")

    def preview(self, rule_id=None):
        """
        What a run would make of the current hosts and the directory,
        without writing a single user.

        Reads the same host attributes and asks the directory the same
        questions a real run does, so the answer is what would happen —
        not what the rule looks like on paper. `rule_id` limits it to one
        rule. Returns (rows, errors).
        """
        attribute_index = collect_attribute_index(self, Host.get_export_hosts())
        rule_groups = []
        for rule in CheckmkUserGenerationRule.objects(enabled=True):
            if rule_id and str(rule.id) != str(rule_id):
                continue
            rule_groups.append((rule, self.group_names(rule, attribute_index)))

        directory = self.lookup_groups(rule_groups)

        rows = []
        for rule, selected in rule_groups:
            search = group_search(rule.outcome, self.override_group_filter)
            groups = directory.get(search, {})
            for group in selected:
                attributes = groups.get(group.name, {})
                plan = self.plan_user(rule, group.name, attributes, group.original)
                # Without an account no directory is asked at all, so the
                # group is not "missing" — it simply has no attributes.
                plan['searched'] = bool(search.account)
                plan['found'] = bool(attributes)
                plan.pop('user', None)
                rows.append(plan)
        # log_details also carries the run's own bookkeeping — when it
        # started, how long it took. Only the failures are of interest
        # to somebody looking at a preview.
        errors = [(level, message) for level, message in self.log_details
                  if str(level).lower() == 'error']
        return rows, errors
