# Phase 2: Feature Engineering & ML Model

This guide walks you through building the ML pipeline step by step. It explains **what** each piece does and **why**, so you can implement it yourself and actually learn.

You will build 4 things:
1. A feature engine that turns raw price data into useful signals
2. A training pipeline that teaches models to predict price movement
3. An evaluation system to measure if the models are any good
4. An inference service that runs predictions every 5 minutes

---

## Prerequisites

Before starting Phase 2, make sure:
- Phase 1 is running and collecting data (at least a few days of data helps)
- You can query your database and see rows in `prices_5min` and `items`

### Libraries you'll need

Add these to your `pyproject.toml` under `[tool.poetry.dependencies]`:

```toml
pandas = "^2.2"
numpy = "^1.26"
scikit-learn = "^1.4"
xgboost = "^2.0"
lightgbm = "^4.3"
joblib = "^1.3"
```

Then run:
```bash
poetry add pandas numpy scikit-learn xgboost lightgbm joblib
```

**What are these?**
- `pandas` — the main library for working with tabular data (think: spreadsheets in Python)
- `numpy` — math operations on arrays (pandas uses this under the hood)
- `scikit-learn` — machine learning toolkit with Random Forest, Logistic Regression, metrics, and data splitting
- `xgboost` — gradient boosted decision trees, the go-to for tabular prediction tasks
- `lightgbm` — Microsoft's gradient boosting library, faster than XGBoost on large datasets
- `joblib` — saves trained models to disk so you can load them later without retraining

---

## Project Structure

Build this inside `packages/engine/`:

```
packages/engine/
├── __init__.py
├── features/
│   ├── __init__.py
│   └── builder.py          # Computes all features from raw data
├── models/
│   ├── __init__.py
│   └── trainer.py           # Trains and compares models
├── evaluation/
│   ├── __init__.py
│   └── metrics.py           # Measures model performance
├── inference/
│   ├── __init__.py
│   └── predictor.py         # Runs predictions on live data
└── main.py                  # Entry point for training + inference
```

Create all the `__init__.py` files as empty files. Python needs them to recognize folders as packages.

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
2. Runs a SQL query to pull all rows from `prices_5min` — you need: `time`, `item_id`, `avg_high_price`, `avg_low_price`, `high_volume`, `low_volume`
3. Returns the result as a `pd.DataFrame`

**Hints:**
- Use `self.db.execute_query()` to run your SQL
- `pd.DataFrame(rows, columns=[...])` converts a list of tuples into a DataFrame
- Sort by `item_id` then `time` — this is critical for all later steps

**Why this matters:** Everything in Phase 2 starts from this DataFrame. If the data is loaded wrong or sorted wrong, every feature will be wrong.

---

## Step 2: Build Base Features

Now you'll compute the first layer of derived signals from the raw columns.

### What to implement

Write a function called `add_base_features` that takes a DataFrame and adds these columns:

```python
# These are the formulas — implement them as DataFrame operations
mid_price = (avg_high_price + avg_low_price) / 2
spread = avg_high_price - avg_low_price
volume_total = high_volume + low_volume
spread_pct = spread / mid_price
volume_imbalance = (high_volume - low_volume) / volume_total
```

**How to do this in pandas:**
```python
df["mid_price"] = (df["avg_high_price"] + df["avg_low_price"]) / 2
```

That's the pattern — each formula becomes one line of pandas code.

**Watch out for:** Division by zero. If `volume_total` is 0, `volume_imbalance` will be `NaN`. That's okay for now — we'll handle missing values later.

---

## Step 3: Build Lag Features

Lag features capture what happened at previous time steps. "What was the price 5 steps ago?"

### What to implement

Write a function called `add_lag_features` that adds lagged versions of key columns.

**The key pandas method:**
```python
# shift(n) moves the column down by n rows
# So shift(1) gives you the previous row's value
df["price_lag1"] = df.groupby("item_id")["mid_price"].shift(1)
```

