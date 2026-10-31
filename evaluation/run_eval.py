"""Run the evaluation set and write a JSON + Markdown report.

Examples
  python -m evaluation.run_eval --lang both --repeats 1            # real model (needs ANTHROPIC_API_KEY)
  python -m evaluation.run_eval --llm mock-oracle --db /tmp/synthetic_olist.db   # harness self-test, no API
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from collections import defaultdict
from pathlib import Path

from agent.agent import Agent
from agent.config import Config
from agent.db import SafeDB
from agent.mock_llm import OracleLLM

from .compare import results_match


def load_questions(path: str) -> list[dict]:
    return json.load(open(path, encoding="utf-8"))


def make_llm(kind: str, cfg: Config, questions: list[dict]):
    if kind == "anthropic":
        from agent.llm import AnthropicClient
        return AnthropicClient(cfg.model, cfg.max_tokens)
    if kind == "mock-oracle":
        gold = {}
        for q in questions:
            if q["gold_sql"]:
                gold[q["question_en"]] = gold[q["question_id"]] = q["gold_sql"]
        return OracleLLM(gold)
    raise SystemExit(f"unknown --llm {kind}")


def run_one(agent: Agent, db: SafeDB, q: dict, lang: str, gold_cache: dict) -> dict:
    text = q["question_en"] if lang == "en" else q["question_id"]
    res = agent.ask(text)
    rec = {
        "id": q["id"], "lang": lang, "type": q["type"], "category": q["category"], "difficulty": q["difficulty"],
        "question": text, "answer": res.answer, "steps": res.steps, "tool_calls": res.tool_calls,
        "failed_queries": res.failed_queries, "blocked_queries": res.blocked_queries,
        "latency_s": round(res.latency_s, 3), "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
        "stopped": res.stopped_reason, "queries": res.queries, "charts": res.chart_paths,
        "answered_without_data": res.answered_without_data,
    }
    if q["type"] == "answerable":
        if q["id"] not in gold_cache:
            g = db.run(q["gold_sql"])
            gold_cache[q["id"]] = (g.columns, g.rows)
        gcols, grows = gold_cache[q["id"]]
        lr = res.last_result
        ok, why = results_match(gcols, grows, lr.columns if lr else [], lr.rows if lr else None, q.get("ordered", False))
        rec.update(correct=ok, reason=why,
                   agent_sql=[x["sql"] for x in res.queries if x["status"] == "ok"][-1:] or None,
                   gold_sql=q["gold_sql"],
                   recovered=(ok and res.failed_queries > 0))
    return rec


def summarize(records: list[dict]) -> dict:
    ans = [r for r in records if r["type"] == "answerable"]
    acc = lambda rs: (sum(r["correct"] for r in rs) / len(rs)) if rs else None
    by = lambda key: {k: {"n": len(v), "accuracy": acc(v)} for k, v in
                      sorted(_group(ans, key).items())}
    unsafe = [r for r in records if r["type"] == "unsafe"]
    unans = [r for r in records if r["type"] == "unanswerable"]
    errs = [r for r in ans if r["failed_queries"] > 0]
    return {
        "n_runs": len(records), "n_answerable_runs": len(ans),
        "execution_accuracy": acc(ans),
        "by_difficulty": by("difficulty"), "by_language": by("lang"), "by_category": by("category"),
        "sql_error_rate": len(errs) / len(ans) if ans else None,
        "self_correction_rate": (sum(r["recovered"] for r in errs) / len(errs)) if errs else None,
        "avg_llm_turns": st.mean(r["steps"] for r in ans) if ans else None,
        "avg_tool_calls": st.mean(r["tool_calls"] for r in ans) if ans else None,
        "avg_latency_s": st.mean(r["latency_s"] for r in ans) if ans else None,
        "avg_input_tokens": st.mean(r["input_tokens"] for r in ans) if ans else None,
        "avg_output_tokens": st.mean(r["output_tokens"] for r in ans) if ans else None,
        "unsafe_prompts": len(unsafe),
        "unsafe_write_attempts_blocked": sum(r["blocked_queries"] for r in unsafe),
        "unsafe_successful_queries": sum(1 for r in unsafe for q in r["queries"] if q["status"] == "ok"),
        "unanswerable_prompts": len(unans),
        "unanswerable_answered_with_data": sum(1 for r in unans if not r["answered_without_data"]),
    }


def _group(rs, key):
    d = defaultdict(list)
    for r in rs:
        d[r[key]].append(r)
    return d


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def markdown(summary: dict, records: list[dict], meta: dict) -> str:
    L = [f"# Evaluation report", "",
         f"- Model/LLM: `{meta['llm']}` | Database: `{meta['db']}` | Repeats: {meta['repeats']} | Languages: {meta['lang']}",
         f"- Run at: {meta['timestamp']}", "",
         "## Headline", "",
         f"**Execution accuracy: {pct(summary['execution_accuracy'])}** over {summary['n_answerable_runs']} answerable runs.", "",
         "| Metric | Value |", "|---|---|",
         f"| SQL error rate (runs with at least one failed query) | {pct(summary['sql_error_rate'])} |",
         f"| Self-correction rate (recovered after an error) | {pct(summary['self_correction_rate'])} |"]
    for k, label in [("avg_llm_turns", "Avg LLM turns"), ("avg_tool_calls", "Avg tool calls"),
                     ("avg_latency_s", "Avg latency (s)"), ("avg_input_tokens", "Avg input tokens"),
                     ("avg_output_tokens", "Avg output tokens")]:
        v = summary[k]
        L.append(f"| {label} | {'n/a' if v is None else round(v, 2)} |")
    for title, key in [("By difficulty", "by_difficulty"), ("By language", "by_language"), ("By category", "by_category")]:
        L += ["", f"## {title}", "", "| Group | Runs | Accuracy |", "|---|---|---|"]
        L += [f"| {k} | {v['n']} | {pct(v['accuracy'])} |" for k, v in summary[key].items()]
    L += ["", "## Safety checks", "",
          f"- Unsafe prompts: {summary['unsafe_prompts']} | write attempts blocked by guardrails: {summary['unsafe_write_attempts_blocked']} "
          f"| unsafe queries that executed successfully: {summary['unsafe_successful_queries']}",
          f"- Unanswerable prompts: {summary['unanswerable_prompts']} | answered using query data (review these manually): {summary['unanswerable_answered_with_data']}",
          "", "## Failures (for error analysis)", ""]
    fails = [r for r in records if r["type"] == "answerable" and not r["correct"]]
    if not fails:
        L.append("None.")
    for r in fails:
        L += [f"### {r['id']} ({r['lang']}, {r['difficulty']}): {r['question']}", f"- Reason: {r['reason']}",
              f"- Agent SQL: `{(r['agent_sql'] or ['(none)'])[0]}`", f"- Gold SQL: `{r['gold_sql']}`", ""]
    L += ["## Manual review: unanswerable and unsafe prompts", ""]
    for r in records:
        if r["type"] != "answerable":
            L += [f"- **{r['id']}** ({r['lang']}) {r['question']}  \n  Agent said: {r['answer'][:300]!r}  \n  Queries: {[(x['status']) for x in r['queries']]}"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--questions", default="evaluation/questions.json")
    ap.add_argument("--lang", choices=["en", "id", "both"], default="both")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--llm", choices=["anthropic", "mock-oracle"], default="anthropic")
    ap.add_argument("--limit", type=int, default=None, help="only the first N questions (cheap trial run)")
    ap.add_argument("--out", default="evaluation/results")
    args = ap.parse_args()

    cfg = Config()
    if args.db:
        cfg.db_path = args.db
    cfg.log_path = ""                                   # keep eval runs out of the interactive log
    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]
    db = SafeDB(cfg.db_path, cfg.max_rows, cfg.timeout_s)
    agent = Agent(cfg, make_llm(args.llm, cfg, questions), db)
    langs = ["en", "id"] if args.lang == "both" else [args.lang]

    gold_cache, records = {}, []
    for rep in range(args.repeats):
        for q in questions:
            for lang in langs:
                rec = run_one(agent, db, q, lang, gold_cache)
                rec["repeat"] = rep
                records.append(rec)
                mark = {True: "PASS", False: "FAIL", None: "----"}[rec.get("correct")]
                print(f"[{mark}] {q['id']} {lang} ({rec['steps']} turns, {rec['latency_s']}s)")

    meta = {"llm": args.llm if args.llm != "anthropic" else cfg.model, "db": cfg.db_path, "repeats": args.repeats,
            "lang": args.lang, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    summary = summarize(records)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json.dump({"meta": meta, "summary": summary, "records": records}, open(out / f"eval_{stamp}.json", "w"),
              indent=1, ensure_ascii=False, default=str)
    (out / "latest.md").write_text(markdown(summary, records, meta), encoding="utf-8")
    print(f"\nExecution accuracy: {pct(summary['execution_accuracy'])}  -> {out / 'latest.md'}")


if __name__ == "__main__":
    main()
