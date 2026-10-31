import unittest

from agent.agent import Agent
from agent.config import Config
from agent.db import SafeDB
from agent.mock_llm import OracleLLM
from evaluation.run_eval import load_questions, run_one, summarize

from .helpers import DB_PATH

QUESTIONS = load_questions("evaluation/questions.json")
ANSWERABLE = [q for q in QUESTIONS if q["type"] == "answerable"]


def gold_map():
    g = {}
    for q in ANSWERABLE:
        g[q["question_en"]] = g[q["question_id"]] = q["gold_sql"]
    return g


def run_all(llm, qs=None):
    cfg = Config(db_path=DB_PATH, log_path="")
    db = SafeDB(DB_PATH)
    agent = Agent(cfg, llm, db)
    cache, recs = {}, []
    for q in qs or QUESTIONS:
        for lang in ("en", "id"):
            recs.append(run_one(agent, db, q, lang, cache))
    return recs


class TestGoldQueries(unittest.TestCase):
    def test_every_gold_query_runs_and_returns_data(self):
        db = SafeDB(DB_PATH)
        for q in ANSWERABLE:
            with self.subTest(q["id"]):
                res = db.run(q["gold_sql"])
                self.assertTrue(res.rows, "empty gold result makes the question meaningless")
                if len(res.rows) == 1 and len(res.columns) == 1:
                    self.assertIsNotNone(res.rows[0][0])

    def test_questions_are_bilingual_and_ids_unique(self):
        ids = [q["id"] for q in QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for q in QUESTIONS:
            self.assertTrue(q["question_en"] and q["question_id"])


class TestHarness(unittest.TestCase):
    def test_oracle_scores_perfectly(self):
        recs = run_all(OracleLLM(gold_map()))
        s = summarize(recs)
        self.assertEqual(s["execution_accuracy"], 1.0)
        self.assertEqual(s["n_answerable_runs"], 2 * len(ANSWERABLE))

    def test_wrong_sql_is_detected(self):
        q = ANSWERABLE[0]                                   # q01
        wrong = {q["question_en"]: "SELECT COUNT(*) + 1 FROM orders"}
        recs = run_all(OracleLLM(gold_map(), overrides=wrong), qs=[q])
        by_lang = {r["lang"]: r for r in recs}
        self.assertFalse(by_lang["en"]["correct"])
        self.assertTrue(by_lang["id"]["correct"])           # only the English text was overridden
        self.assertEqual(summarize(recs)["execution_accuracy"], 0.5)

    def test_self_correction_is_counted(self):
        q = next(x for x in ANSWERABLE if x["id"] == "q03")
        broken = {q["question_en"]: "SELEC oops FROM"}
        recs = [r for r in run_all(OracleLLM(gold_map(), fail_first=broken), qs=[q]) if r["lang"] == "en"]
        self.assertTrue(recs[0]["correct"])
        self.assertTrue(recs[0]["recovered"])
        self.assertEqual(recs[0]["failed_queries"], 1)

    def test_extra_columns_do_not_break_scoring(self):
        q = next(x for x in ANSWERABLE if x["id"] == "q07")
        richer = {q["question_en"]: "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS n, 1 AS extra "
                                    "FROM customers GROUP BY customer_state ORDER BY n DESC, customer_state LIMIT 5"}
        recs = run_all(OracleLLM(gold_map(), overrides=richer), qs=[q])
        self.assertTrue([r for r in recs if r["lang"] == "en"][0]["correct"])

    def test_unsafe_prompts_never_execute_write_queries(self):
        unsafe = [q for q in QUESTIONS if q["type"] == "unsafe"]
        evil = {}
        for q in unsafe:
            evil[q["question_en"]] = evil[q["question_id"]] = "DROP TABLE customers"
        recs = run_all(OracleLLM(evil), qs=unsafe)
        s = summarize(recs)
        self.assertEqual(s["unsafe_successful_queries"], 0)
        self.assertEqual(s["unsafe_write_attempts_blocked"], len(recs))


if __name__ == "__main__":
    unittest.main()
