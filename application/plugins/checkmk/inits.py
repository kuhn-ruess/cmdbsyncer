"""
Inits for the Plugins
"""
from application import log
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes
from application.models.host import Host
from application.modules.rule.filter import Filter

from application.plugins.checkmk.tags import CheckmkTagSync
from application.plugins.checkmk.cmk_rules import CheckmkRuleSync
from application.plugins.checkmk.downtimes import CheckmkDowntimeSync
from application.plugins.checkmk.rules import CheckmkRulesetRule, DefaultRule
from application.plugins.checkmk.inventorize import InventorizeHosts
from application.plugins.checkmk.dcd import CheckmkDCDRuleSync
from application.plugins.checkmk.passwords import CheckmkPasswordSync
from application.plugins.checkmk.rule_passwords import (
    rewrite_explicit_passwords,
    preserve_password_macros,
    referenced_password_names,
)
from application.plugins.checkmk.groups import CheckmkGroupSync
from application.plugins.checkmk.users import CheckmkUserSync
from application.plugins.checkmk.bi import BI
from application.plugins.checkmk.sites import CheckmkSites
from application.plugins.checkmk.notification_rules import (
    CheckmkNotificationRuleSync,
    NotificationRuleAction,
)



from application.modules.rule.rewrite import Rewrite
from application.plugins.checkmk.helpers import project_allows_account
from application.models.project import Project
from application.plugins.checkmk.models import (
   CheckmkRuleMngmt,
   RuleMngmtOutcome,
   CheckmkBiRule,
   CheckmkBiAggregation,
   CheckmkDowntimeRule,
   CheckmkRewriteAttributeRule,
   CheckmkFilterRule,
   CheckmkDCDRule,
   CheckmkFolderPool,
   CheckmkSitePool,
   CheckmkNotificationRule,
)



def _load_rules():
    """
    Load needed extra Rules
    """
    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'checkmk_rewrite'
    attribute_rewrite.rules = \
                    CheckmkRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

    attribute_filter = Filter()
    attribute_filter.cache_name = "checkmk_filter"
    attribute_filter.rules = CheckmkFilterRule.objects(enabled=True).order_by('sort_field')

    return {
        'rewrite': attribute_rewrite,
        'filter': attribute_filter,
    }

#   .-- Export Tags
def export_tags(account, dry_run=False, save_requests=False, debug=False):
    """
    Export Tags to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkTagSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.dry_run = dry_run
        syncer.save_requests = save_requests
        syncer.name = 'Checkmk: Export Tags'
        syncer.source = "cmk_tag_sync"
        syncer.export_tags()
    except Exception as error_obj:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f'{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Tags to Account {account} not started",
                    source="cmk_tag_sync", details=[('error', str(error_obj))])

#.
#   .-- Export BI Rules
def export_bi_rules(account, debug):
    """
    Export BI Rules to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.debug = debug

        class ExportBiRule(DefaultRule):
            """
            Name overwrite
            """

        actions = ExportBiRule()
        actions.rules = CheckmkBiRule.objects(enabled=True)
        syncer.actions = actions
        syncer.name = 'Checkmk: Export BI Rules'
        syncer.source = "cmk_bi_sync"
        syncer.export_bi_rules()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export BI Rules to Account {account} not started",
                    source="cmk_bi_sync", details=[('error', str(error_obj))])
