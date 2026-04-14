import pandas as pd
import numpy as np
import logging
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[2] / "engine" /"models"

from sklearn.metrics import mean_absolute_error, accuracy_score

from packages.collector import db
from packages.collector.db.connection import DatabaseConnection

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression
import xgboost as xgb
import lightgbm as lgb
import joblib


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

THRESHOLD = 0.001  # 0.1% — tune this based on your data
TARGET_REGRESSION = "future_return_5"
TARGET_CLASSIFICATION = "target_up"


# XGBoost
xgb_model = xgb.XGBRegressor(
    n_estimators=500,       # number of trees
    max_depth=6,            # how deep each tree can go
    learning_rate=0.05,     # how much each tree contributes
    subsample=0.8,          # use 80% of data per tree (reduces overfitting)
)

# LightGBM
lgb_model = lgb.LGBMRegressor(
    n_estimators=500,
    num_leaves=64,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.7,
    verbosity=-1
)

# rf_model = RandomForestRegressor(n_estimators=200, max_depth=10)

def load_raw_data(db: DatabaseConnection) -> pd.DataFrame:

    data = db.execute_query("SELECT * FROM prices_5min")
    if data is None:
        logging.info("Failed to load raw prices data")
    data = pd.DataFrame(data, columns=["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"])
    return data

def add_base_features(df: pd.DataFrame) -> pd.DataFrame:

    df["mid_price"] = (df["avg_high_price"] + df["avg_low_price"]) / 2
    df["spread"] = (df["avg_high_price"] - df["avg_low_price"])
    df["volume_total"] = df["high_volume"] + df["low_volume"]
    df["spread_pct"] = df["spread"] / df["mid_price"]
    df["volume_imbalance"] = (df["high_volume"] - df["low_volume"]) / df["mid_price"]
    return df

def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:

    df = df.sort_values(["item_id", "time"])

    price_lag = [1,5,10,20]
    volume_lag = [1,5]
    spread_lag = [1,5]

    for lag in price_lag:
        df[f"price_lag{lag}"] = df.groupby("item_id")["mid_price"].shift(lag)
        df[f"return_{lag}"] = (df["mid_price"] - df[f"price_lag{lag}"]) / df[f"price_lag{lag}"]

    for lag in volume_lag:
        df[f"volume_lag{lag}"] = df.groupby("item_id")["volume_total"].shift(lag)

    for lag in spread_lag:
        df[f"spread_lag{lag}"] = df.groupby("item_id")["spread"].shift(lag)

    return df

def rolling_features(df: pd.DataFrame) -> pd.DataFrame:

    g = df.groupby("item_id")

    # Moving averages
    df["ma_5"] = g["mid_price"].transform(lambda x: x.rolling(5).mean())
    df["ma_20"] = g["mid_price"].transform(lambda x: x.rolling(20).mean())
    df["ma_60"] = g["mid_price"].transform(lambda x: x.rolling(60).mean())

    # Trend signals
    df["price_vs_ma5"] = df["mid_price"] / df["ma_5"]
    df["price_vs_ma20"] = df["mid_price"] / df["ma_20"]
    df["ma5_vs_ma20"] = df["ma_5"] / df["ma_20"]

    # Volatility (rolling std of 1-period return)
    df["volatility_5"] = g["return_1"].transform(lambda x: x.rolling(5).std())
    df["volatility_20"] = g["return_1"].transform(lambda x: x.rolling(20).std())
    df["volatility_60"] = g["return_1"].transform(lambda x: x.rolling(60).std())

    # Volume rolling features
    df["volume_ma5"] = g["volume_total"].transform(lambda x: x.rolling(5).mean())
    df["volume_ma20"] = g["volume_total"].transform(lambda x: x.rolling(20).mean())
    df["volume_ratio_5"] = df["volume_total"] / df["volume_ma5"]
    df["volume_ratio_20"] = df["volume_total"] / df["volume_ma20"]

    # Spread rolling features
    df["spread_ma5"] = g["spread"].transform(lambda x: x.rolling(5).mean())
    df["spread_ma20"] = g["spread"].transform(lambda x: x.rolling(20).mean())
    df["spread_change"] = df["spread"] - df["spread_lag1"]

    # Breakout features
    df["rolling_max_20"] = g["mid_price"].transform(lambda x: x.rolling(20).max())
    df["rolling_min_20"] = g["mid_price"].transform(lambda x: x.rolling(20).min())
    df["price_vs_max20"] = df["mid_price"] / df["rolling_max_20"]
    df["price_vs_min20"] = df["mid_price"] / df["rolling_min_20"]

    return df

