"""The agent loop: question -> (LLM <-> tools)* -> answer, with step limits and run logging."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .db import QueryResult, SafeDB
from .llm import LLMClient
from .prompts import build_system_prompt
from .tools import TOOLS, ToolRunner


@dataclass
class AgentResult:
    question: str
    answer: str
    stopped_reason: str                      # final | max_steps | max_tokens
    steps: int = 0                           # LLM turns used
    tool_calls: int = 0
    queries: list[dict] = field(default_factory=list)
    last_result: QueryResult | None = None
    chart_paths: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def failed_queries(self) -> int:
        return sum(1 for q in self.queries if q["status"] != "ok")

    @property
    def blocked_queries(self) -> int:
        return sum(1 for q in self.queries if q["status"] == "blocked")

    @property
    def answered_without_data(self) -> bool:
        """True when the model answered but never got a successful query result (possible hallucination, or a refusal)."""
        return self.last_result is None


class Agent:
    def __init__(self, config: Config, llm: LLMClient, db: SafeDB | None = None):
        self.config, self.llm = config, llm
        self.db = db or SafeDB(config.db_path, config.max_rows, config.timeout_s)
        self.system = build_system_prompt()

    def ask(self, question: str) -> AgentResult:
        t0 = time.monotonic()
        runner = ToolRunner(self.db, self.config)
        messages: list[dict] = [{"role": "user", "content": question}]
        res = AgentResult(question=question, answer="", stopped_reason="max_steps")

        for _ in range(self.config.max_steps):
            resp = self.llm.create(self.system, messages, TOOLS)
            res.steps += 1
            usage = resp.get("usage") or {}
            res.input_tokens += usage.get("input_tokens", 0)
            res.output_tokens += usage.get("output_tokens", 0)
            messages.append({"role": "assistant", "content": resp["content"]})

            tool_uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
            text = "\n".join(b["text"] for b in resp["content"] if b.get("type") == "text").strip()
            if not tool_uses:
                res.answer = text
                res.stopped_reason = "max_tokens" if resp.get("stop_reason") == "max_tokens" else "final"
                break

            results = []
            for tu in tool_uses:
                out, is_err = runner.call(tu["name"], tu.get("input") or {})
                res.tool_calls += 1
                block = {"type": "tool_result", "tool_use_id": tu["id"], "content": out}
                if is_err:
                    block["is_error"] = True
                results.append(block)
            messages.append({"role": "user", "content": results})
        else:
            res.answer = ("I could not finish within the step limit. "
                          "Please rephrase or narrow the question.")

        res.queries, res.last_result, res.chart_paths = runner.queries, runner.last_result, runner.chart_paths
        res.latency_s = time.monotonic() - t0
        self._log(res)
        return res

    def _log(self, res: AgentResult) -> None:
        if not self.config.log_path:
            return
        path = Path(self.config.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": res.question, "stopped": res.stopped_reason,
            "steps": res.steps, "tool_calls": res.tool_calls, "failed_queries": res.failed_queries,
            "blocked_queries": res.blocked_queries, "latency_s": round(res.latency_s, 3),
            "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
            "queries": res.queries, "answer": res.answer,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