**Critical:** Always use `.groupby("item_id")` before `.shift()`. Without it, lag values bleed between different items — item A's last price becomes item B's lag, which is completely wrong.

### Features to create

| Feature | Code pattern |
|---------|-------------|
| `price_lag1`, `price_lag5`, `price_lag10`, `price_lag20` | `groupby("item_id")["mid_price"].shift(n)` |
| `volume_lag1`, `volume_lag5` | `groupby("item_id")["volume_total"].shift(n)` |
| `spread_lag1`, `spread_lag5` | `groupby("item_id")["spread"].shift(n)` |

### Return features (momentum)

Once you have lags, compute returns — how much did the price change?

```python
df["return_1"] = (df["mid_price"] - df["price_lag1"]) / df["price_lag1"]
```

Same pattern for `return_5`, `return_10`, `return_20`.

**Why returns and not raw prices?** A 100gp price change means very different things for an item worth 500gp vs one worth 500,000gp. Returns normalize this — 10% is 10% regardless of item price.

---

## Step 4: Build Rolling Features

Rolling features compute statistics over a sliding window — "what was the average price over the last 20 periods?"

### The key pandas method

```python
# rolling(window) computes a statistic over the last N rows
# Always groupby item_id first
df["ma_5"] = df.groupby("item_id")["mid_price"].transform(
    lambda x: x.rolling(window=5).mean()
)
```

**What's happening here:**
1. `groupby("item_id")` — process each item separately
2. `.transform(lambda x: x.rolling(5).mean())` — for each item, compute a 5-period rolling average
3. `.transform()` returns the result aligned back to the original DataFrame index

### Features to create

**Moving averages:**
- `ma_5`, `ma_20`, `ma_60` — rolling mean of `mid_price`

**Trend signals (ratios of price to moving averages):**
- `price_vs_ma5 = mid_price / ma_5`
- `price_vs_ma20 = mid_price / ma_20`
- `ma5_vs_ma20 = ma_5 / ma_20`

**Volatility (rolling standard deviation of returns):**
- `volatility_5`, `volatility_20`, `volatility_60` — rolling std of `return_1`

**Volume rolling features:**
- `volume_ma5`, `volume_ma20` — rolling mean of `volume_total`
- `volume_ratio_5 = volume_total / volume_ma5`
- `volume_ratio_20 = volume_total / volume_ma20`

**Spread rolling features:**
- `spread_ma5`, `spread_ma20` — rolling mean of `spread`
- `spread_change = spread - spread_lag1`

**Breakout features:**
- `rolling_max_20` — rolling max of `mid_price` over 20 periods
- `rolling_min_20` — rolling min of `mid_price` over 20 periods
- `price_vs_max20 = mid_price / rolling_max_20`
- `price_vs_min20 = mid_price / rolling_min_20`

**Tip:** The pattern is always the same — just change `mean()` to `std()`, `max()`, or `min()`.

---

## Step 5: Time & Item Features

### Time features

Extract time components from the timestamp and encode them cyclically:

```python
import numpy as np

df["hour"] = df["time"].dt.hour
df["day_of_week"] = df["time"].dt.dayofweek
df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

# Cyclical encoding — tells the model hour 23 is close to hour 0
df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
```

**Why cyclical encoding?** Without it, the model thinks hour 0 and hour 23 are maximally far apart (23 units away). With sin/cos encoding, they're actually close — which matches reality (midnight and 11pm have similar player activity).

### Item-level features

These are computed once per item and merged back:

```python
item_stats = df.groupby("item_id").agg(
    item_avg_volume=("volume_total", "mean"),
    item_avg_spread=("spread", "mean"),
    item_volatility=("return_1", "std"),
    item_avg_price=("mid_price", "mean"),
)
df = df.merge(item_stats, on="item_id", how="left")
```

**Why item-level features?** They help the model understand that a "20% volume spike" means very different things for a highly-traded item vs a barely-traded one.

