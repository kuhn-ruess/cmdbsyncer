"""
Helpers for building restricted SQL queries from account configuration.
"""
import re


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)*$")

_WRITE_KEYWORDS_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|'
    r'GRANT|REVOKE|REPLACE|MERGE|CALL|INTO)\b',
    re.IGNORECASE
)
# Even when the admin opts into DDL on custom_query we keep refusing
# these — they drop, truncate or silently mutate existing rows. A
# bootstrap query that creates a table on first run should never need
# them; if it does, the workflow belongs outside the syncer.
_DESTRUCTIVE_KEYWORDS_RE = re.compile(
    r'\b(DROP|TRUNCATE|DELETE|UPDATE|EXEC|EXECUTE|GRANT|REVOKE|REPLACE|MERGE|INSERT)\b',
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r'(--[^\n]*|/\*.*?\*/)', re.DOTALL)


def _truthy(value):
    return str(value or '').strip().lower() in ('yes', 'true', '1', 'on')


def validate_custom_query(query, allow_ddl=False):
    """
    Validate a custom SQL query taken from account config.

    Default (``allow_ddl=False``): read-only — must start with SELECT or
    WITH, and must not contain any write/DDL keywords. This is the
    hardened behaviour admins get out of the box.

    Opt-in (``allow_ddl=True``): the admin has explicitly enabled DDL on
    the account. Statements like ``CREATE TABLE IF NOT EXISTS ...;
    SELECT ... FROM ...`` are accepted so the same query can bootstrap
    the target table before the import reads from it. Destructive /
    data-mutating keywords (DROP, TRUNCATE, DELETE, UPDATE, INSERT,
    EXEC, GRANT, REVOKE, REPLACE, MERGE) stay blocked so a typo can't
    wipe the schema, and the statement must still contain a SELECT so
    the importer has rows to iterate.
    """
    stripped = _COMMENT_RE.sub('', query).strip()
    if allow_ddl:
        if not stripped:
            raise ValueError("custom_query is empty")
        if _DESTRUCTIVE_KEYWORDS_RE.search(stripped):
            raise ValueError(
                "custom_query must not contain destructive or data-mutating keywords"
            )
        if not re.search(r'\bSELECT\b', stripped, re.IGNORECASE):
            raise ValueError(
                "custom_query must include a SELECT the importer can read from"
            )
        return query
    if not re.match(r'^\s*(SELECT|WITH)\b', stripped, re.IGNORECASE):
        raise ValueError("custom_query must start with SELECT or WITH")
    if _WRITE_KEYWORDS_RE.search(stripped):
        raise ValueError("custom_query must not contain write or DDL statements")
    return query


def custom_query_allow_ddl(config):
    """Shortcut for the opt-in flag on an account's config dict."""
    return _truthy(config.get('allow_ddl'))


def _validate_identifier(identifier):
    value = identifier.strip()
    if not value or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return value


def build_select_query(fields, table):
    """Build a SELECT query from validated identifiers only."""
    safe_fields = ", ".join(_validate_identifier(field) for field in fields.split(','))
    safe_table = _validate_identifier(table)
    return f"SELECT {safe_fields} FROM {safe_table}"
