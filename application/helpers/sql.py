"""
Helpers for building restricted SQL queries from account configuration.
"""
import re


# Unicode-aware: real-world column names contain umlauts and other
# non-ASCII letters (e.g. ``EigentümerFirmaName``), and every SQL dialect
# we drive (MySQL, MSSQL/ODBC, PostgreSQL) accepts them. ``\w`` in Python 3
# already matches Unicode word chars, so we only need to forbid leading
# digits and keep ``$`` allowed for the engines that use it.
IDENTIFIER_RE = re.compile(r"^[^\W\d][\w$]*(\.[^\W\d][\w$]*)*$", re.UNICODE)

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

    Returns the comment-stripped statement, not the original — the
    keyword checks run on the stripped form, and MySQL executes
    conditional comments (``/*!50000 DROP TABLE x*/``) as real SQL, so
    returning the raw input would execute something the validation
    never saw.
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
        return stripped
    if not re.match(r'^\s*(SELECT|WITH)\b', stripped, re.IGNORECASE):
        raise ValueError("custom_query must start with SELECT or WITH")
    if _WRITE_KEYWORDS_RE.search(stripped):
        raise ValueError("custom_query must not contain write or DDL statements")
    return stripped


def custom_query_allow_ddl(config):
    """Shortcut for the opt-in flag on an account's config dict."""
    return _truthy(config.get('allow_ddl'))


def _validate_identifier(identifier):
    value = identifier.strip()
    if not value or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return value


def _validate_table_expression(table):
    """
    Validate the ``table`` value of an account config.

    Accepts either a bare identifier (the common case) or an identifier
    followed by additional FROM-clause SQL — typically a WHERE filter
    that some installations have historically baked into the table
    field. The extra SQL must not contain statement separators, SQL
    comments or destructive / data-mutating keywords, so the relaxed
    form cannot be used to smuggle DROP/TRUNCATE/UPDATE/INSERT/… into
    the executed statement.
    """
    value = table.strip()
    if not value:
        raise ValueError(f"Unsafe SQL identifier: {table}")
    if IDENTIFIER_RE.fullmatch(value):
        return value
    # Extended form: ``<identifier> <free SQL>``. Split off the leading
    # identifier (table / view name) and audit the remainder.
    head_match = re.match(r"^([^\W\d][\w$]*(?:\.[^\W\d][\w$]*)*)\s+(.+)$",
                          value, re.UNICODE | re.DOTALL)
    if not head_match:
        raise ValueError(f"Unsafe SQL identifier: {table}")
    tail = head_match.group(2)
    if ';' in tail or _COMMENT_RE.search(tail):
        raise ValueError(f"Unsafe SQL identifier: {table}")
    if _DESTRUCTIVE_KEYWORDS_RE.search(tail):
        raise ValueError(f"Unsafe SQL identifier: {table}")
    return value


def build_select_query(fields, table):
    """Build a SELECT query from validated identifiers only.

    ``fields`` is always a strict comma-separated identifier list.
    ``table`` is a bare identifier in the normal case, but may carry an
    appended ``WHERE …`` filter as long as it passes the destructive-
    keyword / no-semicolon / no-comment audit in
    :func:`_validate_table_expression`.
    """
    safe_fields = ", ".join(_validate_identifier(field) for field in fields.split(','))
    safe_table = _validate_table_expression(table)
    return f"SELECT {safe_fields} FROM {safe_table}"
