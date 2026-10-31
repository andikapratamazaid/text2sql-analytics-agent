# Data

Nothing here is committed (see `.gitignore`).

1. Download **Brazilian E-Commerce Public Dataset by Olist** from Kaggle (`olistbr/brazilian-ecommerce`) and unzip the CSV files into `data/olist/`. Check the dataset page for its current license.
2. Build the SQLite database the agent queries:

```bash
python scripts/build_db.py --csv-dir data/olist --db data/olist.db
```

The loader uses short table names (`customers`, `orders`, `order_items`, `order_payments`, `order_reviews`, `products`, `sellers`, `category_translation`) and adds indexes so joins stay fast.
