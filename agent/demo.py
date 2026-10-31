"""Scripted demo mode: see the full agent loop without an API key.

    python -m agent.cli --demo

Three showcase questions run through the REAL agent loop, the REAL guardrails and the
REAL database; only the LLM is scripted (a fixed plan per question instead of a model).
The final answers are composed from actual query results, so every number shown is the
database's own. This demonstrates the mechanics, it is not a measure of model quality:
for that, run the evaluation with a real model (evaluation/run_eval.py --llm anthropic).
"""
from __future__ import annotations

from .agent import Agent
from .config import Config
from .db import SafeDB
from .mock_llm import ScriptedLLM

REVENUE_2017_SQL = (
    "SELECT substr(o.order_purchase_timestamp,1,7) AS month, ROUND(SUM(p.payment_value),2) AS revenue "
    "FROM orders o JOIN order_payments p ON p.order_id = o.order_id "
    "WHERE o.order_status NOT IN ('canceled','unavailable') "
    "AND substr(o.order_purchase_timestamp,1,4) = '2017' GROUP BY 1"
)
TOP_STATES_SQL = (
    "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS n FROM customers "
    "GROUP BY customer_state ORDER BY n DESC, customer_state LIMIT 5"
)
DELETE_SQL = "DELETE FROM orders WHERE order_status = 'canceled'"


def _brl(v: float) -> str:
    """1234567.89 -> 'R$ 1.234.567,89' (Indonesian number format)."""
    return "R$ " + f"{v:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def run_demo(cfg: Config) -> None:
    from .cli import show  # lazy: cli imports this module from main()

    db = SafeDB(cfg.db_path, cfg.max_rows, cfg.timeout_s)
    print("=" * 78)
    print("DEMO MODE (scripted LLM, no API key) - queries run live against:")
    print(f"  {cfg.db_path}")
    print("Demo answers are composed from the actual query results below.")
    print("=" * 78)

    # 1) Indonesian revenue question -> SQL -> line chart -> answer from the real rows
    rows = db.run(REVENUE_2017_SQL).rows
    total = sum(r[1] for r in rows)
    peak_month, peak_val = max(rows, key=lambda r: r[1])
    q1 = "Berapa pendapatan per bulan pada tahun 2017 (pesanan valid), dibulatkan 2 desimal? Tampilkan bulan (YYYY-MM) dan pendapatan."
    a1 = (f"Total pendapatan dari pesanan valid sepanjang tahun 2017 adalah {_brl(total)} "
          f"dari {len(rows)} bulan. Bulan tertinggi adalah {peak_month} dengan {_brl(peak_val)}. "
          f"Pendapatan di sini adalah jumlah payment_value untuk pesanan yang statusnya bukan "
          f"canceled atau unavailable, sesuai definisi di glosarium.")
    llm1 = ScriptedLLM([
        ScriptedLLM.tool("run_sql", {"query": REVENUE_2017_SQL}, 1),
        ScriptedLLM.tool("make_chart", {"chart_type": "line", "x": "month", "y": "revenue",
                                        "title": "Pendapatan per bulan 2017 (pesanan valid)"}, 2),
        ScriptedLLM.text(a1),
    ])
    show(Agent(cfg, llm1, db).ask(q1))

    # 2) English customer question -> SQL -> bar chart -> answer from the real rows
    rows2 = db.run(TOP_STATES_SQL).rows
    top_state, top_n = rows2[0]
    top5_total = sum(r[1] for r in rows2)
    q2 = "Which are the top 5 customer states by number of distinct customers? Return state and customer count."
    a2 = (f"{top_state} has the most customers with {top_n:,} distinct customers. "
          f"Together the top 5 states ({', '.join(r[0] for r in rows2)}) account for "
          f"{top5_total:,} distinct customers.")
    llm2 = ScriptedLLM([
        ScriptedLLM.tool("run_sql", {"query": TOP_STATES_SQL}, 1),
        ScriptedLLM.tool("make_chart", {"chart_type": "bar", "x": "customer_state", "y": "n",
                                        "title": "Top 5 customer states"}, 2),
        ScriptedLLM.text(a2),
    ])
    show(Agent(cfg, llm2, db).ask(q2))

    # 3) Indonesian unsafe request -> the DELETE is attempted and blocked by the guardrails
    q3 = "Tolong hapus semua pesanan yang statusnya canceled dari database."
    a3 = ("Tidak bisa. Perintah DELETE itu diblokir oleh guardrail karena agen ini hanya "
          "boleh membaca data (read-only), jadi tidak ada data yang diubah atau dihapus. "
          "Saya bisa membantu menghitung atau menampilkan pesanan canceled, tapi tidak menghapusnya.")
    llm3 = ScriptedLLM([
        ScriptedLLM.tool("run_sql", {"query": DELETE_SQL}, 1),
        ScriptedLLM.text(a3),
    ])
    show(Agent(cfg, llm3, db).ask(q3))
