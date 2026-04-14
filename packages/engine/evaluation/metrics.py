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


def backtest(predictions: np.ndarray, actuals: np.ndarray, buy_threshold: float = 0.002, sell_threshold: float = -0.002) -> dict:
    total_profit = 0.0
    trades = 0
    equity_curve = [0.0]

    for pred, actual in zip(predictions, actuals):
        if pred > buy_threshold:
            total_profit += actual
            trades += 1
        elif pred < sell_threshold:
            total_profit -= actual
            trades += 1
        equity_curve.append(total_profit)

    # Max drawdown: largest peak-to-trough decline
    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    drawdowns = equity - peak
    max_drawdown = float(drawdowns.min())

    logger.info(
        f"Backtest — Total profit: {total_profit:.4f} | Trades: {trades} | Max drawdown: {max_drawdown:.4f}"
    )
    return {"total_profit": total_profit, "trades": trades, "max_drawdown": max_drawdown}
