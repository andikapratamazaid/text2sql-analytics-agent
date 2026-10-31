"""Command line interface.

  python -m agent.cli "Berapa total pendapatan per bulan di 2017?"
  python -m agent.cli --interactive
"""
from __future__ import annotations

import argparse

from .agent import Agent, AgentResult
from .config import Config
from .llm import AnthropicClient
from .tools import format_rows


def show(res: AgentResult, show_sql: bool = True, preview_rows: int = 15) -> None:
    print("\n=== Answer ===")
    print(res.answer or "(no answer)")
    if res.last_result is not None:
        r = res.last_result
        print(f"\n=== Data (last successful query, first {min(preview_rows, len(r.rows))} of {len(r.rows)} rows) ===")
        print(format_rows(r.columns, r.rows, preview_rows))
    if res.chart_paths:
        print("\n=== Charts ===")
        for p in res.chart_paths:
            print(p)
    if show_sql and res.queries:
        print("\n=== SQL attempts ===")
        for i, q in enumerate(res.queries, 1):
            print(f"[{i}] ({q['status']}) {q['sql']}" + (f"\n    -> {q.get('error')}" if q.get("error") else ""))
    print(f"\n[{res.steps} LLM turns, {res.tool_calls} tool calls, {res.latency_s:.1f}s, "
          f"{res.input_tokens}+{res.output_tokens} tokens]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Text-to-SQL analytics agent")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--interactive", "-i", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="scripted showcase on the real database, no API key needed (see agent/demo.py)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-sql", action="store_true", help="hide the SQL attempts")
    args = ap.parse_args()

    cfg = Config()
    if args.db:
        cfg.db_path = args.db
    if args.model:
        cfg.model = args.model
    if args.demo:
        from .demo import run_demo
        run_demo(cfg)
        return
    agent = Agent(cfg, AnthropicClient(cfg.model, cfg.max_tokens))

    if args.interactive:
        print("Ask a question (Indonesian or English). Empty line to quit.")
        while True:
            q = input("\n> ").strip()
            if not q:
                break
            show(agent.ask(q), show_sql=not args.no_sql)
    elif args.question:
        show(agent.ask(args.question), show_sql=not args.no_sql)
    else:
        ap.error("give a question or use --interactive")


if __name__ == "__main__":
    main()
