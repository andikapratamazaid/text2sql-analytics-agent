"""Execution-accuracy comparison between a gold result set and the agent's result set.

Rules (documented so results are interpretable):
- Cell values are normalised: None stays None, numbers are rounded to 2 decimals (5 == 5.0),
  strings are trimmed and lower-cased.
- The agent may return EXTRA columns or use different column names/order. Every gold column must be
  found among the agent's columns (matched by values), and the matched columns must agree row by row.
- Row order is ignored unless the question is marked `ordered`.
- Row counts must be equal.
"""
from __future__ import annotations

from collections import Counter
from itertools import product


def norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v).strip().lower()


def _sortkey(x):
    return tuple((0, "") if c is None else ((1, c) if isinstance(c, float) else (2, c)) for c in x)


def results_match(gold_cols, gold_rows, got_cols, got_rows, ordered: bool = False) -> tuple[bool, str]:
    if got_rows is None:
        return False, "no successful query result"
    if len(gold_rows) != len(got_rows):
        return False, f"row count differs (gold {len(gold_rows)}, agent {len(got_rows)})"
    if not gold_cols:
        return True, "ok"

    g = [[norm(c) for c in r] for r in gold_rows]
    a = [[norm(c) for c in r] for r in got_rows]
    n_gold, n_got = len(gold_cols), len(got_cols)
    if n_got < n_gold:
        return False, f"agent returned fewer columns ({n_got}) than needed ({n_gold})"

    g_vals = [Counter(row[j] for row in g) for j in range(n_gold)]
    a_vals = [Counter(row[j] for row in a) for j in range(n_got)]
    candidates = [[i for i in range(n_got) if a_vals[i] == g_vals[j]] for j in range(n_gold)]
    if any(not c for c in candidates):
        missing = [gold_cols[j] for j, c in enumerate(candidates) if not c]
        return False, f"no agent column matches the values of gold column(s): {missing}"

    gold_multiset = Counter(tuple(r) for r in g)
    for combo in product(*candidates):
        if len(set(combo)) < n_gold:
            continue
        proj = [tuple(row[i] for i in combo) for row in a]
        if ordered:
            if proj == [tuple(r) for r in g]:
                return True, "ok"
        elif Counter(proj) == gold_multiset:
            return True, "ok"
    return False, "columns exist but values do not line up row by row" + (" (or order differs)" if ordered else "")
