import argparse
import logging

import pandas as pd

from packages.collector.db.connection import DatabaseConnection
from packages.engine.flipper.scanner import scan


def _load_price_data(db: DatabaseConnection) -> pd.DataFrame:
    rows = db.execute_query(
        "SELECT time, item_id, avg_high_price, avg_low_price, high_volume, low_volume FROM prices_5min"
    )
    df = pd.DataFrame(rows, columns=["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"])
    df["spread"] = df["avg_high_price"] - df["avg_low_price"]
    df["volume_total"] = df["high_volume"] + df["low_volume"]
    return df


def run_scan() -> None:
    logger = logging.getLogger(__name__)

    logger.info("Connecting to database...")
    db = DatabaseConnection()

    logger.info("Loading price data...")
    df = _load_price_data(db)

    logger.info("Loading item names...")
    rows = db.execute_query("SELECT item_id, name FROM items")
    item_names = {row[0]: row[1] for row in rows}

    logger.info("Scanning for flip opportunities...")
    scan(df, item_names)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="GEPT2.0 Rule-Based Flipper")
    parser.add_argument("--mode", choices=["scan"], required=True)
    args = parser.parse_args()

    if args.mode == "scan":
        run_scan()


if __name__ == "__main__":
    main()
