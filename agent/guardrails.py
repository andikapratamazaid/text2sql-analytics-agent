"""Guardrail layer 1: static SQL validation.

Layers of defence (each one is tested on its own, see tests/):
  1. validate_sql()      - this file: one statement, SELECT/WITH only, no write/DDL keywords
  2. read-only database  - the SQLite file is opened with mode=ro
  3. SQLite authorizer   - table + function allowlist enforced by the engine itself
  4. row cap + timeout   - bounded result size and wall-clock time
"""
import re


class GuardrailError(Exception):
    """Raised when a statement violates the read-only policy."""


MAX_SQL_CHARS = 6000

FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach",
    "pragma", "vacuum", "reindex", "analyze", "begin", "commit", "rollback",
    "savepoint", "release", "truncate", "grant", "revoke", "load_extension",
)


def strip_literals_and_comments(sql: str) -> str:
    """Return the SQL with comments removed and string/identifier contents blanked.

    This lets keyword checks ignore text such as WHERE order_status = 'delete'
    while still seeing real keywords hidden after a comment.
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"', "`"):
            q = c
            i += 1
            while i < n:
                if sql[i] == q:
                    if i + 1 < n and sql[i + 1] == q:   # escaped quote
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            out.append(q + q)
        elif c == "[":                                    # [bracketed identifier]
            j = sql.find("]", i)
            i = n if j == -1 else j + 1
            out.append("[]")
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            out.append(" ")
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def validate_sql(sql: str) -> str:
    """Return the statement ready to execute, or raise GuardrailError."""
    if not sql or not sql.strip():
        raise GuardrailError("Empty query.")
    if len(sql) > MAX_SQL_CHARS:
        raise GuardrailError(f"Query too long (limit {MAX_SQL_CHARS} characters).")

    body = strip_literals_and_comments(sql).strip().rstrip(";").strip()
    if ";" in body:
        raise GuardrailError("Only a single statement is allowed (found ';').")

    m = re.match(r"\s*(\w+)", body)
    first = m.group(1).lower() if m else ""
    if first not in ("select", "with"):
        raise GuardrailError("Only read-only SELECT queries are allowed (statement must start with SELECT or WITH).")

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", body, flags=re.IGNORECASE):
            raise GuardrailError(f"Forbidden keyword '{kw.upper()}': this agent is read-only.")
    if re.search(r"\breplace\s+into\b", body, flags=re.IGNORECASE):
        raise GuardrailError("Forbidden statement 'REPLACE INTO': this agent is read-only.")

    return sql.strip().rstrip(";").strip()
