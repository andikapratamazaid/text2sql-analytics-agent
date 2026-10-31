"""Deterministic fake LLMs used to test the agent loop and the evaluation harness without an API key.

They are test doubles, NOT a measure of model quality: accuracy numbers must come from a real model.
"""
from __future__ import annotations

import itertools


def _tool_use(name: str, args: dict, n: int) -> dict:
    return {"type": "tool_use", "id": f"toolu_mock_{n}", "name": name, "input": args}


def _resp(content: list[dict], stop: str = "end_turn") -> dict:
    return {"content": content, "stop_reason": stop, "usage": {"input_tokens": 0, "output_tokens": 0}}


class ScriptedLLM:
    """Returns pre-written responses in order."""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls = 0

    def create(self, system, messages, tools):
        r = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return r

    @staticmethod
    def tool(name: str, args: dict, n: int = 1) -> dict:
        return _resp([_tool_use(name, args, n)], "tool_use")

    @staticmethod
    def text(msg: str) -> dict:
        return _resp([{"type": "text", "text": msg}])


class OracleLLM:
    """Looks the question up in a table of SQL strings, runs it, then writes a placeholder answer.

    gold:       {question_text: sql}
    overrides:  {question_text: sql} used instead of the gold SQL (to simulate wrong answers)
    fail_first: {question_text: broken_sql} sent first; the correct SQL is sent after the error (self-correction)
    """

    def __init__(self, gold: dict[str, str], overrides: dict[str, str] | None = None,
                 fail_first: dict[str, str] | None = None):
        self.gold, self.overrides, self.fail_first = gold, overrides or {}, fail_first or {}
        self._n = itertools.count(1)

    def create(self, system, messages, tools):
        question = messages[0]["content"]
        results = [b for m in messages[1:] if m["role"] == "user" for b in m["content"] if b.get("type") == "tool_result"]
        sql = self.overrides.get(question, self.gold.get(question))
        if sql is None:                                     # unknown question -> refuse politely
            return _resp([{"type": "text", "text": "I cannot answer that from this database."}])
        if not results:
            first = self.fail_first.get(question, sql)
            return _resp([_tool_use("run_sql", {"query": first}, next(self._n))], "tool_use")
        if results[-1].get("is_error") and question in self.fail_first and len(results) == 1:
            return _resp([_tool_use("run_sql", {"query": sql}, next(self._n))], "tool_use")
        return _resp([{"type": "text", "text": "Done (mock oracle answer)."}])
