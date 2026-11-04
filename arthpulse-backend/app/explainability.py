"""Cost-sensitive sales/risk drivers. Uses SHAP when the library loads; otherwise weighted coefficients."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .models import Voucher
from .rules import REFERENCE_DATE


def _frame(db: Session) -> pd.DataFrame:
    rows = []
    for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all():
        if not v.voucher_date:
            continue
        rows.append({
            "amount": float(v.amount or 0),
            "returns": float(v.returns_amount or 0),
            "territory": v.territory or "Unassigned",
            "product": v.product or "Unspecified",
            "salesperson": v.salesperson or "Unassigned",
            "city": v.city or "Unassigned",
            "segment": v.segment or "Active",
            "month": v.voucher_date.strftime("%Y-%m"),
        })
    return pd.DataFrame(rows)


def _plain(drivers: list[dict]) -> str:
    if not drivers:
        return "Not enough sales history to explain the mix."
    top = drivers[:3]
    bits = [f"{d['factor']} (₹-weighted importance {d['impact_score']:.0f})" for d in top]
    return "The mix is driven mainly by " + "; ".join(bits) + "."


def explain_sales_drivers(db: Session, period="monthly") -> dict:
    df = _frame(db)
    if df.empty or len(df) < 8:
        return {"drivers": [], "plain_english": "Not enough sales rows for a driver analysis.",
                "method": "none"}

    agg = df.groupby(["month", "territory", "product"], as_index=False).agg(
        sales_sum=("amount", "sum"),
        returns_sum=("returns", "sum"),
        order_count=("amount", "count"),
    )
    agg["net"] = agg["sales_sum"] - agg["returns_sum"]
    if len(agg) < 6:
        return {"drivers": [], "plain_english": "Not enough month-territory-product combinations.",
                "method": "none"}

    X = pd.get_dummies(agg[["territory", "product"]], drop_first=True)
    y = agg["net"].to_numpy(dtype=float)
    weights = np.clip(np.abs(y) / (np.abs(y).mean() or 1), 0.2, 8.0)

    method = "weighted-least-squares"
    drivers = []
    try:
        import shap
        import xgboost as xgb
        model = xgb.XGBRegressor(n_estimators=40, max_depth=3, learning_rate=0.15,
                                 random_state=42, verbosity=0)
        model.fit(X, y, sample_weight=weights)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer(X)
        mean_abs = np.abs(shap_values.values).mean(axis=0)
        drivers = [{"factor": name.replace("territory_", "Territory ").replace("product_", "Product "),
                    "impact_score": round(float(score), 2)}
                   for name, score in sorted(zip(X.columns, mean_abs), key=lambda kv: -kv[1])[:6]]
        method = "SHAP (XGBoost, rupee-weighted)"
    except Exception:
        # Cost-sensitive fallback: weighted covariance of each dummy with net sales
        Xn = X.to_numpy(dtype=float)
        w = weights
        w = w / w.sum()
        y_c = y - np.average(y, weights=w)
        scores = []
        for i, name in enumerate(X.columns):
            col = Xn[:, i]
            col_c = col - np.average(col, weights=w)
            scores.append((name, float(np.average(col_c * y_c, weights=w))))
        drivers = [{"factor": n.replace("territory_", "Territory ").replace("product_", "Product "),
                    "impact_score": round(abs(s), 2)}
                   for n, s in sorted(scores, key=lambda kv: -abs(kv[1]))[:6]]
        method = "rupee-weighted coefficients (SHAP library unavailable)"

    return {
        "drivers": drivers,
        "plain_english": _plain(drivers),
        "method": method,
        "as_of": REFERENCE_DATE.isoformat(),
        "period": period,
    }