def time_features(df: pd.DataFrame) -> pd.DataFrame:

    df["hour"] = df["time"].dt.hour
    df["day_of_week"] = df["time"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    # Cyclical encoding — tells the model hour 23 is close to hour 0
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    item_stats = df.groupby("item_id").agg(
        item_avg_volume=("volume_total", "mean"),
        item_avg_spread=("spread", "mean"),
        item_volatility=("return_1", "std"),
        item_avg_price=("mid_price", "mean"),
    )
    df = df.merge(item_stats, on="item_id", how="left")

    return df

def target_features(df: pd.DataFrame) -> pd.DataFrame:
    # Regression target: what will the return be 5 periods from now?
    df["future_return_5"] = df.groupby("item_id")["mid_price"].transform(
        lambda x: x.shift(-5)  # negative shift = look into the future
    )
    df["future_return_5"] = (df["future_return_5"] - df["mid_price"]) / df["mid_price"]

    # Classification target: will the price go up?
    df["target_up"] = (df["future_return_5"] > THRESHOLD).astype(int)
    return df

def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna()
    return df

def train(df: pd.DataFrame) -> None:
    from packages.engine.evaluation.metrics import (
        evaluate_regression,
        evaluate_feature_importance,
        backtest,
    )

    df = df.sort_values("time")

    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    train_df = df.iloc[:train_end]
    val_df = df.iloc[train_end:val_end]
    test_df = df.iloc[val_end:]

    x_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_REGRESSION]
    x_val = val_df[FEATURE_COLUMNS]
    y_val = val_df[TARGET_REGRESSION]
    x_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_REGRESSION]

    models = {
        "XGBoost": xgb_model,
        "LightGBM": lgb_model,
        # "RandomForest": rf_model,
    }

    best_model = None
    best_dir_accuracy = 0.0

    logging.info("=== Validation Set Metrics ===")
    for name, model in models.items():
        model.fit(x_train, y_train)
        metrics = evaluate_regression(name, model, x_val, y_val)
        if metrics["dir_accuracy"] > best_dir_accuracy:
            best_dir_accuracy = metrics["dir_accuracy"]
            best_model = (name, model)

    if best_model:
        name, model = best_model
        logging.info(f"\n=== Best Model: {name} ===")

        logging.info("--- Test Set Metrics ---")
        evaluate_regression(name, model, x_test, y_test)

        logging.info("--- Feature Importance (top 20) ---")
        evaluate_feature_importance(name, model, FEATURE_COLUMNS)

        logging.info("--- Backtest on Test Set ---")
        test_predictions = model.predict(x_test)
        item_names_rows = DatabaseConnection().execute_query("SELECT item_id, name FROM items")
        item_names = {row[0]: row[1] for row in item_names_rows}
        backtest(
            test_predictions,
            y_test.to_numpy(),
            buy_prices=test_df["avg_high_price"].to_numpy(),
            times=test_df["time"].to_numpy(),
            item_ids=test_df["item_id"].to_numpy(),
            item_names=item_names,
            trading_days=7,
        )

        joblib.dump(model, MODELS_DIR / "best_model.pkl")
        logging.info(f"Saved to {MODELS_DIR / 'best_model.pkl'}")

def test():
    db = DatabaseConnection()
    data = load_raw_data(db)
    data = add_base_features(data)
    data = add_lag_features(data)
    data = rolling_features(data)
    data = time_features(data)
    data = target_features(data)
    data = clean(data)
    train(data)
    return data

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    raw_data = test()
