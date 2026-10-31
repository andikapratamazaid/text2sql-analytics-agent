"""Load the Olist CSV files into a SQLite database the agent can query.

Usage:
  python scripts/build_db.py --csv-dir data/olist --db data/olist.db

Dataset: Olist Brazilian E-Commerce Public Dataset (Kaggle: olistbr/brazilian-ecommerce).
Short table names match the earlier PostgreSQL RFM/cohort project.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

TABLE_FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

NUMERIC = {
    "order_items": {"order_item_id": "int", "price": "float", "freight_value": "float"},
    "order_payments": {"payment_sequential": "int", "payment_installments": "int", "payment_value": "float"},
    "order_reviews": {"review_score": "int"},
    "products": {"product_name_lenght": "float", "product_description_lenght": "float", "product_photos_qty": "float",
                 "product_weight_g": "float", "product_length_cm": "float", "product_height_cm": "float",
                 "product_width_cm": "float"},
}

INDEXES = [
    "CREATE INDEX idx_orders_customer ON orders(customer_id)",
    "CREATE INDEX idx_orders_status ON orders(order_status)",
    "CREATE INDEX idx_customers_unique ON customers(customer_unique_id)",
    "CREATE INDEX idx_items_order ON order_items(order_id)",
    "CREATE INDEX idx_items_product ON order_items(product_id)",
    "CREATE INDEX idx_items_seller ON order_items(seller_id)",
    "CREATE INDEX idx_pay_order ON order_payments(order_id)",
    "CREATE INDEX idx_rev_order ON order_reviews(order_id)",
    "CREATE INDEX idx_prod_id ON products(product_id)",
    "CREATE INDEX idx_trans_cat ON category_translation(product_category_name)",
]


def build(csv_dir: str, db_path: str) -> None:
    csv_dir = Path(csv_dir)
    missing = [f for f in TABLE_FILES.values() if not (csv_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing CSV files in {csv_dir}: {missing}")

    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    conn = sqlite3.connect(db)
    for table, fname in TABLE_FILES.items():
        df = pd.read_csv(csv_dir / fname, dtype=str, keep_default_na=False, na_values=[""])
        for col, kind in NUMERIC.get(table, {}).items():
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if kind == "int":
                df[col] = df[col].astype("Int64")
        df.to_sql(table, conn, index=False)
        print(f"{table:22s} {len(df):>9,} rows")
    for stmt in INDEXES:
        conn.execute(stmt)
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    print(f"Built {db}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default="data/olist")
    ap.add_argument("--db", default="data/olist.db")
    a = ap.parse_args()
    build(a.csv_dir, a.db)
