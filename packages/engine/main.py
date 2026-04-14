import argparse
import logging

import joblib

from packages.collector.db.connection import DatabaseConnection
from packages.engine.evaluation.metrics import backtest
from packages.engine.features.builder import (
    FEATURE_COLUMNS,
    MODELS_DIR,
    TARGET_REGRESSION,
    add_base_features,
    add_lag_features,
    clean,
    load_raw_data,
    rolling_features,
    target_features,
    time_features,
    train,
)


def _build_features(logger: logging.Logger) -> object:
    logger.info("Loading data from database...")
    db = DatabaseConnection()
    df = load_raw_data(db)

    logger.info("Building features...")
    df = add_base_features(df)
    df = add_lag_features(df)
    df = rolling_features(df)
    df = time_features(df)
    df = target_features(df)
    df = clean(df)
    logger.info(f"Dataset: {len(df):,} rows, {len(df.columns)} columns")
    return df


def run_train() -> None:
    logger = logging.getLogger(__name__)
    df = _build_features(logger)
    logger.info("Training models...")
    train(df)


def run_backtest(trading_days: int) -> None:
    logger = logging.getLogger(__name__)

    model_path = MODELS_DIR / "best_model.pkl"
    if not model_path.exists():
        raise FileNotFoundError(f"No trained model found at {model_path}. Run --mode train first.")

    model = joblib.load(model_path)
    logger.info(f"Loaded model from {model_path}")

    df = _build_features(logger)
    df = df.sort_values("time")

    n = len(df)
    test_df = df.iloc[int(n * 0.85):]

    item_names_rows = DatabaseConnection().execute_query("SELECT item_id, name FROM items")
    item_names = {row[0]: row[1] for row in item_names_rows}

    predictions = model.predict(test_df[FEATURE_COLUMNS])
    backtest(
        predictions,
        test_df[TARGET_REGRESSION].to_numpy(),
        buy_prices=test_df["avg_low_price"].to_numpy(),
        sell_prices=test_df["avg_high_price"].to_numpy(),
        times=test_df["time"].to_numpy(),
        item_ids=test_df["item_id"].to_numpy(),
        item_names=item_names,
        trading_days=trading_days,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="GEPT2.0 Engine")
    parser.add_argument("--mode", choices=["train", "backtest", "inference"], required=True)
    parser.add_argument("--trading-days", type=int, default=7, help="Days to simulate in backtest (default: 7)")
    args = parser.parse_args()

    if args.mode == "train":
        run_train()
    elif args.mode == "backtest":
        run_backtest(args.trading_days)
    elif args.mode == "inference":
        raise NotImplementedError("Inference mode not yet implemented — see Phase 2 Step 12")


if __name__ == "__main__":
    main()
