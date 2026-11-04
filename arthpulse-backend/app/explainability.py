import pandas as pd
import numpy as np
import shap
import xgboost as xgb
from datetime import timedelta
from sqlalchemy.orm import Session
from app.models import Voucher
from app.rules import REFERENCE_DATE

def get_shap_sales_drivers(db: Session, period="monthly"):
    """
    Trains a lightweight model on historical voucher data to determine 
    what features contributed most to sales volume, returning SHAP values.
    """
    vouchers = db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
    if not vouchers:
        return {"drivers": [], "summary": "Insufficient data for SHAP analysis."}

    # Convert vouchers to a DataFrame for feature engineering
    data = []
    for v in vouchers:
        data.append({
            "date": v.voucher_date,
            "amount": v.amount,
            "territory": v.territory or "Unassigned",
            "product": v.product or "Unspecified",
            "salesperson": v.salesperson or "Unassigned",
            "month": v.voucher_date.strftime("%Y-%m") if v.voucher_date else "Unknown"
        })
    
    df = pd.DataFrame(data)
    if df.empty:
        return {"drivers": [], "summary": "No sales records found."}

    # Aggregate by Month, Territory, and Product to create training instances
    agg = df.groupby(["month", "territory", "product"]).agg(
        sales_sum=("amount", "sum"),
        order_count=("amount", "count")
    ).reset_index()

    if len(agg) < 5:
        return {"drivers": [], "summary": "Not enough historical depth for multi-feature attribution."}

    # Prepare features (X) and target (y: sales_sum)
    features = ["territory", "product"]
    X = pd.get_dummies(agg[features], drop_first=True)
    y = agg["sales_sum"]

    # Train a fast XGBoost regressor
    model = xgb.XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X, y)

    # Compute SHAP values
    explainer = shap.TreeExplainer(model)
    shap_values = explainer(X)

    # Extract mean absolute SHAP values to find overall top root-cause drivers
    mean_shap = np.abs(shap_values.values).mean(axis=0)
    feature_names = X.columns
    
    drivers = sorted(zip(feature_names, mean_shap), key=lambda x: x[1], reverse=True)
    
    formatted_drivers = [{"factor": name, "impact_score": round(float(score), 2)} for name, score in drivers[:5]]
    
    return {
        "top_drivers": formatted_drivers,
        "explanation": "SHAP analysis indicates territory mix and product distribution are the primary root-cause levers influencing sales variance."
    }