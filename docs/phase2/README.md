# Phase 2: Rule-Based Flip Scanner

This guide walks you through building the rule-based scanner step by step. It explains **what** each piece does and **why**, so you can implement it yourself and actually understand the system.

You will build 3 things:
1. A feature builder that turns raw price snapshots into useful signals
2. A scanner that applies explicit rules to find profitable flip opportunities
3. A backtester that validates the scanner against historical data

---

## Prerequisites

Before starting Phase 2, make sure:
- Phase 1 is running and collecting data (a few days of data minimum)
- You can query your database and see rows in `prices_5min` and `items`

### Libraries you'll need

These should already be in your `pyproject.toml` from Phase 1:

```toml
pandas = "^2.2"
numpy = "^1.26"
```

If not, add them:
```bash
poetry add pandas numpy
```

**What are these?**
- `pandas` — the main library for working with tabular data (think: spreadsheets in Python)
- `numpy` — math operations on arrays (pandas uses this under the hood)

---

## Project Structure

Build this inside `packages/engine/`:

```
packages/engine/
├── __init__.py
├── features/
│   ├── __init__.py
│   └── builder.py          # Computes derived signals from raw data
├── flipper/
│   ├── __init__.py
│   ├── scanner.py           # Applies rules to find flip opportunities
│   └── backtester.py        # Validates the scanner against historical data
└── main.py                  # Entry point: --mode scan | --mode backtest
```

Create all `__init__.py` files as empty files. Python needs them to recognize folders as packages.

---

## Step 1: Load Data from the Database

Your first task is pulling raw price data out of the database and into a pandas DataFrame.

**File:** `packages/engine/features/builder.py`

```python
import pandas as pd
import numpy as np
from packages.collector.db.connection import DatabaseConnection
```

### What to implement

Write a function called `load_raw_data` that:
1. Creates a `DatabaseConnection`
2. Runs a SQL query to pull all rows from `prices_5min`
3. Returns the result as a `pd.DataFrame` with columns: `time`, `item_id`, `avg_high_price`, `avg_low_price`, `high_volume`, `low_volume`

**Hints:**
- Use `db.execute_query()` to run your SQL
- `pd.DataFrame(rows, columns=[...])` converts a list of tuples into a DataFrame
- Sort by `item_id` then `time` — this is critical for all later steps

---

## Step 2: Build Base Features

Compute the first layer of derived signals from the raw columns.

### What to implement

Write a function called `add_base_features` that adds these columns:

```python
df["mid_price"] = (df["avg_high_price"] + df["avg_low_price"]) / 2
df["spread"] = df["avg_high_price"] - df["avg_low_price"]
df["volume_total"] = df["high_volume"] + df["low_volume"]
df["spread_pct"] = df["spread"] / df["mid_price"]
df["volume_imbalance"] = (df["high_volume"] - df["low_volume"]) / df["volume_total"]
```

**What these mean:**
- `spread` — the raw flip margin before tax. If `avg_high` is 1000 and `avg_low` is 950, the spread is 50gp
- `spread_pct` — normalizes spread across items of different price. A 50gp spread means different things for a 500gp item vs a 50,000gp item
- `volume_imbalance` — positive means more buying than selling (bullish), negative means more selling (bearish)

**Watch out for:** Division by zero. If `volume_total` is 0, `volume_imbalance` will be `NaN`. That's okay — we handle it when cleaning.

---

## Step 3: Build Lag Features

Lag features capture what happened at previous time steps. "What was the spread 5 periods ago?"

### The key pandas method

```python
# shift(n) moves the column down by n rows within each item group
df["price_lag1"] = df.groupby("item_id")["mid_price"].shift(1)
```

**Critical:** Always use `.groupby("item_id")` before `.shift()`. Without it, item A's last price becomes item B's lag — completely wrong.

### What to implement

Write a function called `add_lag_features`:

| Feature | Code |
|---------|------|
| `price_lag1`, `price_lag5`, `price_lag10`, `price_lag20` | `groupby("item_id")["mid_price"].shift(n)` |
| `volume_lag1`, `volume_lag5` | `groupby("item_id")["volume_total"].shift(n)` |
| `spread_lag1`, `spread_lag5` | `groupby("item_id")["spread"].shift(n)` |

Also compute **return features** — how much did the price change?

```python
df["return_1"] = (df["mid_price"] - df["price_lag1"]) / df["price_lag1"]
```

**Why returns?** A 100gp change means different things for a 500gp vs 500,000gp item. Returns (percentages) are comparable.

---

## Step 4: Build Rolling Features

Rolling features compute statistics over a sliding window.

### The key pandas method

```python
df["ma_20"] = df.groupby("item_id")["mid_price"].transform(
    lambda x: x.rolling(window=20).mean()
)
```

