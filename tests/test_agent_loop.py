import os
import sqlite3
import unittest

from agent.agent import Agent
from agent.config import Config
from agent.mock_llm import ScriptedLLM

from .helpers import DB_PATH, tmp_dir

T, X = ScriptedLLM.tool, ScriptedLLM.text


def make_agent(script, **cfg):
    config = Config(db_path=DB_PATH, charts_dir=tmp_dir(), log_path="", **cfg)
    return Agent(config, ScriptedLLM(script))


def orders_count():
    c = sqlite3.connect(DB_PATH)
    try:
        return c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    finally:
        c.close()


class TestAgentLoop(unittest.TestCase):
    def test_happy_path(self):
        a = make_agent([T("run_sql", {"query": "SELECT COUNT(*) FROM orders"}), X("There are many orders.")])
        r = a.ask("How many orders?")
        self.assertEqual(r.stopped_reason, "final")
        self.assertEqual(r.steps, 2)
        self.assertEqual(r.last_result.rows[0][0], orders_count())
        self.assertEqual(r.failed_queries, 0)
        self.assertFalse(r.answered_without_data)

    def test_recovers_from_sql_error(self):
        a = make_agent([T("run_sql", {"query": "SELECT nope FROM orders"}),
                        T("run_sql", {"query": "SELECT COUNT(*) FROM orders"}, 2), X("Fixed.")])
        r = a.ask("q")
        self.assertEqual(r.failed_queries, 1)
        self.assertEqual([q["status"] for q in r.queries], ["error", "ok"])
        self.assertIsNotNone(r.last_result)

    def test_destructive_sql_is_blocked_and_database_untouched(self):
        before = orders_count()
        a = make_agent([T("run_sql", {"query": "DROP TABLE orders"}), X("I cannot modify data.")])
        r = a.ask("Delete everything")
        self.assertEqual(r.blocked_queries, 1)
        self.assertTrue(r.answered_without_data)
        self.assertEqual(orders_count(), before)

    def test_step_limit_stops_a_looping_model(self):
        a = make_agent([T("run_sql", {"query": "SELECT 1"})], max_steps=3)
        r = a.ask("loop forever")
        self.assertEqual(r.stopped_reason, "max_steps")
        self.assertEqual(r.steps, 3)
        self.assertIn("step limit", r.answer)

    def test_chart_tool_creates_a_png(self):
        a = make_agent([T("run_sql", {"query": "SELECT order_status, COUNT(*) AS n FROM orders GROUP BY order_status"}),
                        T("make_chart", {"chart_type": "bar", "x": "order_status", "y": "n", "title": "Orders by status"}, 2),
                        X("Chart made.")])
        r = a.ask("chart")
        self.assertEqual(len(r.chart_paths), 1)
        self.assertTrue(os.path.getsize(r.chart_paths[0]) > 1000)

    def test_chart_rejects_bad_columns_without_crashing(self):
        a = make_agent([T("run_sql", {"query": "SELECT COUNT(*) AS n FROM orders"}),
                        T("make_chart", {"chart_type": "bar", "x": "nope", "y": "n", "title": "t"}, 2), X("done")])
        r = a.ask("chart")
        self.assertEqual(r.chart_paths, [])
        self.assertEqual(r.stopped_reason, "final")

    def test_unknown_tool_is_reported_not_fatal(self):
        a = make_agent([T("drop_database", {}), X("ok")])
        r = a.ask("x")
        self.assertEqual(r.stopped_reason, "final")

    def test_row_cap_is_reported_to_the_model(self):
        a = make_agent([T("run_sql", {"query": "SELECT * FROM orders"}), X("done")], max_rows=20)
        r = a.ask("dump")
        self.assertTrue(r.last_result.truncated)
        self.assertEqual(len(r.last_result.rows), 20)


if __name__ == "__main__":
    unittest.main()
