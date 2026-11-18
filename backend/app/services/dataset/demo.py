"""Synthetic retail dataset (clearly labelled as demonstration data). Reproducible with a fixed seed.

It is generated as a CSV file and imported through the same ingestion pipeline as user uploads.
Deliberate characteristics so every product capability has something real to find:
  * 24 months of orders with growth and Nov/Dec seasonality
  * a profit decline in the final month concentrated in the West region (heavy discounting, fewer orders)
  * one product (Smart Watch) with promotion-driven, highly variable monthly sales
  * a handful of very large wholesale orders (outlier candidates)
  * small data-quality defects: missing customer IDs, missing discounts and duplicated rows"""
import csv
import io
from datetime import date, timedelta

import numpy as np

PRODUCTS = [  # product, category, unit price, cost ratio, popularity
    ("Wireless Earbuds", "Electronics", 79.0, 0.60, 1.4), ("Smart Watch", "Electronics", 199.0, 0.64, 0.9),
    ("Bluetooth Speaker", "Electronics", 59.0, 0.58, 1.0), ("Laptop Stand", "Electronics", 45.0, 0.52, 0.8),
    ("Espresso Maker", "Home & Kitchen", 249.0, 0.57, 0.7), ("Air Fryer", "Home & Kitchen", 129.0, 0.55, 1.3),
    ("Cookware Set", "Home & Kitchen", 179.0, 0.53, 0.6), ("Ceramic Vase", "Home & Kitchen", 39.0, 0.42, 0.7),
    ("Running Shoes", "Apparel", 95.0, 0.46, 1.1), ("Denim Jacket", "Apparel", 85.0, 0.44, 0.7),
    ("Wool Scarf", "Apparel", 29.0, 0.38, 0.6), ("Cotton T-Shirt", "Apparel", 19.0, 0.35, 1.2),
    ("Ergonomic Chair", "Office", 329.0, 0.61, 0.5), ("Desk Lamp", "Office", 49.0, 0.50, 0.8),
    ("Notebook Pack", "Office", 15.0, 0.40, 0.9), ("Skincare Set", "Beauty", 65.0, 0.36, 0.9),
    ("Hair Dryer", "Beauty", 89.0, 0.48, 0.6),
]
REGIONS = ["North", "South", "East", "West", "Central"]
REGION_W = [0.27, 0.17, 0.22, 0.22, 0.12]
CHANNELS = ["Online Store", "Marketplace", "Retail Store", "Wholesale"]
CHANNEL_W = [0.43, 0.28, 0.23, 0.06]
SEASON = {1: 0.85, 2: 0.82, 3: 0.95, 4: 0.97, 5: 1.0, 6: 0.98, 7: 0.96, 8: 1.0, 9: 1.04, 10: 1.0, 11: 1.25, 12: 1.38}
START, MONTHS = date(2024, 11, 1), 24
HEADER = ["Order ID", "Order Date", "Customer ID", "Product", "Category", "Region", "Sales Channel", "Quantity",
          "Unit Price", "Discount", "Gross Revenue", "Net Revenue", "Cost", "Profit"]


def _month_start(i: int) -> date:
    y, m = divmod(START.month - 1 + i, 12)
    return date(START.year + y, m + 1, 1)


def generate_rows(seed: int = 47) -> list[list]:
    rng = np.random.default_rng(seed)
    n_customers = 320
    cust_w = rng.pareto(1.6, n_customers) + 0.15
    cust_w /= cust_w.sum()
    pop = np.array([p[4] for p in PRODUCTS])
    rows, order_no = [], 10000
    for i in range(MONTHS):
        ms = _month_start(i)
        nxt = _month_start(i + 1)
        days = (nxt - ms).days
        last = i == MONTHS - 1
        base = 54 * (1 + 0.012 * i) * SEASON[ms.month]
        n = int(rng.poisson(base))
        smartwatch_boost = 3.2 if ms.month in (11, 3) or (i % 7 == 2) else 0.35  # promotion-driven spikes
        weights = pop.copy()
        weights[1] *= smartwatch_boost
        weights /= weights.sum()
        reg_w = np.array(REGION_W)
        if last:  # fewer West orders in the final month
            reg_w[3] *= 0.55
        reg_w /= reg_w.sum()
        for _ in range(n):
            order_no += 1
            p = PRODUCTS[rng.choice(len(PRODUCTS), p=weights)]
            region = REGIONS[rng.choice(5, p=reg_w)]
            channel = CHANNELS[rng.choice(4, p=CHANNEL_W)]
            qty = int(rng.integers(5, 11)) if channel == "Wholesale" else int(rng.choice([1, 1, 1, 2, 2, 3, 4]))
            price = round(p[2] * float(rng.uniform(0.96, 1.04)), 2)
            disc = float(rng.choice([0, 0, 0.05, 0.05, 0.10, 0.15]))
            if channel == "Wholesale":
                disc = max(disc, 0.12)
            if last and region == "West":  # aggressive clearance discounting
                disc = float(rng.choice([0.35, 0.40, 0.45]))
            unit_cost = p[2] * p[3]
            gross = round(qty * price, 2)
            net = round(gross * (1 - disc), 2)
            cost = round(qty * unit_cost * float(rng.uniform(0.97, 1.03)), 2)
            d = ms + timedelta(days=int(rng.integers(0, days)))
            cust = f"C{1000 + int(rng.choice(n_customers, p=cust_w))}"
            rows.append([f"SO-{order_no}", d.isoformat(), cust, p[0], p[1], region, channel, qty, price, disc,
                         gross, net, cost, round(net - cost, 2)])
    # Very large wholesale orders: genuine outlier candidates
    for k, idx in enumerate(rng.choice(len(rows), 4, replace=False)):
        r = rows[idx]
        qty = int(rng.integers(45, 70))
        price = PRODUCTS[[p[0] for p in PRODUCTS].index(r[3])][2]
        cost_ratio = PRODUCTS[[p[0] for p in PRODUCTS].index(r[3])][3]
        r[6], r[7], r[9] = "Wholesale", qty, 0.18
        r[10] = round(qty * r[8], 2)
        r[11] = round(r[10] * (1 - 0.18), 2)
        r[12] = round(qty * price * cost_ratio, 2)
        r[13] = round(r[11] - r[12], 2)
    # Data-quality defects
    for idx in rng.choice(len(rows), 11, replace=False):
        rows[idx][2] = ""
    for idx in rng.choice(len(rows), 6, replace=False):
        rows[idx][9] = ""
    rows.sort(key=lambda r: (r[1], r[0]))
    for idx in rng.choice(len(rows), 3, replace=False):
        rows.insert(int(idx) + 1, list(rows[int(idx)]))
    return rows


def generate_csv(seed: int = 47) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    w.writerows(generate_rows(seed))
    return buf.getvalue().encode("utf-8")