**What's happening here:**
1. `groupby("item_id")` — process each item separately
2. `.transform(lambda x: x.rolling(20).mean())` — 20-period rolling average per item
3. `.transform()` returns results aligned back to the original DataFrame

### What to implement

Write a function called `add_rolling_features`:

**Moving averages:**
- `ma_5`, `ma_20` — rolling mean of `mid_price`

**Trend signals:**
- `price_vs_ma5 = mid_price / ma_5` — is price above or below short-term average?
- `ma5_vs_ma20 = ma_5 / ma_20` — crossover signal

**Spread stability — the most important rolling feature:**
```python
spread_mean = df.groupby("item_id")["spread"].transform(lambda x: x.rolling(20).mean())
spread_std  = df.groupby("item_id")["spread"].transform(lambda x: x.rolling(20).std())
df["spread_cv"] = spread_std / spread_mean  # coefficient of variation
```

`spread_cv` is critical for the scanner. A low value (e.g. 0.1) means the spread is consistent — what you see is what you get. A high value (e.g. 0.8) means the spread jumps around — unreliable.

**Volume baseline:**
- `volume_ma20` — rolling mean of `volume_total`

---

## Step 5: Clean the Data

Before scanning, handle missing values:

```python
df = df.dropna()
```

**Why rows are missing:** The first N rows per item won't have enough history for rolling features. `ma_20` needs 20 prior rows. These `NaN` rows are expected — drop them.

---

## Step 6: Build the Scanner

**File:** `packages/engine/flipper/scanner.py`

The scanner is the core of Phase 2. It takes the latest price snapshot (one row per item) and applies a series of filters to find profitable opportunities.

### Constants

Define these at the top of `scanner.py`. Adjust them as you learn what works:

```python
MIN_VOLUME = 100              # Items trading fewer than this per 5min are illiquid
HIGH_VOLUME_THRESHOLD = 5000  # High-volume items get stricter margin requirements
MAX_SPREAD_CV = 0.80          # Reject items where spread is too unstable
MIN_MARGIN_PCT = 0.01         # Minimum 1% net margin after tax (high-vol items)
GE_TAX = 0.02                 # 2% tax on the sell side
TOP_N = 20                    # Number of results to return
```

**Why named constants instead of magic numbers?**
If you write `if volume_total >= 100` in 5 places and want to change the threshold, you have to find and edit 5 places. A named constant changes everywhere at once.

### The `scan()` function

Write a function called `scan(df, item_names)` that:

**Step 1 — Get the latest snapshot (one row per item):**
```python
latest = df.sort_values("time").groupby("item_id").tail(1)
```

**Step 2 — Volume filter:**
```python
latest = latest[latest["volume_total"] >= MIN_VOLUME]
```
Items with low volume are risky — your buy order might sit unfilled for hours.

**Step 3 — Stability filter:**
```python
latest = latest[latest["spread_cv"] <= MAX_SPREAD_CV]
```
High `spread_cv` means the margin you see now may not be there when your offer fills. Filter these out.

**Step 4 — Compute real profit after GE tax:**
```python
import math

latest["tax"] = latest["avg_high_price"].apply(lambda p: min(math.floor(p * GE_TAX), 5_000_000))
latest["profit_per_unit"] = latest["spread"] - latest["tax"]
latest["margin_pct"] = latest["profit_per_unit"] / latest["avg_high_price"]
```

**Why is tax on `avg_high_price` not `spread`?** GE tax is 2% of the sell price, not the profit. On a 1,000gp item you pay 20gp tax even if your spread is only 30gp — leaving only 10gp profit. This is why many items look profitable but aren't.

**Step 5 — Margin filter:**
```python
# High-volume items face more competition — require a larger margin
high_vol = latest["volume_total"] >= HIGH_VOLUME_THRESHOLD
min_margin = MIN_MARGIN_PCT
low_margin = MIN_MARGIN_PCT / 2

latest = latest[
    (high_vol & (latest["margin_pct"] >= min_margin)) |
    (~high_vol & (latest["margin_pct"] >= low_margin))
]
```

**Step 6 — Compute recommended prices:**
```python
latest["recommended_bid"] = latest["avg_low_price"] - 1   # Undercut existing buy orders by 1gp
latest["recommended_ask"] = latest["avg_high_price"] + 1  # Beat existing sell orders by 1gp
```

**Step 7 — Rank and return top N:**
```python
return latest.sort_values("margin_pct", ascending=False).head(TOP_N)
```

---

## Step 7: Build the Backtester

**File:** `packages/engine/flipper/backtester.py`

Before trusting the scanner with real GP, validate it against historical data.

### What a backtest does

