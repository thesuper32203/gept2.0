import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from packages.engine.flipper.scanner import GE_TAX, HIGH_VOLUME_THRESHOLD, MAX_SPREAD_CV, MIN_MARGIN_PCT, MIN_VOLUME

logger = logging.getLogger(__name__)

# --- Constants ---
STARTING_CAPITAL: int = 1_000_000
MAX_ACTIVE_TRADES: int = 8
MAX_POSITION_PCT: float = 0.10
STABILITY_WINDOW: int = 12         # candles used to compute rolling spread CV (12 x 5min = 1hr)
HIGH_VOL_HOLD_MIN: int = 5         # minutes to hold high-volume items
LOW_VOL_HOLD_MIN: int = 15         # minutes before force-selling low-volume items


@dataclass
class Trade:
    item_id: int
    quantity: int
    buy_price: float        # avg_low_price + 1
    cost: float             # quantity * buy_price
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    is_high_volume: bool


@dataclass
class BacktestResult:
    starting_capital: int
    final_capital: float
    total_profit_gp: float
    trades: int
    skipped_no_slots: int
    skipped_unaffordable: int
    skipped_no_margin: int
    max_drawdown_gp: float
    item_stats: dict = field(default_factory=dict)


def _precompute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling spread CV and volume_total to the price history."""
    df = df.sort_values(["item_id", "time"])
    g = df.groupby("item_id")
    df["spread_rolling_mean"] = g["spread"].transform(lambda x: x.rolling(STABILITY_WINDOW).mean())
    df["spread_rolling_std"] = g["spread"].transform(lambda x: x.rolling(STABILITY_WINDOW).std())
    df["spread_cv"] = df["spread_rolling_std"] / df["spread_rolling_mean"]
    return df


def _build_price_lookup(df: pd.DataFrame) -> dict:
    """
    Build a fast (item_id, timestamp) -> (avg_high_price, avg_low_price, volume_total) lookup.
    Used to fetch actual prices when a trade closes.
    """
    lookup = {}
    for row in df.itertuples(index=False):
        lookup[(row.item_id, row.time)] = (row.avg_high_price, row.avg_low_price, row.volume_total)
    return lookup


def _find_nearest_close_price(
    price_lookup: dict,
    item_id: int,
    close_time: pd.Timestamp,
    timestamps: np.ndarray,
) -> tuple[float, float] | None:
    """
    Find the actual close price at or just after the trade's close_time.
    Returns (avg_high_price, avg_low_price) or None if not found.
    """
    # find the nearest timestamp >= close_time
    future = timestamps[timestamps >= close_time]
    if len(future) == 0:
        return None
    nearest = future[0]
    entry = price_lookup.get((item_id, nearest))
    if entry:
        return entry[0], entry[1]
    return None


def _identify_candidates(snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Apply scanner rules to a single-timestamp snapshot.
    Returns candidates sorted by margin descending.
    """
    df = snapshot.copy()

    # Volume filter
    df = df[df["volume_total"] >= MIN_VOLUME]

    # Stability filter (requires precomputed spread_cv)
    df = df.dropna(subset=["spread_cv"])
    df = df[df["spread_cv"] <= MAX_SPREAD_CV]

    if df.empty:
        return df

    # Bid/ask/margin
    df["recommended_bid"] = df["avg_low_price"] + 1
    df["recommended_ask"] = df["avg_high_price"] - 1
    df["profit_per_unit"] = (
        df["recommended_ask"]
        - df["recommended_bid"]
        - df["recommended_ask"] * GE_TAX
    )
    df["margin_pct"] = df["profit_per_unit"] / df["recommended_bid"]

    # Margin filter
    df = df[df["margin_pct"] >= MIN_MARGIN_PCT]

    return df.sort_values("margin_pct", ascending=False)