---

## Step 6: Create Target Variables

The target is what you're trying to predict. You compute it from future data, then the model learns to predict it from past features.

### What to implement

```python
# Regression target: what will the return be 5 periods from now?
df["future_return_5"] = df.groupby("item_id")["mid_price"].transform(
    lambda x: x.shift(-5)  # negative shift = look into the future
)
df["future_return_5"] = (df["future_return_5"] - df["mid_price"]) / df["mid_price"]

# Classification target: will the price go up?
THRESHOLD = 0.001  # 0.1% — tune this based on your data
df["target_up"] = (df["future_return_5"] > THRESHOLD).astype(int)
```

**Important:** `shift(-5)` looks **forward** in time. This is only used to create the target — the model never sees future data as an input feature. After creating targets, you must drop rows where the target is `NaN` (the last 5 rows per item won't have a target).

---

## Step 7: Clean the Data

Before training, handle missing values:

```python
# Drop rows where lag/rolling features are NaN (first ~60 rows per item)
df = df.dropna()
```

**Why rows are missing:** The first N rows per item don't have enough history for lag and rolling features. For example, `ma_60` needs 60 prior rows. These `NaN` rows are expected — just drop them.

---

## Step 8: Train/Test Split

**File:** `packages/engine/models/trainer.py`

```python
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression
import xgboost as xgb
import lightgbm as lgb
import joblib
```

### What to implement

Split the data by time — **never randomly**:

```python
# Sort by time first
df = df.sort_values("time")

# Find the split points
n = len(df)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

train = df.iloc[:train_end]
val = df.iloc[train_end:val_end]
test = df.iloc[val_end:]
```

**Why not random split?** Random splitting leaks future information into training. If a row from 2026-04-10 is in training and a row from 2026-04-09 is in validation, the model effectively has access to future data. Time-based splits prevent this.

### Define your feature columns

```python
# List every feature column — NOT the targets, NOT item_id, NOT time
FEATURE_COLUMNS = [
    "mid_price", "spread", "volume_total", "spread_pct", "volume_imbalance",
    "price_lag1", "price_lag5", "price_lag10", "price_lag20",
    "volume_lag1", "volume_lag5", "spread_lag1", "spread_lag5",
    "return_1", "return_5", "return_10", "return_20",
    "ma_5", "ma_20", "ma_60",
    "price_vs_ma5", "price_vs_ma20", "ma5_vs_ma20",
    "volatility_5", "volatility_20", "volatility_60",
    "volume_ma5", "volume_ma20", "volume_ratio_5", "volume_ratio_20",
    "spread_ma5", "spread_ma20", "spread_change",
    "rolling_max_20", "rolling_min_20", "price_vs_max20", "price_vs_min20",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend",
    "item_avg_volume", "item_avg_spread", "item_volatility", "item_avg_price",
]

TARGET_REGRESSION = "future_return_5"
TARGET_CLASSIFICATION = "target_up"

X_train = train[FEATURE_COLUMNS]
y_train = train[TARGET_REGRESSION]
```

Same pattern for `X_val`, `y_val`, `X_test`, `y_test`.

---

## Step 9: Train Models

### What to implement

Train each model and store it. Here's the pattern — each model follows the same `fit` / `predict` interface:

```python
# XGBoost
xgb_model = xgb.XGBRegressor(
    n_estimators=500,       # number of trees
    max_depth=6,            # how deep each tree can go
    learning_rate=0.05,     # how much each tree contributes
    subsample=0.8,          # use 80% of data per tree (reduces overfitting)
)
xgb_model.fit(X_train, y_train)

# LightGBM
lgb_model = lgb.LGBMRegressor(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
)
lgb_model.fit(X_train, y_train)

# Random Forest
from sklearn.ensemble import RandomForestRegressor
rf_model = RandomForestRegressor(n_estimators=200, max_depth=10)
rf_model.fit(X_train, y_train)
```

**What do these parameters mean?**
- `n_estimators` — how many decision trees to build. More trees = better up to a point, then just slower
- `max_depth` — how many "if/then" questions each tree can ask. Too deep = overfitting (memorizes training data). Too shallow = underfitting (too simple to learn patterns)
- `learning_rate` — how much each new tree corrects the previous ones. Lower = more trees needed but often better results
- `subsample` — each tree only sees a random 80% of the data, which prevents overfitting

**For the classification task** (predicting `target_up`), use the classifier versions:
- `xgb.XGBClassifier`, `lgb.LGBMClassifier`, `RandomForestClassifier`, `LogisticRegression`
- Same `.fit()` / `.predict()` interface, just swap the target to `target_up`

### Save your trained models

```python
joblib.dump(xgb_model, "packages/engine/models/xgb_regression.pkl")
```

Load later with `model = joblib.load("packages/engine/models/xgb_regression.pkl")`.

---

## Step 10: Evaluate Models

**File:** `packages/engine/evaluation/metrics.py`

```python
import numpy as np
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)
```

### What to implement

Write a function that takes a model, `X_val`, and `y_val`, and prints all the metrics:

**Regression metrics** (for `future_return_5`):
```python
predictions = model.predict(X_val)

mae = mean_absolute_error(y_val, predictions)       # Average error size
rmse = np.sqrt(mean_squared_error(y_val, predictions))  # Penalizes big errors more
```

**Directional accuracy** (does the model predict up/down correctly?):
```python
actual_direction = (y_val > 0).astype(int)
predicted_direction = (predictions > 0).astype(int)
dir_accuracy = accuracy_score(actual_direction, predicted_direction)
# Target: >55%
```

**Classification metrics** (for `target_up`):
```python
predictions = model.predict(X_val)
probabilities = model.predict_proba(X_val)[:, 1]  # probability of class 1

accuracy = accuracy_score(y_val, predictions)
precision = precision_score(y_val, predictions)
recall = recall_score(y_val, predictions)
f1 = f1_score(y_val, predictions)
auc = roc_auc_score(y_val, probabilities)
```

**What these mean in plain English:**
- **MAE** — "On average, the prediction is off by X%"
- **Directional accuracy** — "The model correctly predicts up vs down X% of the time"
- **Precision** — "When the model says 'buy', it's right X% of the time"
- **Recall** — "Of all the real opportunities, the model catches X%"
- **F1** — Balance between precision and recall
- **ROC-AUC** — Overall ranking quality. 0.5 = random guessing. >0.6 = useful

### Feature importance

This is one of the biggest advantages of tree-based models — you can see what matters:

```python
import pandas as pd

importance = pd.Series(
    xgb_model.feature_importances_,
    index=FEATURE_COLUMNS
).sort_values(ascending=False)

print(importance.head(20))  # Top 20 most important features
```

If `return_1` and `volume_imbalance` are top features, the model is learning reasonable patterns. If `hour_cos` is #1, something might be wrong.

---

## Step 11: Profit Backtesting

This is where you answer: "Would following this model actually make money?"

### What to implement

Write a simple backtester:

```python
def backtest(predictions, actuals, buy_threshold=0.002, sell_threshold=-0.002):
    """
    predictions: model's predicted future returns
    actuals: what actually happened
    buy_threshold: minimum predicted return to trigger a buy
    sell_threshold: maximum predicted return to trigger a sell
    """
    total_profit = 0
    trades = 0

    for pred, actual in zip(predictions, actuals):
        if pred > buy_threshold:
            # Model says price will go up — buy
            total_profit += actual  # actual return is our profit/loss
            trades += 1
        elif pred < sell_threshold:
            # Model says price will go down — sell (short)
            total_profit -= actual
            trades += 1

    return total_profit, trades
```

**What to track:**
- `total_profit` — sum of returns from all trades
- `trades` — how many trades were made (too few = not useful, too many = high transaction costs)
- `max_drawdown` — worst peak-to-trough decline (how bad can it get?)

**Compare against baselines:**
- Random trading (pick random items to buy)
- Buy-and-hold (just hold everything)
- If your model can't beat these, the features need more work

---

## Step 12: Inference Service

**File:** `packages/engine/inference/predictor.py`

This runs every 5 minutes, computing predictions for all ~4,000 items.

```python
import logging
from datetime import datetime, timezone

import joblib
import pandas as pd

from packages.collector.db.connection import DatabaseConnection
from packages.engine.features.builder import FeatureBuilder
```

### What to implement

Write a class `PredictionService` that:

1. **Loads the trained model** from disk on startup:
   ```python
   self.model = joblib.load("packages/engine/models/best_model.pkl")
   ```

2. **Pulls the latest data window** — you only need the last ~60 rows per item (enough for `ma_60`):
   ```sql
   SELECT * FROM prices_5min
   WHERE time > NOW() - INTERVAL '6 hours'
   ORDER BY item_id, time
   ```

3. **Computes features** using the same `FeatureBuilder` from training — this is critical. If you compute features differently during inference vs training, predictions will be garbage.

4. **Runs predictions** on the latest row per item:
   ```python
   latest = df.groupby("item_id").tail(1)
   predictions = self.model.predict(latest[FEATURE_COLUMNS])
   ```

5. **Stores predictions** in a new database table:
   ```sql
   CREATE TABLE predictions (
       time            TIMESTAMPTZ NOT NULL,
       item_id         INTEGER NOT NULL,
       predicted_return FLOAT,
       predicted_fill_prob FLOAT
   );
   ```

### Running on a loop

Your entry point should run prediction every 5 minutes:

```python
import time

PREDICTION_INTERVAL = 300  # 5 minutes

while True:
    service.predict_all()
    time.sleep(PREDICTION_INTERVAL)
```

---

## Step 13: Putting It All Together

**File:** `packages/engine/main.py`

```python
import logging
import argparse

from packages.engine.features.builder import FeatureBuilder
from packages.engine.models.trainer import ModelTrainer
from packages.engine.evaluation.metrics import evaluate_model
from packages.engine.inference.predictor import PredictionService
```

### What to implement

Create a `main.py` that supports two modes:

```bash
# Train mode — build features, train models, evaluate, save best
python -m packages.engine.main --mode train

# Inference mode — load model, run predictions on loop
python -m packages.engine.main --mode inference
```

Use `argparse` to parse the `--mode` argument:

```python
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["train", "inference"], required=True)
args = parser.parse_args()
```

**Train mode flow:**
1. Load raw data → build features → create targets
2. Time-based split
3. Train all 4 models
4. Evaluate each on validation set, print comparison table
5. Save the best model to disk

**Inference mode flow:**
1. Load saved model
2. Run prediction loop every 5 minutes

---

## Step 14: Docker Deployment

Once your engine works locally, containerize it so it runs alongside your collector.

### Add the predictions table to schema.sql

**File:** `packages/collector/db/schema.sql` — add at the bottom:

```sql
CREATE TABLE IF NOT EXISTS predictions (
    time                  TIMESTAMPTZ NOT NULL,
    item_id               INTEGER NOT NULL,
    predicted_return       DOUBLE PRECISION,
    predicted_fill_prob    DOUBLE PRECISION
);

SELECT create_hypertable('predictions', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => true);
CREATE INDEX IF NOT EXISTS idx_predictions_item_time ON predictions (item_id, time DESC);
```

### Create a Dockerfile for the engine

**File:** `Dockerfile.engine`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for LightGBM and psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc libgomp1 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml poetry.lock* ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --only main --no-root

# Copy source code
COPY packages/engine ./packages/engine
COPY packages/collector/db ./packages/collector/db

# Default to inference mode
CMD ["python", "-m", "packages.engine.main", "--mode", "inference"]
```

**Key differences from the collector Dockerfile:**
- `libgomp1` — LightGBM needs OpenMP for parallel tree building
- Copies `packages/collector/db` — the engine needs `DatabaseConnection` and `schema.sql`
- Default CMD runs inference, but you can override for training

### Add the engine to docker-compose.yml

Add this service block to your existing `docker-compose.yml`:

```yaml
  engine:
    build:
      context: .
      dockerfile: Dockerfile.engine
    container_name: gept-engine
    depends_on:
      db:
        condition: service_healthy
    environment:
      DB_HOST: db
      DB_PORT: "5432"
      DB_NAME: ${DB_NAME}
      DB_USER: ${DB_USER}
      DB_PASS: ${DB_PASS}
    restart: unless-stopped
```

### Running training in Docker

You don't want the training process running on a loop — it's a one-time job. Override the CMD:

```bash
# Train the model (one-time)
docker-compose run --rm engine python -m packages.engine.main --mode train

# Start inference (runs continuously)
docker-compose up engine
```

`docker-compose run --rm` starts a temporary container, runs the command, and removes the container when done. The `--rm` flag prevents dead containers from piling up.

### Full deployment workflow

```bash
# 1. Make sure the database and collectors are running
docker-compose up -d db collectors

# 2. Wait until you have enough data (a few days minimum)

# 3. Train the model
docker-compose run --rm engine python -m packages.engine.main --mode train

# 4. Start the inference service
docker-compose up -d engine

# 5. Verify predictions are being stored
#    Connect DBeaver to localhost:5432, check the predictions table
```

### Environment parity

The most common deployment bug: code works locally but breaks in Docker. To prevent this:

- **Same Python version** — both Dockerfiles use `python:3.12-slim`
- **Same dependencies** — both read from the same `pyproject.toml`
- **Same feature code** — inference imports the same `FeatureBuilder` class used in training
- **Same database connection** — both use `DatabaseConnection` with env vars

If you train locally and deploy to Docker (or vice versa), make sure the model file (`.pkl`) was trained on the same feature set that inference will compute. If you add a feature and retrain, you must also redeploy the inference container.

---

## Order of Implementation

Don't try to build everything at once. Follow this order:

1. **`builder.py`** — Load data, add base features, verify with `print(df.head())`
2. **Add lag features** — Verify with `print(df[["item_id", "time", "mid_price", "price_lag1"]].head(20))`
3. **Add rolling features** — Same verification pattern
4. **Add time + item features** — Verify
5. **Create targets** — Verify `future_return_5` makes sense (should be small decimals like 0.002, -0.001)
6. **`trainer.py`** — Train one model first (XGBoost). Get it working end-to-end before adding others
7. **`metrics.py`** — Evaluate that one model. Is directional accuracy >55%?
8. **Add remaining models** — Train all 4, compare
9. **Backtesting** — Does the best model make theoretical profit?
10. **`predictor.py`** — Run inference locally, verify predictions appear in DB
11. **Dockerize** — Dockerfile.engine + docker-compose addition

At each step, run the code and verify the output makes sense before moving on. If `ma_60` is all `NaN`, you have a bug — don't keep building on top of it.

---

## Common Mistakes to Avoid

- **Forgetting `groupby("item_id")`** — Lag and rolling operations without groupby will mix data between items. This is the #1 bug.
- **Using random split instead of time-based** — Leaks future data into training. Your metrics will look amazing but the model won't work in production.
- **Training on data with NaN values** — XGBoost handles NaN natively, but it can mask bugs. Drop NaN rows during development so you can verify feature correctness.
- **Different features in training vs inference** — If you rename or add a column in `builder.py`, both the trainer and predictor must use the updated version.
- **Overfitting to the validation set** — If you keep tuning parameters to improve validation metrics, you're effectively memorizing the validation data. The test set is your final reality check — only evaluate on it once.