It replays history: for each time step in the past, run the scanner, simulate buying the recommended items, then simulate selling them later. Track whether the total capital grew or shrank.

### Key simulation constraints

These are critical — without them, backtest results will be misleadingly optimistic:

| Constraint | Why |
|-----------|-----|
| **GE buy limit** | Each item has a limit per 4 hours (stored in `items.buy_limit`). You can't buy more than this. |
| **4-hour cooldown** | After hitting the buy limit, track a `last_buy_time` per item. Don't allow re-buying until 4 hours have passed. |
| **Capital tracking** | Track current available GP. Don't buy what you can't afford. Buying locks up capital; selling returns it + profit. |
| **GE tax on every sale** | Deduct `min(floor(sell_price * 0.02), 5_000_000)` from every sale |

### Data structure for open positions

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Position:
    item_id: int
    buy_price: int
    quantity: int
    buy_time: datetime
```

### The simulation loop

```python
for timestamp in sorted_timestamps:
    # 1. Get current price snapshot
    snapshot = df[df["time"] == timestamp]

    # 2. Run scanner on this snapshot
    candidates = scan(snapshot, item_names)

    # 3. Try to open new positions
    for _, row in candidates.iterrows():
        if capital < row["recommended_bid"] * row["buy_limit"]:
            continue  # Can't afford
        if cooldown_active(row["item_id"], timestamp):
            continue  # Buy limit cooldown not expired

        # Open position
        qty = min(row["buy_limit"], capital // row["recommended_bid"])
        capital -= qty * row["recommended_bid"]
        open_positions.append(Position(...))
        record_buy_time(row["item_id"], timestamp)

    # 4. Close positions where we can now sell at a profit
    for position in list(open_positions):
        current_price = get_current_ask(snapshot, position.item_id)
        if current_price and current_price >= position.buy_price:
            tax = min(math.floor(current_price * 0.02), 5_000_000)
            profit = (current_price - position.buy_price - tax) * position.quantity
            capital += current_price * position.quantity - tax * position.quantity
            open_positions.remove(position)
```

### Metrics to report

```
Total profit: X GP
Completed flips: N
Win rate: X%
Max drawdown: X GP
Starting capital: Y GP
Ending capital: Z GP
```

---

## Step 8: Entry Point

**File:** `packages/engine/main.py`

Wire everything together with a CLI:

```python
import argparse
import logging

from packages.engine.features.builder import load_raw_data, add_base_features, add_lag_features, add_rolling_features, add_time_features, clean
from packages.engine.flipper.scanner import scan
from packages.engine.flipper.backtester import run_backtest
from packages.collector.db.connection import DatabaseConnection

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scan", "backtest"], required=True)
    parser.add_argument("--days", type=int, default=14, help="Days of history for backtest")
    args = parser.parse_args()

    db = DatabaseConnection()
    df = load_raw_data(db)
    df = add_base_features(df)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    df = clean(df)

    if args.mode == "scan":
        results = scan(df, item_names={})
        print(results[["item_id", "recommended_bid", "recommended_ask", "profit_per_unit", "margin_pct"]].to_string())

    elif args.mode == "backtest":
        run_backtest(df, days=args.days)

if __name__ == "__main__":
    main()
```

**Run it:**
```bash
python -m packages.engine.main --mode scan
python -m packages.engine.main --mode backtest --days 14
```

---

## Order of Implementation

Don't try to build everything at once. Follow this order:

1. **`builder.py`** — Load data, verify with `print(df.head())`
2. **Add base features** — Verify `spread` and `mid_price` columns look correct
3. **Add lag features** — Verify `price_lag1` matches `mid_price` shifted by 1 within each item
4. **Add rolling features** — Verify `spread_cv` is computed and has reasonable values (0.0–1.5)
5. **`scanner.py`** — Run it, manually inspect top 20 results. Do they make sense?
6. **`backtester.py`** — Run 14-day backtest, verify capital tracking (no negative capital, no double-counting)
7. **Tune constants** — Adjust `MIN_VOLUME`, `MAX_SPREAD_CV`, `MIN_MARGIN_PCT` based on what the backtest shows

At each step, verify the output makes sense before building on top of it.

---

## Common Mistakes to Avoid

- **Forgetting `groupby("item_id")`** on lag and rolling operations — mixes data between items. This is the #1 bug.
- **Not applying GE tax** — many items have negative profit after tax. Always subtract tax before ranking.
- **Not respecting buy limits** in the backtester — inflates profit unrealistically.
- **Double-counting capital recovery** — when a position closes, add back the sale proceeds once, not twice.
- **Using `NaN` spreads** — filter out rows where `avg_high_price` or `avg_low_price` is null before computing spread.
