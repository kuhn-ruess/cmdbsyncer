"""Tests for application.helpers.sql."""
# pylint: disable=missing-function-docstring
import unittest

from application.helpers.sql import (
    build_select_query,
    custom_query_allow_ddl,
    validate_custom_query,
)


class TestValidateCustomQueryReadOnly(unittest.TestCase):
    """Default read-only contract (allow_ddl=False)."""

    def test_select_passes(self):
        q = "SELECT host FROM hosts"
        self.assertEqual(validate_custom_query(q), q)

    def test_cte_passes(self):
        q = "WITH h AS (SELECT 1) SELECT * FROM h"
        self.assertEqual(validate_custom_query(q), q)

    def test_rejects_insert(self):
        with self.assertRaises(ValueError):
            validate_custom_query("INSERT INTO hosts VALUES (1)")

    def test_rejects_create(self):
        with self.assertRaises(ValueError):
            validate_custom_query(
                "CREATE TABLE hosts (id INT); SELECT * FROM hosts"
            )

    def test_rejects_embedded_update(self):
        with self.assertRaises(ValueError):
            validate_custom_query("SELECT 1; UPDATE hosts SET a=1")


class TestValidateCustomQueryAllowDdl(unittest.TestCase):
    """Opt-in DDL contract (allow_ddl=True)."""

    def test_create_then_select_passes(self):
        q = (
            "CREATE TABLE IF NOT EXISTS hosts (host VARCHAR(255)); "
            "SELECT host FROM hosts"
        )
        self.assertEqual(validate_custom_query(q, allow_ddl=True), q)

    def test_mssql_guarded_create_then_select_passes(self):
        q = (
            "IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='hosts') "
            "BEGIN CREATE TABLE hosts (host VARCHAR(255)) END; "
            "SELECT host FROM hosts"
        )
        self.assertEqual(validate_custom_query(q, allow_ddl=True), q)

    def test_plain_select_still_passes(self):
        q = "SELECT host FROM hosts"
        self.assertEqual(validate_custom_query(q, allow_ddl=True), q)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_custom_query("   ", allow_ddl=True)

    def test_rejects_without_select(self):
        with self.assertRaises(ValueError):
            validate_custom_query(
                "CREATE TABLE hosts (id INT)", allow_ddl=True,
            )

    def test_rejects_drop_even_when_allowed(self):
        with self.assertRaises(ValueError):
            validate_custom_query(
                "DROP TABLE legacy; CREATE TABLE hosts (id INT); SELECT * FROM hosts",
                allow_ddl=True,
            )

    def test_rejects_truncate_even_when_allowed(self):
        with self.assertRaises(ValueError):
            validate_custom_query(
                "TRUNCATE TABLE legacy; SELECT * FROM hosts",
                allow_ddl=True,
            )

    def test_rejects_insert_even_when_allowed(self):
        with self.assertRaises(ValueError):
            validate_custom_query(
                "INSERT INTO hosts VALUES (1); SELECT * FROM hosts",
                allow_ddl=True,
            )


class TestCustomQueryAllowDdl(unittest.TestCase):
    """Opt-in flag parser."""

    def test_truthy_variants(self):
        for v in ("yes", "YES", "True", "1", "on"):
            self.assertTrue(custom_query_allow_ddl({"allow_ddl": v}), v)

    def test_falsy_variants(self):
        for v in ("", "no", "false", "0", None):
            self.assertFalse(custom_query_allow_ddl({"allow_ddl": v}), v)

    def test_missing(self):
        self.assertFalse(custom_query_allow_ddl({}))


class TestBuildSelectQuery(unittest.TestCase):
    """Unchanged SELECT-builder behaviour."""

    def test_simple(self):
        self.assertEqual(
            build_select_query("host,ip", "hosts"),
            "SELECT host, ip FROM hosts",
        )

    def test_rejects_injection_in_table(self):
        with self.assertRaises(ValueError):
            build_select_query("host", "hosts; DROP TABLE x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