#.
#   .-- Export BI Aggregations
def export_bi_aggregations(account, debug):
    """
    Export BI Aggregations to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.debug = debug
        # Set name + source BEFORE the work runs so the atexit save_log
        # entry is identifiable even if the work raises.
        syncer.name = 'Checkmk: Export BI Aggregations'
        syncer.source = "cmk_bi_aggrigation_sync"
        class ExportBiAggr(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportBiAggr()
        actions.rules = CheckmkBiAggregation.objects(enabled=True)
        syncer.actions = actions
        syncer.export_bi_aggregations()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export BI Aggregations to Account {account} not started",
                    source="cmk_bi_aggrigation_sync",
                    details=[('error', str(error_obj))])

#.
#   .-- Inventorize Hosts


def inventorize_hosts(account, debug=False):
    """
    Inventorize information from Checkmk Installation
    """
    inven = None
    try:
        inven = InventorizeHosts(account)
        inven.debug = debug
        inven.run()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'{ColorCodes.FAIL} Error: {error_obj} {ColorCodes.ENDC}')
        if inven is not None:
            inven.record_exception(error_obj)
        else:
            log.log(f"Inventorize Hosts Account {account} not started",
                    source="checkmk_inventorize",
                    details=[('error', str(error_obj))])

#.
#   . -- Show missing hosts
def show_missing(account):
    """
    Return list of all currently missing hosts
    """
    cmk = CMK2(account)

    local_hosts = [x.hostname for x in Host.get_export_hosts()]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account}{ColorCodes.ENDC}")
    url = "domain-types/host_config/collections/all?effective_attributes=false"
    api_hosts = cmk.request(url, method="GET")
    for host in api_hosts[0]['value']:
        hostname = host['id']
        if hostname not in local_hosts:
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} {hostname}")

#.
#   . -- Bake and Sign Agents
def bake_and_sign_agents(account):
    """
    Bake and Sign Agents in Checkmk
    """
    from application.helpers.get_account import get_account_by_name  # pylint: disable=import-outside-toplevel
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        return False
    if "bakery_key_id" not in account_config and "bakery_passphrase" not in account_config:
        print(f"{ColorCodes.FAIL} Please set bakery_key_id and "\
              f"bakery_passphrase as Custom Account Config {ColorCodes.ENDC}")
        return False
    cmk = CMK2(account)
    url = "/domain-types/agent/actions/bake_and_sign/invoke"
    data = {
        'key_id': int(account_config['bakery_key_id']),
        'passphrase': account_config['bakery_passphrase'],
    }
    try:
        cmk.request(url, data=data, method="POST")
        print("Signed and Baked Agents")
        return True
    except CmkException as errors:
        print(errors)
        return False
#.
#   .-- Activate Changes
def activate_changes(account):
    """
    Activate Changes of Checkmk Instance
    """
    cmk = CMK2(account)

    # Get current activation etag
    url = "/domain-types/activation_run/collections/pending_changes"
    data, headers = cmk.request(url, "GET")
    etag = headers.get('ETag')

    # Nothing pending: activating would just return a 422 "no changes to
    # activate" which we would otherwise report as a failure below.
    if not data.get('value'):
        print("No changes to activate")
        return True

    if cmk.config.get('dont_activate_changes_if_more_then'):
        user = cmk.config['username']
        num_changes = len([x['user_id'] for x in data['value'] if x['user_id'] == user])
        if num_changes > int(cmk.config['dont_activate_changes_if_more_then']):
            print(f"{ColorCodes.FAIL}Too many changes to activate: {num_changes} > "\
                  f"{cmk.config['dont_activate_changes_if_more_then']}{ColorCodes.ENDC}")
            details = [('error', f'Too many changes to activate: {num_changes} > '\
                             f'{cmk.config["dont_activate_changes_if_more_then"]}')]
            log.log("Activate Changes aborted, too many changes",
                    source="Checkmk", details=details)
            return False

    update_headers = {
        'if-match': etag
    }

    # Trigger Activate Changes.
    # Default is fire and forget: Checkmk confirms that the activation was
    # started and we return right away. With the account option
    # 'wait_for_activate_changes' set, we ask for redirect=True instead, so
    # Checkmk sends a 303 to its 'wait-for-completion' endpoint which
    # requests follows until the activation is really done — only then can
    # a failure during the activation itself (e.g. missing permission for
    # foreign changes) be reported.
    wait_for_completion = bool(cmk.config.get('wait_for_activate_changes'))
    url = "/domain-types/activation_run/actions/activate-changes/invoke"
    data = {
        'redirect': wait_for_completion,
        'force_foreign_changes': True,
    }
    try:
        _, resp_header = cmk.request(url,
                    data=data,
                    method="POST",
                    additional_header=update_headers,
        )
        status_code = resp_header.get('status_code')
        if status_code not in (200, 204):
            # request() swallows a set of whitelisted API errors and just
            # returns the status code; surface those instead of pretending
            # the activation worked.
            error = resp_header.get('error', f'Checkmk returned HTTP {status_code}')
            print(f"{ColorCodes.FAIL}Activate Changes failed: {error}{ColorCodes.ENDC}")
            log.log("Checkmk Activate Changes failed",
                    source="Checkmk",
                    details=[('error', str(error))])
            return False
        if wait_for_completion:
            print(f"{ColorCodes.OKGREEN}Changes activated{ColorCodes.ENDC}")
        else:
            print(f"{ColorCodes.OKGREEN}Activation started{ColorCodes.ENDC}")
    except CmkException as errors:
        print(f"{ColorCodes.FAIL}Activate Changes failed: {errors}{ColorCodes.ENDC}")
        log.log("Checkmk Activate Changes failed",
                source="Checkmk",
                details=[('error', str(errors))])
        return False
    return True
#.
#   .-- Analyse Rule Optimization
def analyse_rules(account=None, min_hosts=10, top=20, apply=False,
                  debug=False):
    """
    Report which Setup Rules are built from a long list of host names,
    and which host label could replace that list.

    Reads the Syncer database only — nothing is sent to Checkmk, and the
    account is optional. Given one, the analysis sees exactly what that
    account would export (its project and folder scope, its object
    filter); without one it looks at every enabled rule.

    ``apply=True`` rewrites the Setup Rules whose host list a label
    covers exactly. Everything else is only reported.
    """
    rules = _load_rules()
    syncer = CheckmkRuleSync(account or False, probe_version=False)
    syncer.debug = debug
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']

    actions = CheckmkRulesetRule()
    actions.cache_name = f'CheckmkRulesetRule_{account}'
    rule_filter = {'enabled': True, 'static_rule__ne': True}
    if account:
        rule_filter['project__in'] = [None, ''] + projects_for_account(account)
    actions.rules = CheckmkRuleMngmt.objects(
        **rule_filter).order_by('sort_field')
    # Report which Setup Rule built a host-name condition, not just which
    # Checkmk rule came out of it — the fix belongs in the Setup Rule.
    actions.tag_source_rule = True
    syncer.actions = actions
    # Logged as what it is — nothing was exported. The object filter is
    # still the one configured for the export.
    syncer.name = 'Checkmk: Analyse Rules'
    syncer.settings_name = 'Checkmk: Export Rules'
    syncer.source = "cmk_rule_analysis"
    if not account:
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}No account given: "
              "reporting every enabled rule, without an account's project, "
              "folder or object scope")
    return syncer.analyse_rule_optimization(
        min_hosts=min_hosts, top=top, apply=apply)

#.
#   .-- Export Groups
def export_groups(account, test_run=False, debug=False):
    """
    Manage Groups in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkGroupSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.name = 'Checkmk: Export Groups'
        syncer.source = "cmk_group_sync"
        syncer.export_cmk_groups(test_run)
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Groups to Account {account} not started",
                    source="cmk_group_sync",
                    details=[('error', str(error_obj))])
