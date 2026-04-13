import pandas as pd
import numpy as np
import logging

from sklearn.metrics import mean_absolute_error, accuracy_score

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
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend"
]

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
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
)

rf_model = RandomForestRegressor(n_estimators=200, max_depth=10)

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

def rolling_features(df: pd.DataFrame) -> pd.DataFrame | None:
    #Need to build
    return None

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
    THRESHOLD = 0.001  # 0.1% — tune this based on your data
    df["target_up"] = (df["future_return_5"] > THRESHOLD).astype(int)
    return df

def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna()
    return df

def train(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["time"])

    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    train = df.iloc[:train_end]
    val = df.iloc[train_end:val_end]
    test = df.iloc[val_end:]

    x_train = train[FEATURE_COLUMNS]
    y_train = train[TARGET_REGRESSION]
    x_val = val[FEATURE_COLUMNS]
    y_val = val[TARGET_REGRESSION]
    x_test = test[FEATURE_COLUMNS]
    y_test = test[TARGET_REGRESSION]

    #xgb_model.fit(x_train, y_train)
    #predictions = xgb_model.predict(x_val)
    #lgb_model.fit(x_train, y_train)
    #predictions = lgb_model.predict(x_val)
    rf_model.fit(x_train, y_train)
    predictions = rf_model.predict(x_val)
    mae = mean_absolute_error(y_val, predictions)
    rmse = np.sqrt(mean_absolute_error(y_val, predictions))
    actual_direction = (y_val > 0).astype(int)
    predictioned_direction = (predictions > 0).astype(int)
    dir_accuracy = accuracy_score(actual_direction, predictioned_direction)
    print("MAE:", mae)
    print("RMSE:", rmse)
    print("ACCURACY:", dir_accuracy)

    # lgb_model.fit(x_train, y_train)
    # rf_model = RandomForestRegressor(n_estimators=200, max_depth=10)
    # rf_model.fit(x_train, y_train)
    #print(lgb_model.predict(x_val))
    #print(rf_model.predict(x_val))

    return df

def test():
    db = DatabaseConnection()
    data = load_raw_data(db)
    data = add_base_features(data)
    data = add_lag_features(data)
    data = time_features(data)
    data = target_features(data)
    data = clean(data)
    data = train(data)
    return data

if __name__ == "__main__":
    raw_data = test()
    print(raw_data.columns)