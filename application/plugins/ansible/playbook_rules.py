"""
Match-and-fire engine for AnsiblePlaybookFireRule.

Kept out of the inventory hot path (`AnsibleInventory.get_attributes`) so
that read-only `--list` calls never start playbook runs. Invoked via the
`ansible fire_playbook_rules` CLI command (registered as a cronjob).
"""
from application import logger
from application.models.host import Host
from application.modules.rule.rule import Rule

from .models import AnsiblePlaybookFireRule, AnsibleRunStats
from .runner import available_playbooks, run_playbook


class _PlaybookMatcher(Rule):
    """
    Rule subclass with no real outcome aggregation — its only job is to
    drive `check_rules()` and capture which (rule_id, outcomes) pairs
    matched for the current host. The actual firing happens in
    `fire_playbook_rules` below.
    """
    name = "Ansible Playbook Fire Match"

    def __init__(self):
        super().__init__()
        self._matched = []

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """Capture the outcomes of every rule that matched this host."""
        self._matched.append((str(rule['_id']), rule_outcomes))
        return outcomes


def _already_fired(rule_id: str, hostname: str, playbook: str) -> bool:
    """Has this exact (rule, host, playbook) already produced a run record?"""
    return AnsibleRunStats.objects(
        playbook=playbook,
        target_host=hostname,
        source='rule',
        triggered_by=f'rule:{rule_id}',
    ).first() is not None


def _fire(matched, hostname, available):
    """
    Dispatch the playbooks of the ``matched`` (rule_id, outcomes) pairs
    against ``hostname`` that have not fired for it yet, return how many.
    """
    fired = 0
    for rule_id, rule_outcomes in matched:
        for outcome in rule_outcomes:
            playbook = (outcome.get('playbook') or '').strip()
            if not playbook:
                continue
            if playbook not in available:
                logger.warning(
                    "Skipping fire-rule outcome: playbook %r not found",
                    playbook,
                )
                continue
            if _already_fired(rule_id, hostname, playbook):
                continue
            run_playbook(
                playbook,
                target_host=hostname,
                extra_vars=outcome.get('extra_vars') or None,
                provider=(outcome.get('inventory') or '').strip() or None,
                source='rule',
                triggered_by=f'rule:{rule_id}',
            )
            fired += 1
    return fired


def fire_playbook_rules(account=False):  # pylint: disable=unused-argument
    """
    Walk all hosts, evaluate enabled fire-rules, dispatch playbook runs
    for any (rule, host, playbook) that has not yet been recorded. A rule
    from a pasted list fires against the host each row names instead.

    Returns the number of runs dispatched. The `account` keyword exists
    only because `register_cronjob` invokes commands with `account=` when
    the cron entry has an account binding.
    """
    # pylint: disable=protected-access
    enabled = list(AnsiblePlaybookFireRule.objects(enabled=True).order_by('sort_field'))
    if not enabled:
        return 0

    available = set(available_playbooks())
    fired = 0

    for db_host in Host.get_export_hosts():
        matcher = _PlaybookMatcher()
        matcher.rules = enabled
        matcher.attributes = db_host.get_labels() or {}
        matcher.hostname = db_host.hostname
        matcher.db_host = db_host
        matcher.check_rules(db_host.hostname)
        fired += _fire(matcher._matched, db_host.hostname, available)

    matcher = _PlaybookMatcher()
    matcher.rules = enabled
    for row in matcher.list_rows():
        matched, matcher._matched = matcher._matched, []
        if not row.name:
            logger.warning("Fire-rule '%s', row %s skipped: it needs a "
                           "'hostname' or 'name' column", row.rule, row.row_idx + 1)
            continue
        fired += _fire(matched, row.name, available)
    for message in matcher.list_errors:
        logger.warning(message)

    return fired
