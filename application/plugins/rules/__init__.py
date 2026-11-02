"""
Rule Manger
"""
import click
from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .rule_import_export import import_rules, export_rules, export_all_rules
from .autorules import create_rules
from .git_staging import (
    GitStagingError,
    format_pull_result,
    pull_rules,
    push_rules,
    repo_config,
    split_rule_types,
)

cli_rules = register_cli_group(app, 'rules', 'rules', "Syner Rules import and Export")

@cli_rules.command('export_rules')
@click.argument("rule_type", default="")
def cli_export_rules(rule_type):
    """
    Export Rules by Category
    """
    export_rules(rule_type)

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
@click.option("--override", is_flag=True, default=False,
              help="Replace rules which already exist instead of "
                   "skipping them.")
@click.option("--debug", default=False, is_flag=True)
def cli_import_rules(rulefile_path, override, debug):# pylint: disable=unused-argument
    """
    Import Rules into the CMDB Syncer
    """
    import_rules(rulefile_path, override=override)

@cli_rules.command('export_all_rules')
@click.argument("target_path", default="")
@click.option("--include-hosts", is_flag=True, default=False,
              help="Also export hosts/objects from the Host collection "
                   "(skipped by default).")
@click.option("--include-accounts", is_flag=True, default=False,
              help="Also export accounts (skipped by default).")
@click.option("--include-users", is_flag=True, default=False,
              help="Also export user accounts including hashed passwords "
                   "and roles (skipped by default — treat the output as secret).")
@click.option("--include-passwords", is_flag=True, default=False,
              help="Also export the Secret Store (skipped by default; "
                   "the entries are encrypted with this instance's key, "
                   "treat the output as secret).")
@click.option("--zip", "as_zip", is_flag=True, default=False,
              help="Write the export compressed into a zip archive, "
                   "import_rules reads it as it is.")
@click.option("--debug", default=False, is_flag=True)
def cli_export_all_rules(target_path, include_hosts, include_accounts,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                         include_users, include_passwords, as_zip,
                         debug):  # pylint: disable=unused-argument
    """
    Export all Rules of every type into a single file.
    If no path is given, a timestamped filename is generated.
    """
    export_all_rules(
        target_path or None,
        include_hosts=include_hosts,
        include_accounts=include_accounts,
        include_users=include_users,
        include_passwords=include_passwords,
        as_zip=as_zip,
    )

@cli_rules.command('create_rules')
@click.option("--debug", default=False, is_flag=True)
def cli_create_rules(debug):
    """
    Create Syncer Rules based on Config
    """
    create_rules(None, debug)

register_cronjob('Syncer: Autocreate Rules', create_rules)


@cli_rules.command('git_push')
@click.argument("account")
@click.option("--type", "rule_types", multiple=True, required=True,
              help="Rule type to push, repeat for several types.")
@click.option("--message", default="", help="Commit message.")
@click.option("--debug", default=False, is_flag=True)
def cli_git_push(account, rule_types, message, debug):
    """
    Push the rules of the given types into the Git repository of ACCOUNT
    """
    try:
        result = push_rules(account, rule_types, message)
    except GitStagingError as error:
        if debug:
            raise
        raise click.ClickException(str(error)) from error
    if not result['commit']:
        print("Nothing changed, no commit created")
        return
    print(f"Pushed commit {result['commit']}")
    for name in result['changed']:
        print(f"  {name}")


@cli_rules.command('git_pull')
@click.argument("account")
@click.option("--type", "rule_types", multiple=True,
              help="Rule type to pull, repeat for several types. "
                   "Without it every type in the repository is pulled.")
@click.option("--delete-missing", is_flag=True, default=False,
              help="Delete rules of a pulled type which are not in the repository.")
@click.option("--debug", default=False, is_flag=True)
def cli_git_pull(account, rule_types, delete_missing, debug):
    """
    Load the rules from the Git repository of ACCOUNT
    """
    try:
        result = pull_rules(account, rule_types, delete_missing)
    except GitStagingError as error:
        if debug:
            raise
        raise click.ClickException(str(error)) from error
    for line in format_pull_result(result):
        print(line)


def git_pull_cronjob(account=None):
    """
    Pull the rules from the Git repository of the account, with the rule
    types and the delete setting configured in the account
    """
    if not account:
        raise GitStagingError("The job needs an account of type Git Repository")
    config = repo_config(account)
    result = pull_rules(account, split_rule_types(config['rule_types']),
                        config['delete_missing'])
    errors = [rule_type for rule_type, entry in result['types'].items()
              if entry.get('error')]
    if errors:
        raise GitStagingError(f"Pull failed for: {', '.join(errors)}")

register_cronjob('Syncer: Pull Rules from Git', git_pull_cronjob)
