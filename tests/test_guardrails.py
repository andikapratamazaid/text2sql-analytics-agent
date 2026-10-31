import unittest

from agent.guardrails import GuardrailError, validate_sql

MUST_BLOCK = {
    "drop table": "DROP TABLE orders",
    "delete": "DELETE FROM orders",
    "update": "UPDATE orders SET order_status = 'delivered'",
    "insert": "INSERT INTO orders SELECT * FROM orders",
    "multi statement": "SELECT 1; DROP TABLE orders",
    "multi statement after comment": "SELECT 1 /* harmless */ ; DELETE FROM orders",
    "write hidden in CTE": "WITH x AS (SELECT 1) DELETE FROM orders",
    "pragma": "PRAGMA table_info(orders)",
    "attach": "ATTACH DATABASE '/tmp/x.db' AS x",
    "create": "CREATE TABLE t AS SELECT * FROM orders",
    "alter": "ALTER TABLE orders ADD COLUMN x TEXT",
    "vacuum": "VACUUM",
    "replace into": "WITH x AS (SELECT 1) REPLACE INTO orders SELECT * FROM orders",
    "load_extension": "SELECT load_extension('evil.so')",
    "begin": "BEGIN; SELECT 1",
    "empty": "   ",
    "line comment hiding keyword": "SELECT 1 -- ok\n; DROP TABLE orders",
    "not a select": "EXPLAIN SELECT 1",
}

MUST_ALLOW = {
    "simple": "SELECT COUNT(*) FROM orders",
    "trailing semicolon": "SELECT COUNT(*) FROM orders;",
    "cte": "WITH a AS (SELECT 1 AS x) SELECT x FROM a",
    "keyword inside string": "SELECT * FROM orders WHERE order_status = 'delete'",
    "keyword inside string 2": "SELECT 'DROP TABLE x; DELETE' AS s",
    "semicolon inside string": "SELECT 'a;b' AS s",
    "keyword in comment": "SELECT 1 /* update later */",
    "replace function": "SELECT REPLACE(order_status, 'a', 'b') FROM orders",
    "identifier that contains a keyword": "SELECT order_approved_at, product_photos_qty FROM orders, products LIMIT 1",
    "uppercase and newlines": "SELECT\n  COUNT(*)\nFROM\n  orders",
}


class TestValidator(unittest.TestCase):
    def test_blocks_dangerous_statements(self):
        for name, sql in MUST_BLOCK.items():
            with self.subTest(name):
                with self.assertRaises(GuardrailError):
                    validate_sql(sql)

    def test_allows_legitimate_queries(self):
        for name, sql in MUST_ALLOW.items():
            with self.subTest(name):
                out = validate_sql(sql)
                self.assertFalse(out.endswith(";"))

    def test_rejects_oversized_query(self):
        with self.assertRaises(GuardrailError):
            validate_sql("SELECT " + "1," * 5000 + "1")


if __name__ == "__main__":
    unittest.main()
