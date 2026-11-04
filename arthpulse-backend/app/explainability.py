
"""Explain sales patterns using SHAP and a clearly labelled fallback."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .models import Voucher
from .summaries import get_window


# Features available in the Voucher model that may help explain sales patterns.
CATEGORICAL_FEATURES = [
    "territory",
    "product",
    "salesperson",
    "city",
    "segment",
    "category",
    "payment_mode",
    "nature",
    "state",
]


def _frame(db: Session, start, end) -> pd.DataFrame:
    """Load sales vouchers within the selected reporting window."""
    vouchers = (
        db.query(Voucher)
        .filter(
            Voucher.voucher_type == "Sales",
            Voucher.voucher_date >= start,
            Voucher.voucher_date <= end,
        )
        .all()
    )

    rows = []

    for voucher in vouchers:
        if not voucher.voucher_date:
            continue

        row = {
            "amount": float(voucher.amount or 0),
            "returns": float(voucher.returns_amount or 0),
        }

        for feature in CATEGORICAL_FEATURES:
            value = getattr(voucher, feature, None)
            row[feature] = str(value).strip() if value else "Unknown"

        rows.append(row)

    return pd.DataFrame(rows)


def _display_name(feature: str) -> str:
    """Convert encoded feature names into readable business labels."""
    prefixes = {
        "territory": "Territory",
        "product": "Product",
        "salesperson": "Salesperson",
        "city": "City",
        "segment": "Customer segment",
        "category": "Product category",
        "payment_mode": "Payment mode",
        "nature": "Transaction nature",
        "state": "State",
    }

    for prefix, label in prefixes.items():
        if feature == prefix:
            return label
        if feature.startswith(prefix + "_"):
            value = feature[len(prefix) + 1:]
            return f"{label}: {value}"

    return feature.replace("_", " ").title()


def _plain(drivers: list[dict]) -> str:
    if not drivers:
        return "Not enough sales history to explain the sales patterns."

    top = drivers[:3]
    factors = [
        f"{driver['factor']} (importance score {driver['impact_score']:.2f})"
        for driver in top
    ]

    return (
        "The model identified these as the strongest sales-related "
        "features: " + "; ".join(factors) + ". "
        "These are model-based associations, not proof of causation."
    )


def _empty_result(message: str, period: str, end) -> dict:
    return {
        "drivers": [],
        "plain_english": message,
        "method": "none",
        "as_of": end.isoformat(),
        "period": period,
    }


def explain_sales_drivers(db: Session, period: str = "monthly") -> dict:
    """Rank sales-related feature contributions for the selected period."""
    start, end, _, _ = get_window(db, period)
    df = _frame(db, start, end)

    if df.empty or len(df) < 8:
        return _empty_result(
            "Not enough sales records in this reporting period for "
            "a reliable driver analysis.",
            period,
            end,
        )

    # Predict net sales at voucher level rather than aggregating away
    # salesperson, city, segment, and payment information.
    df["net_sales"] = df["amount"] - df["returns"]

    feature_data = df[CATEGORICAL_FEATURES].copy()

    # Remove columns that have no variation in this reporting window.
    feature_data = feature_data.loc[
        :, feature_data.nunique(dropna=False) > 1
    ]

    if feature_data.empty:
        return _empty_result(
            "The available sales records have insufficient feature "
            "variation to explain sales patterns.",
            period,
            end,
        )

    X = pd.get_dummies(
        feature_data,
        prefix=feature_data.columns,
        prefix_sep="_",
        drop_first=False,
        dtype=float,
    )

    y = df["net_sales"].to_numpy(dtype=float)

    # Give higher-value transactions more influence without allowing
    # a single large transaction to dominate the training weights.
    mean_abs_sales = float(np.abs(y).mean())
    if mean_abs_sales == 0:
        return _empty_result(
            "Net sales are zero throughout this reporting period, "
            "so a meaningful sales-driver analysis is unavailable.",
            period,
            end,
        )

    weights = np.clip(np.abs(y) / mean_abs_sales, 0.2, 8.0)

    try:
        import shap
        import xgboost as xgb

        model = xgb.XGBRegressor(
            n_estimators=60,
            max_depth=3,
            learning_rate=0.08,
            min_child_weight=2,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            random_state=42,
            verbosity=0,
        )

        model.fit(X, y, sample_weight=weights)

        explainer = shap.TreeExplainer(model)
        shap_values = explainer(X)

        values = np.asarray(shap_values.values)

        # This is a single-output regression model; guard against
        # unexpected output shapes instead of silently misranking.
        if values.ndim != 2 or values.shape[1] != X.shape[1]:
            raise ValueError("Unexpected SHAP output shape")

        mean_abs = np.abs(values).mean(axis=0)

        ranked = sorted(
            zip(X.columns, mean_abs),
            key=lambda item: -float(item[1]),
        )

        drivers = [
            {
                "factor": _display_name(str(feature)),
                "impact_score": round(float(score), 2),
            }
            for feature, score in ranked[:8]
            if np.isfinite(score)
        ]

        method = "SHAP (XGBoost, rupee-weighted)"

    except Exception:
        # Fallback is an association score, not a SHAP explanation.
        # Use weighted correlation to keep scores comparable across
        # dummy variables with different frequencies.
        Xn = X.to_numpy(dtype=float)
        normalized_weights = weights / weights.sum()
        y_mean = np.average(y, weights=normalized_weights)
        y_centered = y - y_mean

        scores = []

        for index, feature in enumerate(X.columns):
            column = Xn[:, index]
            x_mean = np.average(column, weights=normalized_weights)
            x_centered = column - x_mean

            covariance = np.average(
                x_centered * y_centered,
                weights=normalized_weights,
            )

            x_variance = np.average(
                x_centered ** 2,
                weights=normalized_weights,
            )
            y_variance = np.average(
                y_centered ** 2,
                weights=normalized_weights,
            )

            denominator = np.sqrt(x_variance * y_variance)

            # Constant columns cannot provide a meaningful correlation.
            if denominator <= 0:
                continue

            correlation = covariance / denominator

            # Scale the association by the typical absolute net sale
            # value to retain a rupee-oriented importance score.
            score = abs(correlation) * mean_abs_sales

            if np.isfinite(score):
                scores.append((feature, score))

        ranked = sorted(scores, key=lambda item: -item[1])

        drivers = [
            {
                "factor": _display_name(str(feature)),
                "impact_score": round(float(score), 2),
            }
            for feature, score in ranked[:8]
        ]

        method = "weighted correlation fallback (SHAP unavailable or failed)"

    return {
        "drivers": drivers,
        "plain_english": _plain(drivers),
        "method": method,
        "as_of": end.isoformat(),
        "period": period,
    }
