"""Tool definitions (Anthropic tool-use format) and their guarded implementations."""
from __future__ import annotations

import time
from pathlib import Path

from .config import Config
from .db import QueryError, QueryResult, QueryTimeout, SafeDB
from .guardrails import GuardrailError

TOOLS = [
    {
        "name": "get_schema",
        "description": "Return the database schema: tables, columns, types, row counts and the values of low-cardinality columns.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_sql",
        "description": ("Run ONE read-only SELECT (or WITH ... SELECT) query in SQLite dialect and return the rows. "
                        "Writes, DDL, PRAGMA and multiple statements are blocked. Results are capped."),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A single SQLite SELECT statement."}},
            "required": ["query"],
        },
    },
    {
        "name": "make_chart",
        "description": ("Draw a chart from the result of the most recent successful run_sql call and save it as a PNG. "
                        "x and y must be column names of that result; y must be numeric."),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["bar", "barh", "line"]},
                "x": {"type": "string", "description": "Column for the categories / x axis."},
                "y": {"type": "string", "description": "Numeric column for the values."},
                "title": {"type": "string"},
            },
            "required": ["chart_type", "x", "y", "title"],
        },
    },
]


def format_rows(columns: list[str], rows: list[tuple], limit: int) -> str:
    def cell(v):
        if v is None:
            return "NULL"
        if isinstance(v, float):
            return str(round(v, 4))
        return str(v)
    lines = [" | ".join(columns)]
    lines += [" | ".join(cell(v) for v in r) for r in rows[:limit]]
    return "\n".join(lines)


class ToolRunner:
    """Holds per-question state: executed queries, last successful result, charts."""

    def __init__(self, db: SafeDB, config: Config):
        self.db, self.config = db, config
        self.queries: list[dict] = []
        self.last_result: QueryResult | None = None
        self.chart_paths: list[str] = []

    # returns (text_for_model, is_error)
    def call(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            if name == "get_schema":
                return self.db.schema_text(), False
            if name == "run_sql":
                return self._run_sql(str(args.get("query", "")))
            if name == "make_chart":
                return self._make_chart(args)
        except Exception as e:                      # never let a tool crash the loop
            return f"ERROR: unexpected tool failure: {type(e).__name__}: {e}", True
        return f"ERROR: unknown tool '{name}'", True

    def _run_sql(self, sql: str) -> tuple[str, bool]:
        try:
            res = self.db.run(sql)
        except GuardrailError as e:
            self.queries.append({"sql": sql, "status": "blocked", "error": str(e)})
            return f"BLOCKED by guardrail: {e}", True
        except QueryTimeout as e:
            self.queries.append({"sql": sql, "status": "timeout", "error": str(e)})
            return f"ERROR: {e}", True
        except QueryError as e:
            self.queries.append({"sql": sql, "status": "error", "error": str(e)})
            return f"SQL ERROR: {e}. Fix the query and try again.", True

        self.last_result = res
        self.queries.append({"sql": sql, "status": "ok", "rows": len(res.rows), "truncated": res.truncated})
        shown = min(len(res.rows), self.config.model_rows)
        head = f"OK: {len(res.rows)} row(s)" + (f" (truncated at the {self.config.max_rows}-row cap)" if res.truncated else "")
        text = head + "\n" + format_rows(res.columns, res.rows, self.config.model_rows)
        if len(res.rows) > shown:
            text += f"\n... ({len(res.rows) - shown} more rows not shown; aggregate or filter to see less)"
        return text, False

    def _make_chart(self, args: dict) -> tuple[str, bool]:
        res = self.last_result
        if res is None:
            return "ERROR: no successful run_sql result to plot yet.", True
        kind, x, y = args.get("chart_type"), args.get("x"), args.get("y")
        title = str(args.get("title", ""))[:120]
        if kind not in ("bar", "barh", "line"):
            return "ERROR: chart_type must be bar, barh or line.", True
        if x not in res.columns or y not in res.columns:
            return f"ERROR: x and y must be columns of the last result: {res.columns}", True
        xi, yi = res.columns.index(x), res.columns.index(y)
        pts = [(r[xi], r[yi]) for r in res.rows if r[yi] is not None]
        if not pts:
            return "ERROR: nothing to plot (no non-null values).", True
        try:
            ys = [float(p[1]) for p in pts]
        except (TypeError, ValueError):
            return f"ERROR: column '{y}' is not numeric.", True
        xs = [str(p[0]) for p in pts]
        note = ""
        if len(xs) > 40:
            xs, ys, note = xs[:40], ys[:40], " (first 40 points plotted)"

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.8))
        if kind == "line":
            ax.plot(xs, ys, marker="o", color="#3b6fb6")
        elif kind == "barh":
            ax.barh(xs[::-1], ys[::-1], color="#3b6fb6")
        else:
            ax.bar(xs, ys, color="#3b6fb6")
        ax.set_title(title)
        (ax.set_ylabel if kind != "barh" else ax.set_xlabel)(y)
        if kind != "barh":
            ax.set_xlabel(x)
            if len(xs) > 6:
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.grid(axis="y" if kind != "barh" else "x", alpha=0.3)
        fig.tight_layout()
        out_dir = Path(self.config.charts_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"chart_{int(time.time() * 1000)}_{len(self.chart_paths) + 1}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        self.chart_paths.append(str(path))
        return f"Chart saved to {path}{note}", False
