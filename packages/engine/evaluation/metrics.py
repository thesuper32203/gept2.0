import heapq
import logging

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)

logger = logging.getLogger(__name__)


def evaluate_regression(name: str, model, x_val: pd.DataFrame, y_val: pd.Series) -> dict:
    predictions = model.predict(x_val)

    mae = mean_absolute_error(y_val, predictions)
    rmse = np.sqrt(mean_squared_error(y_val, predictions))
    dir_accuracy = accuracy_score((y_val > 0).astype(int), (predictions > 0).astype(int))

    logger.info(f"[{name}] MAE: {mae:.6f} | RMSE: {rmse:.6f} | Directional accuracy: {dir_accuracy:.4f}")
    return {"mae": mae, "rmse": rmse, "dir_accuracy": dir_accuracy}


def evaluate_classification(name: str, model, x_val: pd.DataFrame, y_val: pd.Series) -> dict:
    predictions = model.predict(x_val)
    probabilities = model.predict_proba(x_val)[:, 1]

    acc = accuracy_score(y_val, predictions)
    precision = precision_score(y_val, predictions, zero_division=0)
    recall = recall_score(y_val, predictions, zero_division=0)
    f1 = f1_score(y_val, predictions, zero_division=0)
    auc = roc_auc_score(y_val, probabilities)

    logger.info(
        f"[{name}] Accuracy: {acc:.4f} | Precision: {precision:.4f} | "
        f"Recall: {recall:.4f} | F1: {f1:.4f} | AUC: {auc:.4f}"
    )
    return {"accuracy": acc, "precision": precision, "recall": recall, "f1": f1, "auc": auc}


def evaluate_feature_importance(name: str, model, feature_columns: list[str], top_n: int = 20) -> pd.Series:
    importance = pd.Series(
        model.feature_importances_,
        index=feature_columns,
    ).sort_values(ascending=False)

    logger.info(f"[{name}] Top {top_n} features:\n{importance.head(top_n).to_string()}")
    return importance


STARTING_CAPITAL: int = 1_000_000  # 1M GP
MAX_POSITION_PCT: float = 0.10     # Max 10% of capital per trade
MAX_ACTIVE_TRADES: int = 8         # OSRS GE trade slot limit
GE_TAX: float = 0.02              # 2% tax on every sale
FIVE_PERIODS: np.timedelta64 = np.timedelta64(25, 'm')  # 5 x 5-min candles


def backtest(
    predictions: np.ndarray,
    actuals: np.ndarray,
    buy_prices: np.ndarray,
    times: np.ndarray,
    item_ids: np.ndarray | None = None,
    item_names: dict[int, str] | None = None,
    trading_days: int | None = 7,
    starting_capital: int = STARTING_CAPITAL,
    max_position_pct: float = MAX_POSITION_PCT,
    buy_threshold: float = 0.002,
) -> dict:
    capital = float(starting_capital)
    trades = 0
    skipped_unaffordable = 0
    skipped_no_slots = 0
    equity_curve = [capital]
    item_stats: dict[int, dict] = {}

    cutoff = times[0] + np.timedelta64(trading_days, 'D') if trading_days is not None else None

    # Min-heap of close times for open trade slots
    open_slots: list[np.datetime64] = []

    for i, (pred, actual, buy_price) in enumerate(zip(predictions, actuals, buy_prices)):
        t = times[i]

        if cutoff is not None and t > cutoff:
            break

        # Free any slots whose trades have now closed
        while open_slots and open_slots[0] <= t:
            heapq.heappop(open_slots)

        # Only act on buy signals — OSRS GE does not support shorting
        if pred <= buy_threshold:
            continue

        # Block if all 8 trade slots are occupied
        if len(open_slots) >= MAX_ACTIVE_TRADES:
            skipped_no_slots += 1
            continue

        # Position sizing: up to max_position_pct of capital
        position_gp = capital * max_position_pct
        if buy_price <= 0 or buy_price > position_gp:
            skipped_unaffordable += 1
            continue

        quantity = int(position_gp // buy_price)
        cost = quantity * buy_price
        sale_value = cost * (1 + actual)
        tax = sale_value * GE_TAX
        profit_gp = sale_value - cost - tax

        capital += profit_gp
        trades += 1
        equity_curve.append(capital)
        heapq.heappush(open_slots, t + FIVE_PERIODS)

        if item_ids is not None:
            item_id = int(item_ids[i])
            if item_id not in item_stats:
                item_stats[item_id] = {"trades": 0, "net_profit_gp": 0.0}
            item_stats[item_id]["trades"] += 1
            item_stats[item_id]["net_profit_gp"] += profit_gp

    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    max_drawdown_gp = float((equity - peak).min())
    total_profit_gp = capital - starting_capital

    window = f"{trading_days} day(s)" if trading_days else "full test set"
    logger.info(
        f"Backtest ({window}) — Starting: {starting_capital:,} GP | "
        f"Final: {capital:,.0f} GP | "
        f"Profit: {total_profit_gp:+,.0f} GP | "
        f"Trades: {trades:,} | Skipped (no slot): {skipped_no_slots:,} | "
        f"Skipped (unaffordable): {skipped_unaffordable:,} | "
        f"Max drawdown: {max_drawdown_gp:,.0f} GP"
    )

    if item_stats:
        top10 = sorted(item_stats.items(), key=lambda x: x[1]["trades"], reverse=True)[:10]
        logger.info("Top 10 most traded items:")
        logger.info(f"  {'Item':<35} {'Trades':>8} {'Net Profit (GP)':>16}")
        logger.info(f"  {'-'*61}")
        for item_id, stats in top10:
            name = item_names.get(item_id, str(item_id)) if item_names else str(item_id)
            logger.info(f"  {name:<35} {stats['trades']:>8,} {stats['net_profit_gp']:>+16,.0f}")

    return {
        "starting_capital": starting_capital,
        "final_capital": capital,
        "total_profit_gp": total_profit_gp,
        "trades": trades,
        "skipped_no_slots": skipped_no_slots,
        "skipped_unaffordable": skipped_unaffordable,
        "max_drawdown_gp": max_drawdown_gp,
    }
