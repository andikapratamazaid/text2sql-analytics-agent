"""Each engine-level guardrail layer is tested WITHOUT the static validator, to prove defence in depth."""
import sqlite3
import unittest

from agent.db import QueryTimeout, SafeDB
from agent.guardrails import GuardrailError

from .helpers import DB_PATH


def count(table):
    c = sqlite3.connect(DB_PATH)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


class TestEngineLayers(unittest.TestCase):
    def setUp(self):
        self.db = SafeDB(DB_PATH, max_rows=500, timeout_s=10)

    def test_authorizer_blocks_writes_even_if_validator_is_bypassed(self):
        before = count("orders")
        for sql in ["DELETE FROM orders", "UPDATE orders SET order_status='x'", "DROP TABLE orders",
                    "INSERT INTO orders SELECT * FROM orders", "CREATE TABLE evil(x)"]:
            with self.subTest(sql):
                with self.assertRaises((GuardrailError, Exception)) as cm:
                    self.db._execute(sql)
                self.assertNotIsInstance(cm.exception, QueryTimeout)
        self.assertEqual(count("orders"), before)

    def test_authorizer_blocks_system_tables_and_unlisted_functions(self):
        with self.assertRaises(GuardrailError):
            self.db._execute("SELECT * FROM sqlite_master")
        with self.assertRaises(GuardrailError) as cm:
            self.db._execute("SELECT load_extension('x')")
        self.assertIn("load_extension", str(cm.exception))

    def test_authorizer_allows_normal_analytics(self):
        res = self.db._execute("WITH a AS (SELECT order_status s, COUNT(*) n FROM orders GROUP BY 1) "
                               "SELECT s, ROUND(100.0*n/SUM(n) OVER (), 2) FROM a")
        self.assertTrue(res.rows)

    def test_database_file_is_opened_read_only(self):
        conn = sqlite3.connect(self.db._uri(), uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE x(y)")
        conn.close()

    def test_row_cap_truncates(self):
        small = SafeDB(DB_PATH, max_rows=10)
        res = small.run("SELECT * FROM orders")
        self.assertEqual(len(res.rows), 10)
        self.assertTrue(res.truncated)
        full = small.run("SELECT * FROM orders LIMIT 5")
        self.assertFalse(full.truncated)

    def test_timeout_interrupts_runaway_query(self):
        quick = SafeDB(DB_PATH, timeout_s=0.5)
        with self.assertRaises(QueryTimeout):          # accidental 3-way cross join, billions of row combinations
            quick.run("SELECT COUNT(*) FROM order_items a, order_items b, order_items c")

    def test_recursive_ctes_are_not_allowed(self):
        with self.assertRaises(GuardrailError):
            self.db.run("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c")

    def test_schema_text_lists_tables_and_values(self):
        s = self.db.schema_text()
        self.assertIn("orders", s)
        self.assertIn("order_status", s)
        self.assertIn("delivered", s)          # low-cardinality values are surfaced
        self.assertNotIn("sqlite_", s)


if __name__ == "__main__":
    unittest.main()
