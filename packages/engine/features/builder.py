import pandas as pd
import numpy as np
import logging
from pathlib import Path

from packages.collector.db.connection import DatabaseConnection

MODELS_DIR = Path(__file__).resolve().parents[2] / "engine" / "models"


def load_raw_data(db: DatabaseConnection) -> pd.DataFrame:
    data = db.execute_query("SELECT * FROM prices_5min")
    if data is None:
        logging.info("Failed to load raw prices data")
    data = pd.DataFrame(data, columns=["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"])
    return data


def add_base_features(df: pd.DataFrame) -> pd.DataFrame:
    df["mid_price"] = (df["avg_high_price"] + df["avg_low_price"]) / 2
    df["spread"] = df["avg_high_price"] - df["avg_low_price"]
    df["volume_total"] = df["high_volume"] + df["low_volume"]
    df["spread_pct"] = df["spread"] / df["mid_price"]
    df["volume_imbalance"] = (df["high_volume"] - df["low_volume"]) / df["volume_total"]
    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["item_id", "time"])

    for lag in [1, 5, 10, 20]:
        df[f"price_lag{lag}"] = df.groupby("item_id")["mid_price"].shift(lag)
        df[f"return_{lag}"] = (df["mid_price"] - df[f"price_lag{lag}"]) / df[f"price_lag{lag}"]

    for lag in [1, 5]:
        df[f"volume_lag{lag}"] = df.groupby("item_id")["volume_total"].shift(lag)
        df[f"spread_lag{lag}"] = df.groupby("item_id")["spread"].shift(lag)

    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    group = df.groupby("item_id")

    for window in [5, 20, 60]:
        df[f"ma_{window}"] = group["mid_price"].transform(lambda x: x.rolling(window).mean())
        df[f"volatility_{window}"] = group["return_1"].transform(lambda x: x.rolling(window).std())
        df[f"volume_ma{window}"] = group["volume_total"].transform(lambda x: x.rolling(window).mean())
        df[f"spread_ma{window}"] = group["spread"].transform(lambda x: x.rolling(window).mean())

    df["price_vs_ma5"] = df["mid_price"] / df["ma_5"]
    df["price_vs_ma20"] = df["mid_price"] / df["ma_20"]
    df["ma5_vs_ma20"] = df["ma_5"] / df["ma_20"]

    df["volume_ratio_5"] = df["volume_total"] / df["volume_ma5"]
    df["volume_ratio_20"] = df["volume_total"] / df["volume_ma20"]

    df["spread_change"] = df["spread"] - df["spread_lag1"]

    df["rolling_max_20"] = group["mid_price"].transform(lambda x: x.rolling(20).max())
    df["rolling_min_20"] = group["mid_price"].transform(lambda x: x.rolling(20).min())
    df["price_vs_max20"] = df["mid_price"] / df["rolling_max_20"]
    df["price_vs_min20"] = df["mid_price"] / df["rolling_min_20"]

    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df["hour"] = df["time"].dt.hour
    df["day_of_week"] = df["time"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna()