def run_backtest(
    df: pd.DataFrame,
    item_names: dict[int, str],
    trading_days: int = 7,
    starting_capital: int = STARTING_CAPITAL,
) -> BacktestResult:
    """
    Simulate rule-based flipping over historical data.

    At each 5-min candle:
      1. Close any trades whose hold period has elapsed (using actual close prices)
      2. Scan for new flip opportunities using scanner rules
      3. Open trades for the best candidates until slots or capital is exhausted
    """
    logger.info("Preprocessing features...")
    df = _precompute_features(df)
    df = df.sort_values("time")

    all_timestamps = pd.Series(df["time"].unique()).sort_values().values
    cutoff = all_timestamps[0] + np.timedelta64(trading_days, 'D')
    timestamps = all_timestamps[all_timestamps <= cutoff]

    price_lookup = _build_price_lookup(df)

    capital = float(starting_capital)
    open_trades: list[Trade] = []
    equity_curve = [capital]
    item_stats: dict[int, dict] = {}
    total_trades = 0
    skipped_no_slots = 0
    skipped_unaffordable = 0
    skipped_no_margin = 0

    logger.info(f"Backtesting {len(timestamps)} candles over {trading_days} day(s)...")

    for t in timestamps:
        t_stamp = pd.Timestamp(t)

        # --- Close expired trades ---
        still_open = []
        for trade in open_trades:
            if trade.close_time <= t_stamp:
                close_prices = _find_nearest_close_price(price_lookup, trade.item_id, trade.close_time, all_timestamps)
                if close_prices:
                    actual_ask = close_prices[0] - 1   # sell 1 below actual high at close
                else:
                    actual_ask = trade.buy_price        # worst case: sell at cost

                sale_value = trade.quantity * actual_ask
                tax = sale_value * GE_TAX
                profit_gp = sale_value - trade.cost - tax
                capital += profit_gp

                if trade.item_id not in item_stats:
                    item_stats[trade.item_id] = {"trades": 0, "net_profit_gp": 0.0}
                item_stats[trade.item_id]["trades"] += 1
                item_stats[trade.item_id]["net_profit_gp"] += profit_gp
                total_trades += 1
                equity_curve.append(capital)
            else:
                still_open.append(trade)
        open_trades = still_open

        # --- Scan for new opportunities ---
        if len(open_trades) >= MAX_ACTIVE_TRADES:
            skipped_no_slots += 1
            continue

        snapshot = df[df["time"] == t]
        candidates = _identify_candidates(snapshot)

        if candidates.empty:
            skipped_no_margin += 1
            continue

        for _, row in candidates.iterrows():
            if len(open_trades) >= MAX_ACTIVE_TRADES:
                break

            position_gp = capital * MAX_POSITION_PCT
            buy_price = row["recommended_bid"]

            if buy_price <= 0 or buy_price > position_gp:
                skipped_unaffordable += 1
                continue

            quantity = int(position_gp // buy_price)
            is_high_vol = row["volume_total"] >= HIGH_VOLUME_THRESHOLD
            hold_minutes = HIGH_VOL_HOLD_MIN if is_high_vol else LOW_VOL_HOLD_MIN
            close_time = t_stamp + pd.Timedelta(minutes=hold_minutes)

            open_trades.append(Trade(
                item_id=int(row["item_id"]),
                quantity=quantity,
                buy_price=buy_price,
                cost=quantity * buy_price,
                open_time=t_stamp,
                close_time=close_time,
                is_high_volume=is_high_vol,
            ))

    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    max_drawdown_gp = float((equity - peak).min())
    total_profit_gp = capital - starting_capital

    result = BacktestResult(
        starting_capital=starting_capital,
        final_capital=capital,
        total_profit_gp=total_profit_gp,
        trades=total_trades,
        skipped_no_slots=skipped_no_slots,
        skipped_unaffordable=skipped_unaffordable,
        skipped_no_margin=skipped_no_margin,
        max_drawdown_gp=max_drawdown_gp,
        item_stats=item_stats,
    )

    _log_results(result, item_names)
    return result


def _log_results(result: BacktestResult, item_names: dict[int, str]) -> None:
    logger.info(
        f"Backtest complete — "
        f"Starting: {result.starting_capital:,} GP | "
        f"Final: {result.final_capital:,.0f} GP | "
        f"Profit: {result.total_profit_gp:+,.0f} GP | "
        f"Trades: {result.trades:,} | "
        f"Max drawdown: {result.max_drawdown_gp:,.0f} GP"
    )
    logger.info(
        f"Skipped — No slots: {result.skipped_no_slots:,} | "
        f"Unaffordable: {result.skipped_unaffordable:,} | "
        f"No margin: {result.skipped_no_margin:,}"
    )

    if result.item_stats:
        top10 = sorted(result.item_stats.items(), key=lambda x: x[1]["trades"], reverse=True)[:10]
        logger.info("Top 10 most traded items:")
        logger.info(f"  {'Item':<35} {'Trades':>8} {'Net Profit (GP)':>16}")
        logger.info(f"  {'-' * 61}")
        for item_id, stats in top10:
            name = item_names.get(item_id, str(item_id))
            logger.info(f"  {name:<35} {stats['trades']:>8,} {stats['net_profit_gp']:>+16,.0f}")
