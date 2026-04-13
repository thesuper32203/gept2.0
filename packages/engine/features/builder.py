import pandas as pd
import numpy as np
import logging
from packages.collector.db.connection import DatabaseConnection

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
    df["volume_imbalance"] = df["volume_total"] / df["mid_price"]
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


def test():
    db = DatabaseConnection()
    data = load_raw_data(db)
    data = add_base_features(data)
    data = add_lag_features(data)
    return data

if __name__ == "__main__":
    raw_data = test()
    print(raw_data.columns)