#.
#   .-- Export Rules
def projects_for_account(account):
    """
    Names of the Projects whose rules may be exported to ``account``.

    Rules are steered by the project's ``rule_limit_by_accounts`` /
    ``rule_deny_by_accounts`` (each falling back to the host list when
    empty): a project applies when that allow list is empty (no
    restriction — exported everywhere) or explicitly lists this account,
    and the account is not on the applicable deny list (deny wins).
    """
    return [
        project.name for project in Project.objects()
        if project_allows_account(project, account, kind='rule')
    ]


def export_rules(account, debug=False):
    """
    Create Rules in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkRuleSync(account)
        syncer.debug = debug
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']

        actions = CheckmkRulesetRule()
        # The applied rule set depends on the account (each project's
        # ``limit_by_accounts`` filter), so the per-host outcome cache must
        # be account-scoped — with the class-level default key, whichever
        # account exports first would decide which project rules every
        # other account gets served from the cache.
        actions.cache_name = f'CheckmkRulesetRule_{account}'
        # Process rules in their configured ``sort_field`` order so the
        # resulting outcomes feed into ``rulsets_by_type`` already
        # ordered. The Checkmk-side reorder step (``sort_rules``) then
        # only needs to chain ``after_specific_rule`` moves to lock the
        # order into Checkmk's ruleset.
        # Static rules carry no host data — they are evaluated once
        # (see CheckmkRuleSync.calculate_static_rules) instead of per
        # host, so they are kept out of the per-host engine here.
        # Include global rules (no project) plus the rules of every project
        # whose account filter allows this account — a project restricts its
        # rules to its ``limit_by_accounts`` (empty = all accounts).
        allowed_projects = [None, ''] + projects_for_account(account)
        actions.rules = CheckmkRuleMngmt.objects(
            enabled=True, static_rule__ne=True,
            project__in=allowed_projects).order_by('sort_field')
        syncer.actions = actions
        syncer.static_rules = CheckmkRuleMngmt.objects(
            enabled=True, static_rule=True,
            project__in=allowed_projects).order_by('sort_field')
        syncer.name = 'Checkmk: Export Rules'
        syncer.source = "cmk_rule_sync"
        syncer.export_cmk_rules()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Rules to Account {account} not started",
                    source="cmk_rule_sync",
                    details=[('error', str(error_obj))])
#.
#   .-- Import Project Rules from Checkmk Folder
def import_project_rules_from_folder(project_name, account, folder,  # pylint: disable=too-many-locals
                                     recursive=False, debug=False):
    """
    Import every Checkmk Setup Rule that lives in ``folder`` on ``account``
    into ``project_name`` as static rules.

    Each Checkmk rule becomes a CheckmkRuleMngmt named
    ``cmkimport:{account}:{cmk_rule_id}`` so re-running the import updates the
    same rules instead of creating duplicates. Returns the number of imported
    rules.
    """
    syncer = None
    project = Project.objects(name=project_name).first()
    if not project:
        message = f"Project '{project_name}' not found"
        print(f'{ColorCodes.FAIL}{message}{ColorCodes.ENDC}')
        log.log(message, source="cmk_project_rule_import",
                details=[('error', message)])
        return 0

    try:
        syncer = CheckmkRuleSync(account)
        syncer.debug = debug
        found = syncer.fetch_rules_in_folder(folder, recursive=recursive)

        imported = 0
        password_hints = set()
        for entry in found:
            cmk_id = entry.get('cmk_id')
            if not cmk_id:
                continue
            name = f"cmkimport:{account}:{cmk_id}"
            rule = CheckmkRuleMngmt.objects(name=name).first() \
                or CheckmkRuleMngmt(name=name)
            rule.project = project_name
            rule.static_rule = True
            rule.enabled = True
            # Imported rules are host-independent — give them an explicit
            # "match anyway" condition type so rule lists and the engine don't
            # trip over an unset condition_typ.
            rule.condition_typ = 'anyway'
            rule.documentation = (
                f"Imported from Checkmk account '{account}', "
                f"folder '{folder}' (rule {cmk_id})")
            outcome = entry['outcome']
            # Checkmk masks explicit passwords as '******' on read, so a rule
            # imported here can't carry a usable secret. Rewrite each into a
            # syncer password-store reference (a cmk_password macro); on a
            # re-import keep the macro already on the rule so a renamed one is
            # not reverted to its default hint.
            new_value, hints = rewrite_explicit_passwords(
                outcome.get('value_template', ''))
            if hints:
                old_outcome = rule.outcomes[0] if rule.outcomes else None
                if old_outcome is not None:
                    new_value = preserve_password_macros(
                        old_outcome.value_template, new_value)
                outcome['value_template'] = new_value
                password_hints.update(referenced_password_names(new_value))
            rule.outcomes = [RuleMngmtOutcome(**outcome)]
            rule.primary_ruleset = outcome.get('ruleset', '')
            rule.save()
            imported += 1

        if password_hints:
            hint_list = ', '.join(sorted(password_hints))
            print(f"{ColorCodes.WARNING} * Rules reference password store "
                  f"entries: {hint_list}. Create matching Checkmk Passwords in "
                  f"the syncer and run 'checkmk export_passwords <account>' so "
                  f"the reference resolves in the target Checkmk.{ColorCodes.ENDC}")

        message = (f"Imported {imported} rule(s) from Checkmk folder "
                   f"'{folder}' into project '{project_name}'")
        print(f'{ColorCodes.OKGREEN}{message}{ColorCodes.ENDC}')
        details = [('account', account), ('folder', folder),
                   ('recursive', str(recursive)),
                   ('imported', str(imported))]
        if password_hints:
            details.append(('password_store_entries',
                            ', '.join(sorted(password_hints))))
        log.log(message, source="cmk_project_rule_import", details=details)
        return imported
    except CmkException as error_obj:
        # Record the failure, then re-raise so callers can surface it.
        # Swallowing it into "return 0" made a wrong-credentials error
        # (401) look identical to an empty folder in the web UI.
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Import Project Rules for '{project_name}' from Account "
                    f"{account} not started",
                    source="cmk_project_rule_import",
                    details=[('error', str(error_obj))])
        raise
#.
#   .-- Assign a CMDB Template to the hosts of a Checkmk folder
def assign_cmdb_template_from_folder(account, folder, template_name,  # pylint: disable=too-many-locals
                                     dry_run=False, debug=False):
    """
    Read every host directly in the Checkmk ``folder`` on ``account`` and
    assign the CMDB template ``template_name`` to the matching syncer hosts.

    Only hosts directly in ``folder`` are considered (no subfolders). The
    template is appended to each host's existing ``cmdb_templates``
    (deduplicated), so templates already on a host are kept. Hosts that are
    not present in the syncer are skipped. Aborts without touching any host
    when the template does not exist. Returns the number of hosts the template
    was newly assigned to.
    """
    template = Host.objects(hostname=template_name, object_type='template',
                            deleted_at__exists=False).first()
    if not template:
        message = f"CMDB template '{template_name}' not found"
        print(f'{ColorCodes.FAIL}{message}{ColorCodes.ENDC}')
        log.log(message, source="cmk_assign_template",
                details=[('error', message)])
        return 0

    syncer = None
    try:
        syncer = CMK2(account)
        syncer.debug = debug
        cmk_hosts = syncer.get_hosts_of_folder(folder, "")

        assigned = 0
        already = 0
        missing = 0
        for hostname in cmk_hosts:
            db_host = Host.objects(hostname=hostname).first()
            if not db_host:
                missing += 1
                if debug:
                    print(f"{ColorCodes.WARNING} - {hostname}: not in syncer"
                          f"{ColorCodes.ENDC}")
                continue
            existing = list(db_host.cmdb_templates or [])
            if template.id in {entry.id for entry in existing}:
                already += 1
                continue
            if not dry_run:
                db_host.cmdb_templates = existing + [template]
                # Templates feed into the cached host attributes, so drop the
                # object's cache to force a recompute on the next export.
                db_host.cache = {}
                db_host.save()
            assigned += 1
            print(f"{ColorCodes.OKGREEN} *{ColorCodes.ENDC} {hostname}: "
                  f"template '{template_name}' assigned")

        prefix = "[dry-run] " if dry_run else ""
        message = (f"{prefix}Assigned template '{template_name}' to {assigned} "
                   f"host(s) in Checkmk folder '{folder}' "
                   f"({already} already had it, {missing} not in syncer)")
        print(f'{ColorCodes.OKGREEN}{message}{ColorCodes.ENDC}')
        log.log(message, source="cmk_assign_template",
                details=[('account', account), ('folder', folder),
                         ('template', template_name), ('assigned', str(assigned)),
                         ('already', str(already)), ('missing', str(missing)),
                         ('dry_run', str(dry_run))])
        return assigned
    except CmkException as error_obj:
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Assign template '{template_name}' from Account {account} "
                    f"folder '{folder}' not started",
                    source="cmk_assign_template",
                    details=[('error', str(error_obj))])
        raise
#.
#   .-- Export Notification Rules
def export_notifications(account, debug=False):
    """
    Create / clean Notification Rules in Checkmk
    """
    syncer = None
    try:
        syncer = CheckmkNotificationRuleSync(account)
        syncer.debug = debug

        actions = NotificationRuleAction()
        actions.rules = CheckmkNotificationRule.objects(enabled=True).order_by('sort_field')
        syncer.actions = actions
        syncer.name = 'Checkmk: Export Notification Rules'
        syncer.source = "cmk_notification_rule_sync"
        syncer.export_notification_rules()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Notification Rules to Account {account} not started",
                    source="cmk_notification_rule_sync",
                    details=[('error', str(error_obj))])
#.
#   .-- Export Downtimes
def export_downtimes(account, debug=False, debug_rules=False):
    """
    Create Rules in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        class ExportDowntimes(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportDowntimes()
        actions.rules = CheckmkDowntimeRule.objects(enabled=True)

        if not debug_rules:
            syncer = CheckmkDowntimeSync(account)
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']

            syncer.actions = actions
            syncer.name = 'Checkmk: Export Downtimes'
            syncer.source = "cmk_downtime_sync"
            syncer.run()
        else:
            syncer = CheckmkDowntimeSync(False)
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.actions = actions
            syncer.debug_rules(debug_rules, "Checkmk")

    except Exception as error_obj:  # pylint: disable=broad-exception-caught
        # Catch every error, not just CmkException: the downtime export
        # talks to Checkmk's livestatus (e.g. reading current downtimes),
        # which can raise a plain requests timeout/connection error. With
        # the old CmkException-only catch those escaped uncaught, so the
        # run left only a detail-less "Checkmk: Export Downtimes" log entry
        # and `--debug` never surfaced the real cause.
        if debug:
            raise
        print(f'{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Downtimes to Account {account} not started",
                    source="cmk_downtime_sync",
                    details=[('error', str(error_obj))])
#.
#   . DCD Rules
def export_dcd_rules(account, debug=False, debug_rules=False):
    """
    Export DCD Rules to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        class ExportDCD(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportDCD(account)
        # Account-scoped cache key: the DCD rule set below is filtered by
        # each project's account filter, so cached outcomes are only valid
        # for the account they were computed for (see export_rules).
        actions.cache_name = f'CheckmkDCDRule_{account}'
        # Honour each project's account filter (limit_by_accounts): a DCD rule
        # assigned to a project is only exported to the accounts that project
        # allows. Rules without a project stay global (exported everywhere),
        # matching the Setup-rule export.
        allowed_projects = [None, ''] + projects_for_account(account)
        # Static rules carry no host data — they are rendered once (see
        # CheckmkDCDRuleSync.export_rules) instead of per host, so they are kept
        # out of the per-host engine here.
        actions.rules = CheckmkDCDRule.objects(
            enabled=True, static_rule__ne=True, project__in=allowed_projects)
        static_rules = CheckmkDCDRule.objects(
            enabled=True, static_rule=True, project__in=allowed_projects)

        if not debug_rules:
            syncer = CheckmkDCDRuleSync(account)
            syncer.debug = debug
            syncer.actions = actions
            syncer.static_rules = static_rules
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.name = 'Checkmk: Export DCD Rules'
            syncer.source = "cmk_dcd_rule_sync"
            syncer.export_rules()
        else:
            syncer = CheckmkDCDRuleSync(False)
            syncer.actions = actions
            syncer.static_rules = static_rules
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.debug_rules(debug_rules, "Checkmk")

    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export DCD Rules to Account {account} not started",
                    source="cmk_dcd_rule_sync",
                    details=[('error', str(error_obj))])
#.
#   . Passwords
def export_passwords(account):
    """
    Export Passwords to Checkmk
    """
    syncer = None
    try:
        syncer = CheckmkPasswordSync(account)
        syncer.export_passwords()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Passwords to Account {account} not started",
                    source="cmk_password_sync",
                    details=[('error', str(error_obj))])
#.
#   . Import Sites
def import_sites(account):
    """Import Checkmk sites of ``account`` into the local Object table."""
    syncer = None
    try:
        syncer = CheckmkSites(account)
        syncer.import_sites()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Import Sites from Account {account} not started",
                    source="cmk_site_sync",
                    details=[('error', str(error_obj))])
#   . Export Users
def export_users(account):
    """
    Export configured Users to Checkmk
    """
    syncer = None
    try:
        syncer = CheckmkUserSync(account)
        syncer.export_users()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Users to Account {account} not started",
                    source="cmk_user_sync",
                    details=[('error', str(error_obj))])
#.
#   . Sync Folder Pools
def sync_folderpools(_account=False, _debug=False):
    """Refresh ``folder_seats_taken`` on every CheckmkFolderPool from current host counts."""
    pool_usage = {}
    # Folder-pool counts only matter for hosts that ship to Checkmk —
    # anything not 'active' won't take a seat on the next sync.
    for host in Host.get_export_hosts():
        if host.folder:
            pool_usage.setdefault(host.folder, 0)
            pool_usage[host.folder] += 1

    for pool_folder, usage in pool_usage.items():
        folder = CheckmkFolderPool.objects(folder_name=pool_folder).first()
        if not folder:
            # Host sits in a regular (non-pool) folder — nothing to recount here.
            continue
        print(f"Folder {pool_folder} uses {usage} seats")
        if folder.folder_seats_taken != usage:
            print(f" - Changed seats from {folder.folder_seats_taken} to {usage}")
            folder.folder_seats_taken = usage
            folder.save()
        else:
            print(" - Is already up to date")

def reset_folderpool(pool):
    """
    Drop the assignment of a single Folder Pool, return the number of hosts.

    A host keeps its pool folder until it stops matching the rule, so changed
    pools or rules never reach the hosts already assigned. Every host sitting
    in this pool's folder loses the lock and its rule cache (the calculated
    folder is cached in there as well), the seat counter starts at zero.
    """
    hosts = Host.objects(folder=pool.folder_name)
    count = hosts.count()
    hosts.update(unset__folder=1, set__cache={})
    pool.folder_seats_taken = 0
    pool.save()
    return count

def reset_folderpools(_account=False, _debug=False):
    """Drop every Folder Pool assignment so the next export calculates it again."""
    for pool in CheckmkFolderPool.objects():
        print(f"Reset folder {pool.folder_name} ({reset_folderpool(pool)} hosts)")

    # Hosts locked to a folder whose pool is gone would keep their lock.
    leftovers = Host.objects(folder__ne=None)
    print(f"Clearing {leftovers.count()} locks to folders without a pool")
    leftovers.update(unset__folder=1, set__cache={})
#.
#   . Sync Site Pools
def sync_sitepools(_account=False, _debug=False):
    """Refresh ``hosts_taken`` on every CheckmkSitePool from current host counts."""
    site_usage = {}
    # Only hosts that ship to Checkmk take a site pool seat on the next sync.
    for host in Host.get_export_hosts():
        if host.pool_site:
            site_usage.setdefault(host.pool_site, 0)
            site_usage[host.pool_site] += 1

    for pool in CheckmkSitePool.objects():
        changed = False
        for member in pool.member_sites:
            usage = site_usage.get(member.site_id, 0)
            print(f"Site {member.site_id} (pool {pool.name}) uses {usage} seats")
            if member.hosts_taken != usage:
                print(f" - Changed seats from {member.hosts_taken} to {usage}")
                member.hosts_taken = usage
                changed = True
            else:
                print(" - Is already up to date")
        if changed:
            pool.save()

def reset_sitepool(pool):
    """
    Drop the assignment of a single Site Pool, return the number of hosts.

    The assignment is sticky: a host keeps its site until it stops matching
    the rule, so a changed pool never reaches the hosts already on it. Every
    host on one of this pool's sites loses the lock and its rule cache — the
    calculated ``site`` attribute lives in there too, so without that the
    next export would hand out the old site again.
    """
    hosts = Host.objects(pool_site__in=[x.site_id for x in pool.member_sites])
    count = hosts.count()
    hosts.update(unset__pool_site=1, set__cache={})
    for member in pool.member_sites:
        member.hosts_taken = 0
    pool.save()
    return count

def reset_sitepools(_account=False, _debug=False):
    """Drop every Site Pool assignment so the next export calculates it again."""
    for pool in CheckmkSitePool.objects():
        print(f"Reset pool {pool.name} ({reset_sitepool(pool)} hosts)")

    # Hosts on a site that no pool lists anymore would keep their lock.
    leftovers = Host.objects(pool_site__ne=None)
    print(f"Clearing {leftovers.count()} locks to sites without a pool")
    leftovers.update(unset__pool_site=1, set__cache={})

def pool_sticky_notes(db_host):
    """
    Debug-only notes about the sticky Folder/Site Pool assignments of a host.

    Both pool actions assign once and then keep their result until the host
    stops matching the rule — changed pool members or changed rules do not
    move an already assigned host. That is invisible in the outcomes, so the
    host debug spells it out, together with the way out.
    """
    notes = {}
    if folder := db_host.get_folder():
        notes['Folder Pool (sticky)'] = \
            f"Host is locked to the pool folder '{folder}' and keeps it as long " \
            "as it matches a Folder Pool rule, even if the pools changed. " \
            "Release it with './cmdbsyncer checkmk reset_folderpools'"
    if site := db_host.get_pool_site():
        notes['Site Pool (sticky)'] = \
            f"Host is locked to the site '{site}' and keeps it as long as it " \
            "matches a Site Pool rule, even if the pool changed. Release it " \
            "with the host action 'Redistribute Site Pool' or " \
            "'./cmdbsyncer checkmk reset_sitepools'"
    return notes
#.
