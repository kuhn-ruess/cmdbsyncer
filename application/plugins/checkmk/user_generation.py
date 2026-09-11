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

from syncerapi.v1 import render_jinja, cc as CC, Host


str_replace = Rule.replace

# Chars a group name may keep when it becomes a Checkmk user id
REPLACE_EXCEPTIONS = ['-', '_']


# The LDAP search one rule describes. Rules describing the very same
# search share one connection and one query, so it is the key the lookup
# is grouped by — which is why it has to be hashable.
GroupSearch = namedtuple(
    'GroupSearch', 'account base_dn group_filter name_attribute attributes')


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
        for rule, group_names in rule_groups:
            search = group_search(rule.outcome, self.override_group_filter)
            if search.account and search not in directory:
                # The lookup failed and said so — creating the users now
                # would leave them without their directory data.
                continue
            groups = directory.get(search, {})
            for group_name in group_names:
                self.sync_user(rule, group_name, groups.get(group_name, {}))

    def group_names(self, rule, attribute_index):
        """
        The group names a single rule selects, each one only once.

        `rewrite_group_name` turns the value a host carries into the name
        the directory really knows — a prefix cut off, a domain dropped.
        A template that renders to nothing skips that value: an empty
        name would be searched as whatever the group filter alone
        matches, and the user of the first object found would be created
        under a name nobody asked for.
        """
        outcome = rule.outcome
        template = getattr(outcome, 'rewrite_group_name', '')
        group_names = []
        for item in foreach_attribute_items(attribute_index,
                                            outcome.foreach_type, outcome.foreach):
            item = str(item).strip()
            name = item
            if template:
                name = render_jinja(template,
                                    _ctx={'name': item, 'result': item}).strip()
            if not name:
                if self.debug and item:
                    print(f"INFO: '{item}' rewrote to nothing, no group searched")
                continue
            if name not in group_names:
                group_names.append(name)
        return group_names

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
        for rule, group_names in rule_groups:
            search = group_search(rule.outcome, self.override_group_filter)
            if not search.account:
                continue
            names = wanted.setdefault(search, [])
            for group_name in group_names:
                if group_name not in names:
                    names.append(group_name)

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

    def sync_user(self, rule, group_name, group):
        """
        Create the Checkmk user of one group, or update the one a former
        run created. A user someone made by hand is never touched.

        Every attribute of the LDAP group is a Jinja variable of the
        rule's templates; `name` is the group name and wins over an
        attribute of the same name.
        """
        outcome = rule.outcome
        context = dict(group)
        context['name'] = group_name
        context['result'] = group_name

        user_id = str_replace(render_jinja(outcome.rewrite_user_id or '', _ctx=context),
                              REPLACE_EXCEPTIONS).strip()
        if not user_id:
            return

        # pylint: disable=no-member
        user = CheckmkUserMngmt.objects(user_id=user_id).first()
        if user and not user.generated_by_rule:
            print(f"{CC.WARNING}  * {user_id}: exists and was created by hand, "
                  f"not touched{CC.ENDC}")
            return
        if not user:
            user = CheckmkUserMngmt(user_id=user_id,
                                    # Generated users are contacts, not logins.
                                    # A random secret keeps the entry valid
                                    # without anybody knowing a password.
                                    password=secrets.token_urlsafe(32))

        wanted = {
            'generated_by_rule': rule.name,
            'full_name': render_jinja(outcome.rewrite_full_name or '',
                                      _ctx=context).strip() or user_id,
            'roles': list(outcome.roles),
            'contact_groups': list(outcome.contact_groups),
            'disable_login': bool(outcome.disable_login),
        }
        # A template that renders to nothing — the group has no such
        # attribute — leaves the field as it is instead of emptying it.
        for field, template in (('email', outcome.rewrite_email),
                                ('pager_address', outcome.rewrite_pager_address)):
            if not template:
                continue
            if value := render_jinja(template, _ctx=context).strip():
                wanted[field] = value

        changed = [field for field, value in wanted.items()
                   if getattr(user, field, None) != value]
        if not changed:
            print(f"{CC.OKGREEN}  *{CC.ENDC} {user_id}: Nothing to do")
            return

        for field, value in wanted.items():
            setattr(user, field, value)
        user.save()
        print(f"{CC.OKGREEN}  *{CC.ENDC} {user_id}: Saved ({', '.join(changed)})")
