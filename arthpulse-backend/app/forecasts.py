"""Simple forecasts: moving-average baseline, used only when enough history exists."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from .models import Voucher, InventoryItem
from .rules import REFERENCE_DATE


def _month_key(d):
    return d.year, d.month


def _next_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _label(y, m):
    return date_name(m) + f" {y}"


def date_name(m):
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]


def _series(rows, amount_fn, months=6):
    buckets = defaultdict(float)
    for v in rows:
        if v.voucher_date:
            buckets[_month_key(v.voucher_date)] += amount_fn(v)
    keys = []
    y, m = REFERENCE_DATE.year, REFERENCE_DATE.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    values = [round(buckets[k]) for k in keys]
    return keys, values


def _forecast_next(values):
    hist = [v for v in values if v]
    if len(hist) < 3:
        return None, "Not enough history for a forecast."
    ma = sum(hist[-3:]) / 3
    prev = hist[-1]
    return round(ma), f"Three-month moving average (last actual {round(prev)})."


def build_forecasts(db: Session) -> dict:
    sales = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
             if v.voucher_date]
    receipts = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Receipt").all()
                if v.voucher_date]
    payments = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Payment").all()
                if v.voucher_date]

    s_keys, s_vals = _series(sales, lambda v: v.amount - (v.returns_amount or 0))
    next_sales, note = _forecast_next(s_vals)
    ny, nm = _next_month(*s_keys[-1]) if s_keys else (REFERENCE_DATE.year, REFERENCE_DATE.month)

    _, in_vals = _series(receipts, lambda v: v.amount if v.status == "Cleared" or v.payment_mode == "Cash" else 0)
    _, out_vals = _series(payments, lambda v: v.amount if v.status == "Cleared" or v.payment_mode == "Cash" else 0)
    cash_in, in_note = _forecast_next(in_vals)
    cash_out, out_note = _forecast_next(out_vals)

    open_in = sum(v.amount for v in receipts if v.status != "Cleared" and v.payment_mode != "Cash")
    open_out = sum(v.amount for v in payments if v.status != "Cleared" and v.payment_mode != "Cash")

    stock = db.query(InventoryItem).all()
    stock_forecast = []
    for it in stock:
        daily = max((it.quantity or 0), 1) / max(it.lead_time_days or 7, 1)
        cover = None
        if it.quantity and it.quantity > 0:
            sold_90 = sum(v.quantity or 0 for v in sales
                          if v.product == it.product
                          and v.voucher_date >= REFERENCE_DATE - timedelta(days=89))
            daily_sales = sold_90 / 90 if sold_90 else 0
            cover = round(it.quantity / daily_sales) if daily_sales else None
        stock_forecast.append({
            "product": it.product,
            "godown": it.branch,
            "on_hand": it.quantity,
            "lead_time_days": it.lead_time_days,
            "safety_stock": it.safety_stock,
            "days_cover": cover,
            "reorder_review": bool(
                cover is not None and it.lead_time_days and cover <= (it.lead_time_days or 0) + (it.safety_stock or 0)
            ),
        })

    return {
        "sales": {
            "labels": [_label(*k) for k in s_keys],
            "history": s_vals,
            "next_month": _label(ny, nm),
            "forecast": next_sales,
            "method": note,
        },
        "cash": {
            "expected_in": round(open_in + (cash_in or 0)),
            "expected_out": round(open_out + (cash_out or 0)),
            "open_receivables": round(open_in),
            "open_payables": round(open_out),
            "in_note": in_note,
            "out_note": out_note,
        },
        "stock": stock_forecast[:12],
    }
