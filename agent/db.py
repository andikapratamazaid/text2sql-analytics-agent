"""Safe SQLite access: read-only connection, authorizer allowlist, row cap and timeout."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .guardrails import GuardrailError, validate_sql


class QueryError(Exception):
    """The query was allowed but failed (syntax error, unknown column, ...)."""


class QueryTimeout(QueryError):
    """The query exceeded the wall-clock limit."""


ALLOWED_FUNCTIONS = {
    # aggregates
    "count", "sum", "avg", "min", "max", "total", "group_concat",
    # scalar
    "abs", "round", "coalesce", "ifnull", "nullif", "iif", "length", "lower", "upper",
    "substr", "substring", "trim", "ltrim", "rtrim", "replace", "instr", "printf", "format",
    "typeof", "sign", "likely", "unlikely", "like", "glob",
    # dates
    "date", "time", "datetime", "julianday", "strftime",
    # math (available in most SQLite builds)
    "ceil", "ceiling", "floor", "sqrt", "pow", "power", "ln", "log", "log10", "log2", "exp", "mod",
    # window functions
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile",
    "lag", "lead", "first_value", "last_value", "nth_value",
}


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False
    elapsed_s: float = 0.0


@dataclass
class SafeDB:
    db_path: str
    max_rows: int = 500
    timeout_s: float = 10.0
    allowed_tables: set[str] = field(default_factory=set)
    _schema_cache: str | None = field(default=None, repr=False)
    _last_denied: str = field(default="", repr=False)

    def __post_init__(self):
        if not Path(self.db_path).exists():
            raise FileNotFoundError(
                f"Database not found: {self.db_path}. Build it with scripts/build_db.py (see README).")
        if not self.allowed_tables:
            conn = self._raw_connect()
            try:
                self.allowed_tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                }
            finally:
                conn.close()

    # ---- connections -------------------------------------------------------------------
    def _uri(self) -> str:
        return f"{Path(self.db_path).resolve().as_uri()}?mode=ro"      # layer 2: read-only file

    def _raw_connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._uri(), uri=True)

    def _authorizer(self, action, arg1, arg2, dbname, source):          # layer 3: engine-level allowlist
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if arg1 in self.allowed_tables:
                return sqlite3.SQLITE_OK
            self._last_denied = f"table '{arg1}' is not on the allowlist"
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or "").lower() in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            self._last_denied = f"function '{arg2}' is not on the allowlist"
            return sqlite3.SQLITE_DENY
        self._last_denied = "this operation is not permitted (read-only SELECT queries only)"
        return sqlite3.SQLITE_DENY

    # ---- execution ---------------------------------------------------------------------
    def run(self, sql: str) -> QueryResult:
        """Validate, then execute with every guardrail layer active."""
        return self._execute(validate_sql(sql))

    def _execute(self, sql: str) -> QueryResult:
        """Execute WITHOUT static validation (layers 2-4 only). Used by tests to prove the
        engine-level layers hold even if layer 1 were bypassed."""
        conn = self._raw_connect()
        self._last_denied = ""
        conn.set_authorizer(self._authorizer)
        deadline = time.monotonic() + self.timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)  # layer 4
        t0 = time.monotonic()
        try:
            cur = conn.execute(sql)
            if cur.description is None:
                raise GuardrailError("Statement returned no result set.")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(self.max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "interrupted" in msg:
                raise QueryTimeout(f"Query exceeded the {self.timeout_s:.0f}s time limit. Simplify it or aggregate earlier.") from e
            if "not authorized" in msg or "prohibited" in msg or "readonly" in msg.lower():
                detail = self._last_denied or "operation not permitted"
                raise GuardrailError(f"Blocked by the database authorizer: {detail}.") from e
            raise QueryError(msg) from e
        finally:
            conn.close()
        truncated = len(rows) > self.max_rows
        return QueryResult(cols, [tuple(r) for r in rows[: self.max_rows]], truncated, time.monotonic() - t0)

    # ---- schema ------------------------------------------------------------------------
    def schema_text(self) -> str:
        """Human/LLM-readable schema with row counts and low-cardinality values."""
        if self._schema_cache:
            return self._schema_cache
        conn = self._raw_connect()          # introspection only; never exposed to arbitrary SQL
        try:
            lines = ["Database: SQLite (read-only). Tables and columns:"]
            for t in sorted(self.allowed_tables):
                n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                lines.append(f"\n- {t} ({n:,} rows)")
                for _, name, ctype, *_ in conn.execute(f'PRAGMA table_info("{t}")'):
                    note = ""
                    if (ctype or "").upper() == "TEXT":
                        vals = [r[0] for r in conn.execute(
                            f'SELECT DISTINCT "{name}" FROM "{t}" WHERE "{name}" IS NOT NULL LIMIT 13')]
                        if 0 < len(vals) <= 12:
                            note = "   values: " + ", ".join(str(v) for v in sorted(vals))
                    lines.append(f"    {name} {ctype or ''}{note}")
            self._schema_cache = "\n".join(lines)
        finally:
            conn.close()
        return self._schema_cache
