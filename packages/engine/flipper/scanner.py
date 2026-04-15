import logging

import pandas as pd

logger = logging.getLogger(__name__)

# --- Tunable constants ---
MIN_VOLUME: int = 100             # minimum volume_total per 5-min candle to qualify
HIGH_VOLUME_THRESHOLD: int = 5_000  # items above this are considered high-volume (sell after 5 min)
MAX_SPREAD_CV: float = 0.80       # max coefficient of variation of spread (lower = more stable)
MIN_MARGIN_PCT: float = 0.01      # minimum profit margin after GE tax (1%)
GE_TAX: float = 0.02             # 2% tax applied to sale value
TOP_N: int = 20                  # number of flip opportunities to display


def _filter_volume(df: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """Keep only items whose most recent 5-min candle meets the volume threshold."""
    return latest[latest["volume_total"] >= MIN_VOLUME]


def _filter_stability(df: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only items with a stable spread.

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

    latest = latest.merge(spread_stats[["item_id", "spread_cv"]], on="item_id", how="left")
    return latest[latest["spread_cv"] <= MAX_SPREAD_CV]


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


def scan(df: pd.DataFrame, item_names: dict[int, str]) -> pd.DataFrame:
    """
    Identify the best flip opportunities from the most recent price snapshot.

    Args:
        df:          Full price history DataFrame with columns:
                     time, item_id, avg_high_price, avg_low_price,
                     high_volume, low_volume, spread, volume_total
        item_names:  Mapping of item_id -> item name

    Returns:
        DataFrame of top flip opportunities sorted by margin, with columns:
        name, recommended_bid, recommended_ask, profit_per_unit, margin_pct,
        volume_total, spread_cv
    """
    # Latest snapshot per item (most recent candle)
    latest = (
        df.sort_values("time")
        .groupby("item_id")
        .last()
        .reset_index()
    )

    latest = _filter_volume(df, latest)
    latest = _filter_stability(df, latest)
    latest = _compute_recommendations(latest)

    # Drop unprofitable flips (negative margin after tax)
    latest = latest[latest["margin_pct"] >= MIN_MARGIN_PCT]

    latest["name"] = latest["item_id"].map(item_names).fillna(latest["item_id"].astype(str))

    result = (
        latest[["name", "item_id", "recommended_bid", "recommended_ask",
                "profit_per_unit", "margin_pct", "volume_total", "spread_cv"]]
        .sort_values("margin_pct", ascending=False)
        .reset_index(drop=True)
    )

    _log_results(result)
    return result


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
