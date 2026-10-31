"""Generate a SYNTHETIC database with the exact Olist schema, for tests and CI only.

The data is random. It exists so the guardrails, the agent loop and the evaluation harness can be
tested without downloading Kaggle data. Never report numbers from it as real results.

Usage:
  python scripts/make_synthetic_db.py --db /tmp/synthetic_olist.db
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/make_synthetic_db.py`
from scripts.build_db import build

CATEGORIES = {
    "cama_mesa_banho": "bed_bath_table", "beleza_saude": "health_beauty", "esporte_lazer": "sports_leisure",
    "informatica_acessorios": "computers_accessories", "moveis_decoracao": "furniture_decor",
    "utilidades_domesticas": "housewares", "relogios_presentes": "watches_gifts", "telefonia": "telephony",
    "automotivo": "auto", "brinquedos": "toys", "cool_stuff": "cool_stuff", "perfumaria": "perfumery",
    "bebes": "baby", "eletronicos": "electronics", "papelaria": "stationery",
}
STATES = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES"]
STATE_W = np.array([.40, .13, .12, .06, .06, .04, .04, .03, .03, .02])


def _hex(i: int, prefix: str = "") -> str:
    return f"{prefix}{i:032x}"[-32:]


def _fmt(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime("%Y-%m-%d %H:%M:%S")


def generate(out_dir: Path, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_people = 3500
    p_state = rng.choice(STATES, n_people, p=STATE_W / STATE_W.sum())
    k = rng.choice([1, 2, 3], n_people, p=[.90, .08, .02])
    start, end = pd.Timestamp("2016-10-01"), pd.Timestamp("2018-08-15")
    span = (end - start).days

    rows = []                                      # (person, purchase_ts)
    for p in range(n_people):
        if p < 60:                                 # guaranteed 2017-01 cohort ...
            first = pd.Timestamp("2017-01-03") + pd.Timedelta(days=int(rng.integers(0, 27)), hours=int(rng.integers(0, 24)))
        else:
            first = start + pd.Timedelta(days=float(rng.beta(2.2, 1.6) * span))
        dates = [first]
        n_orders = max(int(k[p]), 2) if p < 25 else int(k[p])
        for j in range(1, n_orders):
            if p < 25 and j == 1:                  # ... with a returning purchase in 2017-02
                nxt = pd.Timestamp("2017-02-02") + pd.Timedelta(days=int(rng.integers(0, 25)), hours=int(rng.integers(0, 24)))
            else:
                nxt = dates[-1] + pd.Timedelta(days=int(rng.integers(7, 300)))
            dates.append(min(nxt, pd.Timestamp("2018-08-25")))
        rows += [(p, d) for d in dates]
    rows.sort(key=lambda r: r[1])
    n = len(rows)
    person = np.array([r[0] for r in rows])
    purchase = pd.Series([r[1] for r in rows])

    # --- customers (one row per ORDER, like the real dataset) -------------------------------
    customers = pd.DataFrame({
        "customer_id": [_hex(i + 1, "c") for i in range(n)],
        "customer_unique_id": [_hex(int(p) + 1, "u") for p in person],
        "customer_zip_code_prefix": [f"{int(z):05d}" for z in rng.integers(1000, 99999, n)],
        "customer_city": [f"city_{p_state[pp].lower()}_{int(c)}" for pp, c in zip(person, rng.integers(0, 5, n))],
        "customer_state": p_state[person],
    })

    # --- orders ----------------------------------------------------------------------------
    status = rng.choice(["delivered", "canceled", "shipped", "unavailable", "invoiced", "processing"], n,
                        p=[.92, .03, .02, .01, .01, .01])
    approved = purchase + pd.to_timedelta(rng.uniform(0.1, 20, n), unit="h")
    carrier = purchase + pd.to_timedelta(rng.uniform(1, 5, n), unit="D")
    deliv_days = rng.gamma(4, 3.2, n) + 3
    delivered = purchase + pd.to_timedelta(deliv_days, unit="D")
    estimated = purchase + pd.to_timedelta(rng.uniform(20, 35, n), unit="D")
    no_deliv_date = (status != "delivered") | (rng.random(n) < 0.03)
    orders = pd.DataFrame({
        "order_id": [_hex(i + 1, "o") for i in range(n)],
        "customer_id": customers["customer_id"],
        "order_status": status,
        "order_purchase_timestamp": _fmt(purchase),
        "order_approved_at": _fmt(approved).where(status != "canceled"),
        "order_delivered_carrier_date": _fmt(carrier).where(np.isin(status, ["delivered", "shipped"])),
        "order_delivered_customer_date": _fmt(delivered).where(~no_deliv_date),
        "order_estimated_delivery_date": _fmt(estimated),
    })

    # --- products, sellers, translation -----------------------------------------------------
    cats = list(CATEGORIES)
    n_prod = 300
    products = pd.DataFrame({
        "product_id": [_hex(i + 1, "p") for i in range(n_prod)],
        "product_category_name": rng.choice(cats, n_prod, p=np.array([15, 12, 10, 10, 9, 8, 7, 6, 6, 5, 4, 4, 4, 3, 3]) / 106),
        "product_name_lenght": rng.integers(20, 60, n_prod), "product_description_lenght": rng.integers(100, 1500, n_prod),
        "product_photos_qty": rng.integers(1, 6, n_prod), "product_weight_g": rng.integers(100, 5000, n_prod),
        "product_length_cm": rng.integers(10, 60, n_prod), "product_height_cm": rng.integers(5, 40, n_prod),
        "product_width_cm": rng.integers(10, 50, n_prod),
    })
    n_sell = 60
    sellers = pd.DataFrame({
        "seller_id": [_hex(i + 1, "s") for i in range(n_sell)],
        "seller_zip_code_prefix": [f"{int(z):05d}" for z in rng.integers(1000, 99999, n_sell)],
        "seller_city": [f"city_{s.lower()}" for s in rng.choice(STATES, n_sell)],
        "seller_state": rng.choice(STATES, n_sell),
    })
    translation = pd.DataFrame({"product_category_name": cats, "product_category_name_english": [CATEGORIES[c] for c in cats]})

    # --- items -------------------------------------------------------------------------------
    n_items = rng.choice([1, 2, 3], n, p=[.80, .15, .05])
    item_rows = []
    for i in range(n):
        for j in range(int(n_items[i])):
            item_rows.append((orders.order_id[i], j + 1, products.product_id[int(rng.integers(0, n_prod))],
                              sellers.seller_id[int(rng.integers(0, n_sell))],
                              round(float(np.exp(rng.normal(4.25, 0.8))), 2), round(float(rng.uniform(5, 40)), 2), i))
    items = pd.DataFrame(item_rows, columns=["order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value", "_i"])
    items["shipping_limit_date"] = _fmt(purchase[items["_i"].to_numpy()].reset_index(drop=True) + pd.Timedelta(days=3))
    items = items[["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"]]

    # --- payments ----------------------------------------------------------------------------
    totals = items.assign(t=items.price + items.freight_value).groupby("order_id")["t"].sum()
    pay_rows = []
    for oid in orders.order_id:
        total = float(totals[oid])
        ptype = rng.choice(["credit_card", "boleto", "voucher", "debit_card"], p=[.75, .19, .04, .02])
        if rng.random() < 0.85:
            pay_rows.append((oid, 1, ptype, int(rng.integers(1, 11)) if ptype == "credit_card" else 1, round(total, 2)))
        else:
            part = round(total * float(rng.uniform(.2, .6)), 2)
            pay_rows.append((oid, 1, ptype, 1, round(total - part, 2)))
            pay_rows.append((oid, 2, "voucher", 1, part))
    payments = pd.DataFrame(pay_rows, columns=["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"])

    # --- reviews -----------------------------------------------------------------------------
    late = (orders.order_status == "delivered") & (delivered > estimated) & (~no_deliv_date)
    review_rows = []
    for i in range(n):
        if status[i] in ("processing", "invoiced") or rng.random() < 0.03:
            continue
        probs = [.30, .15, .15, .15, .25] if late[i] else [.05, .04, .08, .19, .64]
        created = (delivered[i] if not no_deliv_date[i] else purchase[i] + pd.Timedelta(days=10)) + pd.Timedelta(days=1)
        review_rows.append((_hex(len(review_rows) + 1, "r"), orders.order_id[i], int(rng.choice([1, 2, 3, 4, 5], p=probs)),
                            None, None, created.strftime("%Y-%m-%d 00:00:00"), (created + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")))
    reviews = pd.DataFrame(review_rows, columns=["review_id", "order_id", "review_score", "review_comment_title",
                                                 "review_comment_message", "review_creation_date", "review_answer_timestamp"])

    files = {
        "olist_customers_dataset.csv": customers, "olist_orders_dataset.csv": orders,
        "olist_order_items_dataset.csv": items, "olist_order_payments_dataset.csv": payments,
        "olist_order_reviews_dataset.csv": reviews, "olist_products_dataset.csv": products,
        "olist_sellers_dataset.csv": sellers, "product_category_name_translation.csv": translation,
    }
    for name, df in files.items():
        df.to_csv(out_dir / name, index=False)


def make(db_path: str, seed: int = 0) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        generate(Path(tmp), seed)
        build(tmp, db_path)
    return db_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/synthetic_olist.db")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    make(a.db, a.seed)
