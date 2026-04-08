"""
Helpers for building restricted SQL queries from account configuration.
"""
import re


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)*$")

_WRITE_KEYWORDS_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|REPLACE|MERGE|CALL|INTO)\b',
    re.IGNORECASE
)
_COMMENT_RE = re.compile(r'(--[^\n]*|/\*.*?\*/)', re.DOTALL)


def validate_custom_query(query):
    """Ensure a custom SQL query is read-only (SELECT only)."""
    stripped = _COMMENT_RE.sub('', query).strip()
    if not re.match(r'^\s*SELECT\b', stripped, re.IGNORECASE):
        raise ValueError("custom_query must start with SELECT")
    if _WRITE_KEYWORDS_RE.search(stripped):
        raise ValueError("custom_query must not contain write or DDL statements")
    return query


def _validate_identifier(identifier):
    value = identifier.strip()
    if not value or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return value


def build_select_query(fields, table):
    safe_fields = ", ".join(_validate_identifier(field) for field in fields.split(','))
    safe_table = _validate_identifier(table)
    return f"SELECT {safe_fields} FROM {safe_table}"
