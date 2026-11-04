"""Dashboard totals vs last Tally sync, plus missing-field warnings."""

from sqlalchemy.orm import Session

from .models import InventoryItem, SyncEvent, Voucher
from .tally_sync import last_sync


def build_quality(db: Session) -> dict:
    sales = db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
    purchases = db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all()
    stock = db.query(InventoryItem).all()
    dash_sales = sum(v.amount for v in sales)
    dash_purch = sum(v.amount for v in purchases)
    dash_stock = sum(it.value for it in stock)

    sync = last_sync(db)
    tally_sales = (sync or {}).get("tally_sales_total") or 0
    match_sales = abs(dash_sales - tally_sales) < 1 if sync and sync.get("source") == "tally" else None

    missing = []
    for v in sales[:]:
        if not v.invoice_no:
            missing.append(f"Sales to {v.party_name} on {v.voucher_date} has no invoice number.")
        if not v.product or v.product == "Unspecified":
            missing.append(f"Sales to {v.party_name} has no stock item.")
        if len(missing) >= 8:
            break

    stale = bool(sync and sync.get("stale"))
    source = (sync or {}).get("source") or "none"
    warnings = []
    if source == "none":
        warnings.append("No sync has been recorded yet. You are looking at whatever is in the database.")
    if source == "synthetic":
        warnings.append("This is the presentation synthetic set, not a live Tally company.")
    if stale:
        warnings.append("Last successful sync is more than 24 hours old.")
    if match_sales is False:
        warnings.append("Dashboard sales total does not match the total stored from the last Tally export.")

    return {
        "sync": sync,
        "dashboard": {
            "sales": round(dash_sales),
            "purchases": round(dash_purch),
            "stock": round(dash_stock),
            "open_receivables": round(sum(
                v.amount for v in db.query(Voucher).filter(
                    Voucher.payment_type == "Receivable",
                    Voucher.status != "Cleared",
                    Voucher.payment_mode != "Cash",
                ).all()
            )),
        },
        "tally_sales_total": tally_sales,
        "sales_match": match_sales,
        "missing_fields": missing,
        "warnings": warnings,
        "strong_ai_ok": not stale and not missing[:1] and source != "none",
    }
