import logging
import pandas as pd
import time

from packages.collector.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

# --- Tunable constants ---
MIN_VOLUME: int = 1_000                 # minimum volume_total per 5-min candle to qualify
HIGH_VOLUME_THRESHOLD: int = 50_000     # items above this are considered high-volume
MAX_SPREAD_CV: float = 0.80             # max coefficient of variation of spread (lower = more stable)
MIN_MARGIN_PCT: float = 0.01            # minimum profit margin after GE tax (1%)
MIN_MARGIN_PCT_HIGH_VOL: float = 0.005  # 0.5% minimum for high-volume items
GE_TAX: float = 0.02                   # 2% tax applied to sale value
TOP_N: int = 20                         # number of flip opportunities to display


def _get_price(db: DatabaseConnection) -> pd.DataFrame:
    query = (
        "SELECT time, item_id, avg_high_price, avg_low_price, high_volume, low_volume "
        "FROM prices_5min "
        "WHERE time >= NOW() - INTERVAL '6 HOUR'"
    )
    rows = db.execute_query(query)
    price_data = pd.DataFrame(rows, columns=[
        "time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"
    ])
    price_data["time"] = pd.to_datetime(price_data["time"], utc=True).dt.tz_convert(None)
    price_data["spread"] = price_data["avg_high_price"] - price_data["avg_low_price"]
    price_data["volume_total"] = price_data["high_volume"] + price_data["low_volume"]
    return price_data


def _filter_by_volume(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only items that meet the volume threshold at the most recent candle.
    Returns the full 6-hour history filtered to those items only.
    """
    max_time = df["time"].max()
    valid_items = df[(df["time"] == max_time) & (df["volume_total"] >= MIN_VOLUME)]["item_id"]
    return df[df["item_id"].isin(valid_items)]


def _filter_stability(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only items with a stable spread. Returns the latest candle per item.

    Coefficient of variation (CV) = std(spread) / mean(spread).
    Low CV means the spread is consistent — predictable margins.
    High CV means the spread jumps around — risky to flip.
    """
    spread_stats = (
        df.groupby("item_id")["spread"]
        .agg(["mean", "std"])
        .rename(columns={"mean": "spread_mean", "std": "spread_std"})
        .reset_index()
    )
    spread_stats["spread_cv"] = spread_stats["spread_std"] / spread_stats["spread_mean"]
    spread_stats = spread_stats[spread_stats["spread_cv"] <= MAX_SPREAD_CV]

    latest = (
        df[df["item_id"].isin(spread_stats["item_id"])]
        .sort_values("time")
        .groupby("item_id")
        .last()
        .reset_index()
    )
    return latest.merge(spread_stats[["item_id", "spread_cv"]], on="item_id")


def _compute_recommendations(latest: pd.DataFrame) -> pd.DataFrame:
    """
    Compute bid, ask, profit per unit, and margin for each item.

    GE queue mechanic:
      - Bid 1 GP above avg_low_price  → queues ahead of other buyers, fills fast
      - Ask 1 GP below avg_high_price → undercuts other sellers, fills fast
      - Profit = ask - bid - 2% GE tax on ask
    """
    latest = latest.copy()
    latest["recommended_bid"] = latest["avg_low_price"] + 1
    latest["recommended_ask"] = latest["avg_high_price"] - 1
    latest["tax"] = latest["recommended_ask"] * GE_TAX
    latest["profit_per_unit"] = latest["recommended_ask"] - latest["recommended_bid"] - latest["tax"]
    latest["margin_pct"] = latest["profit_per_unit"] / latest["recommended_bid"]
    return latest


def _apply_margin_filter(latest: pd.DataFrame) -> pd.DataFrame:
    """Two-tier margin filter: high-volume items get a lower margin floor."""
    high_vol = latest["volume_total"] >= HIGH_VOLUME_THRESHOLD
    return latest[
        (high_vol & (latest["margin_pct"] >= MIN_MARGIN_PCT_HIGH_VOL)) |
        (~high_vol & (latest["margin_pct"] >= MIN_MARGIN_PCT))
    ]


def scan(df: pd.DataFrame, item_names: dict[int, str]) -> pd.DataFrame:
    """
    Identify the best flip opportunities from the most recent price snapshot.

    Args:
        df:          Full price history DataFrame (output of _get_price)
        item_names:  Mapping of item_id -> item name

    Returns:
        DataFrame of top flip opportunities sorted by volume_total descending.
    """
    df = _filter_by_volume(df)
    latest = _filter_stability(df)
    latest = _compute_recommendations(latest)
    latest = _apply_margin_filter(latest)

    latest["name"] = latest["item_id"].map(item_names).fillna(latest["item_id"].astype(str))

    result = (
        latest[["name", "item_id", "recommended_bid", "recommended_ask",
                "profit_per_unit", "margin_pct", "volume_total", "spread_cv"]]
        .sort_values(["profit_per_unit", "volume_total"], ascending=False)
        .reset_index(drop=True)
    )

    _log_results(result)
    return result


def scanner_loop(db: DatabaseConnection) -> None:
    items = db.execute_query("SELECT item_id, name FROM items")
    item_names = {row[0]: row[1] for row in items}
    logger.info(f"Found {len(items)} items")

    while True:
        price_data = _get_price(db)
        logger.info(f"Loaded {len(price_data)} price rows")
        scan(price_data, item_names)
        time.sleep(300)


def _log_results(df: pd.DataFrame) -> None:
    top = df.head(TOP_N)
    if top.empty:
        logger.info("No flip opportunities found matching the current filters.")
        return

    logger.info(f"Top {len(top)} flip opportunities:")
    logger.info(
        f"  {'Item':<35} {'Bid':>10} {'Ask':>10} "
        f"{'Profit/unit':>12} {'Margin':>8} {'Volume':>12}"
    )
    logger.info(f"  {'-' * 91}")
    for _, row in top.iterrows():
        logger.info(
            f"  {row['name']:<35} "
            f"{int(row['recommended_bid']):>10,} "
            f"{int(row['recommended_ask']):>10,} "
            f"{int(row['profit_per_unit']):>12,} "
            f"{row['margin_pct']:>7.2%} "
            f"{int(row['volume_total']):>12,}"
        )


def main() -> None:
    db = DatabaseConnection()
    scanner_loop(db)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
