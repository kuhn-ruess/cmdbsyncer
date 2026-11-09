"""
Checkmk DCD Manager
"""
# pylint: disable=duplicate-code
from jinja2.exceptions import UndefinedError
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.plugins.checkmk.cmk_rules import HOST_FOLDER
from application.plugins.checkmk.rules import host_folder_engine, host_site

from application import logger
from application.modules.rule.list_source import (
    is_list_rule,
    parse_rule_list,
    row_context,
)

from syncerapi.v1 import Host, render_jinja


# Jinja variable of a DCD rule: the site the host export gives the host,
# else the account's site (see add_host_context).
HOST_SITE = 'HOST_SITE'


class CheckmkDCDRuleSync(CMK2):
    """
    Sync Checkmk Downtimes
    """
    console = None

    # Host-independent DCD rules, rendered once instead of per host. Injected
    # by inits.export_dcd_rules; defaults to empty so other callers still work.
    static_rules = []

    def __init__(self, account=False):
        super().__init__(account)
        # Per-instance run state. Class-level defaults would accumulate
        # across accounts/runs in the same process and leak stale rules
        # into later exports.
        self.all_rules = []
        # Folder rules engine for HOST_FOLDER, built on first use.
        self._host_folder_engine = None
        # Site ids of the target Checkmk, see known_sites.
        self._known_sites = None

    # Account config keys withheld from the rule template context — secrets and
    # internal ids that must never end up in a rendered rule.
    _ACCOUNT_HIDDEN_KEYS = frozenset({
        'password', 'bakery_passphrase', 'ca_cert_chain', 'ca_root_cert',
        '_id', 'id', 'ref',
    })

    def _account_site(self):
        """
        Checkmk site name of the exporting account — the last path segment of
        its address (which ends in ``/<site>``). Exposed to DCD rules as
        ``{{ cmk_site }}`` so one rule can target the correct site on each
        Checkmk (e.g. a test and a prod instance with different site names).
        """
        address = (self.config.get('address') or '').rstrip('/')
        return address.rsplit('/', 1)[-1] if '/' in address else ''

    def _account_context(self):
        """
        The exporting account's attributes exposed to DCD rules as
        ``{{ account.<field> }}`` — its standard fields plus any per-account
        custom field (flattened into the account config). Lets one rule use a
        value configured per account (test vs prod). Secrets are withheld.
        """
        return {key: value for key, value in (self.config or {}).items()
                if key not in self._ACCOUNT_HIDDEN_KEYS}

    def build_timeranges(self, rule):
        """
        Return Timestamp ListField
        "exclude_time_ranges": [
          {
            "start": "11:00",
            "end": "13:00"
          }
        ],
        """
        timeranges = []
        for tr in rule['exclude_time_ranges']:
            timeranges.append({
                'start': f"{tr['start_hour']}:{tr['start_minute']:02d}",
                'end': f"{tr['end_hour']}:{tr['end_minute']:02d}",
            })
        return timeranges


    def build_creation_rules(self, rule, attributes):
        """
        Return Creation Rules Field
        "creation_rules": [
          {
            "folder_path": "/",
            "host_attributes": {
              "tag_snmp_ds": "no-snmp",
              "tag_agent": "no-agent",
              "tag_piggyback": "piggyback",
              "tag_address_family": "no-ip"
            },
            "delete_hosts": false,
             "host_filters": [
                  "lx1"
                ] }
        ],
        """
        creation_rules = []
        for crule in rule['creation_rules']:
            rule_payload = {
                'folder_path': render_jinja(crule['folder_path'], **attributes),
                'delete_hosts': crule['delete_hosts'],
                'host_attributes': dict({x['attribute_name']:x['attribute_value'] \
                                            for x in crule['host_attributes']})
            }
            if crule['host_filters']:
                rule_payload['host_filters'] =  crule['host_filters']
            creation_rules.append(rule_payload)
        return creation_rules



    def build_rule_payload(self, rule, attributes):
        """
        Return Payload as Dict
        """
        try:
            # A line rendering empty (an attribute the host lacks) is left out.
            restricted_hosts = [
                host for host in (render_jinja(entry, mode='raise', **attributes).strip()
                                  for entry in rule['restricted_source_hosts'])
                if host]
            creation_rules = self.build_creation_rules(rule, attributes)
            exclude_time_ranges = self.build_timeranges(rule)


            # Checkmk's DCD REST API nests the connector settings under a
            # "connector" object (all three supported versions). Checkmk 2.4
            # dropped the "activate_changes_interval" and "exclude_time_ranges"
            # connector fields — only 2.3 and older still accept them.
            connector = {
                  "connector_type": render_jinja(rule['connector_type'], mode='raise',**attributes),
                  "restrict_source_hosts": restricted_hosts,
                  "interval": render_jinja(rule['interval'], mode='raise', **attributes),
                  "creation_rules": creation_rules,
                  "discover_on_creation": rule['discover_on_creation'],
                  "no_deletion_time_after_init": render_jinja(rule['no_deletion_time_after_init'],\
                                                                                    **attributes),
                  "max_cache_age": render_jinja(rule['max_cache_age'], **attributes),
                  "validity_period": render_jinja(rule['validity_period'], **attributes),
            }
            if not self.version_at_least(2, 4):
                connector["activate_changes_interval"] = \
                        render_jinja(rule['activate_changes_interval'], **attributes)
                connector["exclude_time_ranges"] = exclude_time_ranges

            payload =  {
                  "dcd_id": render_jinja(rule['dcd_id'], mode='raise', **attributes),
                  "title": render_jinja(rule['title'], mode='raise', **attributes),
                  "comment": render_jinja(rule['comment'], mode='raise',**attributes),
                  "disabled": rule['disabled'],
                  "site": render_jinja(rule['site'], mode='raise',**attributes),
                  "connector": connector,
            }
            if rule['documentation_url']:
                payload['documentation_url']= rule['documentation_url']
            logger.debug(payload)
            return payload
        except UndefinedError:
            if self.debug:
                raise
            return {}

    def create_rule_in_cmk(self, payload):
        """
        Create not existing rule in checkmk
        """
        self.console(f" * Create Rule {payload['dcd_id']}")
        url = "/domain-types/dcd/collections/all"
        self.request(url, method="POST", data=payload)

    def calculate_rules_of_host(self, hostname, outcomes, attributes):
        """
        Calculate rules for Host
        """
        self.console(f" * Calculate {hostname}")
        for _, rules in outcomes.items():
            for rule  in rules:
                rule_payload = self.build_rule_payload(rule, attributes)
                logger.debug('\nGot Payload: %s', rule_payload)

                # A connection without ID is no connection (a row of a list
                # with an empty cell, for example).
                if rule_payload and rule_payload.get('dcd_id') and \
                        rule_payload not in self.all_rules:
                    self.all_rules.append(rule_payload)

    def calculate_static_rules(self, context):
        """
        Static rules carry no host data: render each once against
        ``context`` (site and account) instead of per host. Their match
        conditions are ignored, a static rule is always emitted. A rule
        rendered from its list is rendered once per row instead, with the
        row's columns added to ``context``.
        """
        for rule in self.static_rules:
            host_actions = {'dcd': [dict(outcome.to_mongo())
                                    for outcome in rule.outcomes]}
            if not is_list_rule(rule):
                self.calculate_rules_of_host(f"static:{rule.name}",
                                             host_actions, context)
                continue
            parsed = parse_rule_list(rule)
            if parsed.errors:
                self.log_error(
                    f"List rule '{rule.name}' skipped, its list is not valid: "
                    f"{'; '.join(parsed.errors)}")
                continue
            for row_idx, row in enumerate(parsed.rows):
                self.calculate_rules_of_host(
                    f"list:{rule.name}:{row_idx}", host_actions,
                    {**context, **row_context(row, row_idx)})

    def add_host_context(self, db_host, host_actions, attributes):
        """
        Add HOST_FOLDER, the folder the host export puts the host in, and
        HOST_SITE, the site it gives the host (else the account's), to
        ``attributes`` when one of the host's outcomes uses them. Only then
        the export rules run for the host, the other hosts cost nothing.
        """
        used = str(host_actions)
        wants_folder = HOST_FOLDER in used
        wants_site = HOST_SITE in used
        if not wants_folder and not wants_site:
            return
        if self._host_folder_engine is None:
            self._host_folder_engine = host_folder_engine()
        outcomes = self._host_folder_engine.get_outcomes(
            db_host, attributes, persist_cache=False, use_cache=False)
        if wants_folder:
            attributes[HOST_FOLDER] = outcomes.get('move_folder') or '/'
        if wants_site:
            attributes[HOST_SITE] = host_site(outcomes, attributes) or \
                attributes.get('cmk_site', '')

    def export_rules(self):
        """
        Export DCD Rules
        """

        # Exposed to every DCD rule: {{ cmk_site }} = the account's Checkmk site,
        # and {{ account.<field> }} = any (non-secret) account attribute, so one
        # rule can use values configured per account (test vs prod).
        site = self._account_site()
        account_ctx = self._account_context()
        db_objects = Host.active_non_template()
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Calculate Rules", total=total)
            object_filter = self.config['settings'].get(self.name, {}).get('filter')
            db_objects = Host.objects_by_filter(object_filter)
            for db_host in db_objects:
                logger.debug('Started with %s', db_host.hostname)
                attributes = self.get_attributes(db_host, 'checkmk')
                if not attributes:
                    logger.debug(' -- Skiped no attributes')
                    progress.advance(task1)
                    continue
                attributes['all']['cmk_site'] = site
                attributes['all']['account'] = account_ctx
                # The site the site pool gave the host in the host export.
                attributes['all']['HOST_POOL_SITE'] = db_host.get_pool_site() or ''
                # pylint: disable-next=no-member
                host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                if host_actions:
                    logger.debug(' -- Got Actions')
                    self.add_host_context(db_host, host_actions, attributes['all'])
                    self.calculate_rules_of_host(db_host.hostname, host_actions, attributes['all'])
                progress.advance(task1)

            # No host: HOST_SITE is the account's site, there is no pool.
            self.calculate_static_rules({'cmk_site': site, 'account': account_ctx,
                                         HOST_SITE: site, 'HOST_POOL_SITE': ''})

            task2 = progress.add_task("Send Rules to Checkmk", total=len(self.all_rules))
            self.send_rules(lambda: progress.advance(task2))

    def send_rules(self, advance):
        """
        Create the collected connections Checkmk does not have yet, and
        replace those whose site, title, comment, disabled state or
        restricted source hosts differ.
        ``advance`` is called once per connection.
        """
        count_new = 0
        count_existing = 0
        count_replaced = 0
        sent = {}
        for rule in self.all_rules:
            # Hosts rendering one DCD ID differently would replace the
            # connection back and forth: the first rendering wins.
            if rule['dcd_id'] in sent:
                if sent[rule['dcd_id']] is not None:
                    self.log_error(
                        f"DCD connection {rule['dcd_id']} renders differently "
                        "for several hosts, the first one is used. Put what "
                        "differs (site, host) into the DCD ID.")
                    sent[rule['dcd_id']] = None
                advance()
                continue
            sent[rule['dcd_id']] = rule
            existing = self.get_rule(rule['dcd_id'])
            changed = changed_fields(rule, existing) if existing else []
            if existing and not changed:
                count_existing += 1
                advance()
                continue
            if changed and rule['site'] not in self.known_sites():
                # Deleting first would leave no connection at all: Checkmk
                # refuses to create one on a site it does not know.
                self.log_error(
                    f"DCD connection {rule['dcd_id']} kept as it is: the rule "
                    f"wants site '{rule['site']}', Checkmk has no such site")
                count_existing += 1
                advance()
                continue
            # One connection Checkmk refuses must not keep the others
            # from being created.
            try:
                if changed:
                    # Checkmk can not update a connection, only delete it.
                    # Its hosts stay, only the connection is replaced.
                    self.console(f" * Replace Rule {rule['dcd_id']}, changed: "
                                 f"{', '.join(changed)}")
                    self.request(f"/objects/dcd/{rule['dcd_id']}", method="DELETE")
                    self.log_details.append(
                        ('INFO', f"Replaced DCD connection {rule['dcd_id']}, "
                                 f"changed: {', '.join(changed)}"))
                    count_replaced += 1
                self.create_rule_in_cmk(rule)
                count_new += 0 if changed else 1
            except CmkException as error:
                if self.debug:
                    raise
                self.log_error(
                    f"DCD connection {rule['dcd_id']} not created: {error}")
            advance()

        self.log_details.append(('new_rules', count_new))
        self.log_details.append(('replaced_rules', count_replaced))
        self.log_details.append(('existing_rules', count_existing))

    def known_sites(self):
        """
        Ids of the sites Checkmk knows, read once per run. Empty when the
        list can not be read, then no connection is replaced.
        """
        if self._known_sites is None:
            try:
                response = self.request(
                    "domain-types/site_connection/collections/all",
                    method="GET")[0]
                self._known_sites = {site.get('id') for site
                                     in response.get('value', [])}
            except CmkException as error:
                self.log_error(f"Could not read the sites from Checkmk: {error}")
                self._known_sites = set()
        return self._known_sites

    def get_rule(self, rule_id):
        """
        The connection ``rule_id`` as Checkmk has it (title, site, connector
        and so on), or None when there is none.
        """
        response = self.request(f"/objects/dcd/{rule_id}", method="GET")[0]
        if not response:
            return None
        return response.get('extensions') or {}


# Fields of a DCD connection the export keeps in line with the rule. The
# rest of the connector is left out: Checkmk returns it in another shape
# than it takes it (types, key names, defaults), comparing it would replace
# the connection on every run.
COMPARED_FIELDS = ('site', 'title', 'comment', 'disabled')


def changed_fields(rule, existing):
    """
    The fields of ``COMPARED_FIELDS`` and the restricted source hosts in
    which the connection Checkmk has differs from the one the rule renders.
    """
    changed = [field for field in COMPARED_FIELDS
               if str(rule.get(field) or '') != str(existing.get(field) or '')]
    # Checkmk leaves the key out when the list is empty.
    ours = (rule.get('connector') or {}).get('restrict_source_hosts') or []
    theirs = (existing.get('connector') or {}).get('restrict_source_hosts') or []
    if sorted(ours) != sorted(theirs):
        changed.append('restrict_source_hosts')
    return changed
