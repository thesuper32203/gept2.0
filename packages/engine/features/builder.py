import pandas as pd
import numpy as np
import logging
from packages.collector.db.connection import DatabaseConnection

def load_raw_data(db: DatabaseConnection):

    data = db.execute_query("SELECT * FROM prices_5min")
    if data is None:
        logging.info("Failed to load raw prices data")
    data = pd.DataFrame(data, columns=["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"])
    return data

def add_base_features(df: pd.DataFrame):
    df["mid_price"] = (df["avg_high_price"] + df["avg_low_price"]) / 2
    df["spread"] = (df["avg_high_price"] - df["avg_low_price"])
    df["volume_total"] = df["high_volume"] + df["low_volume"]
    df["spread_pct"] = df["spread"] / df["mid_price"]
    df["volume_imbalance"] = df["volume_total"] / df["mid_price"]
    return df
def test():
    db = DatabaseConnection()
    data = load_raw_data(db)
    data = add_base_features(data)
    return data

if __name__ == "__main__":
    raw_data = test()
    print(raw_data)