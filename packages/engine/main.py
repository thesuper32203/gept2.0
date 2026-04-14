import argparse
import logging

from packages.collector.db.connection import DatabaseConnection
from packages.engine.features.builder import (
    load_raw_data,
    add_base_features,
    add_lag_features,
    rolling_features,
    time_features,
    target_features,
    clean,
    train,
)


def run_train() -> None:
    logger = logging.getLogger(__name__)

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
    logger.info("Training models...")
    train(df)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="GEPT2.0 Engine")
    parser.add_argument("--mode", choices=["train", "inference"], required=True)
    args = parser.parse_args()

    if args.mode == "train":
        run_train()
    elif args.mode == "inference":
        raise NotImplementedError("Inference mode not yet implemented — see Phase 2 Step 12")


if __name__ == "__main__":
    main()
