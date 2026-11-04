"""
Every function here returns data shaped EXACTLY like the arrays already
hardcoded in the frontend's app.js (same column order).

"Today" is fixed to a reference date rather than the real system clock,
since the sample vouchers are dated in mid-2026 and ageing/overdue logic
needs a consistent point to compare against for the demo.
"""

from datetime import date, datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import Voucher, InventoryItem, PartyMaster, SyncEvent, SalesTarget
 
REFERENCE_DATE = date(2026, 8, 25)
 
 
def _in_window(d, start, end):
    return (start is None or d >= start) and (end is None or d <= end)
 
 
def get_sales_table(db: Session, start: date | None = None, end: date | None = None):
    rows = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
            if _in_window(v.voucher_date, start, end)]
    return [
        [v.party_name, v.product, v.territory, v.salesperson, v.amount, v.returns_amount, v.segment,
         v.id, v.invoice_no, v.city, v.state, v.pincode, v.discount_pct]
        for v in rows
    ]
 
 
def get_purchase_table(db: Session, start: date | None = None, end: date | None = None):
    rows = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all()
            if _in_window(v.voucher_date, start, end)]
    result = []
    for v in rows:
        variance = (v.received_quantity or 0) - (v.quantity or 0)
        result.append([
            v.po_number, v.party_name, v.product, v.quantity,
            v.received_quantity, variance, v.debit_note or "\u2014", v.status,
            v.id, v.invoice_no,
        ])
    return result
 
 
def _inventory_risk(item: InventoryItem) -> str:
    if item.quantity < 0:
        return "Negative stock"
    if item.quantity < item.reorder_level:
        return "Low stock"
    if item.quantity > item.reorder_level * 4:
        return "Overstock"
    return "Healthy"
 
 
def get_inventory_table(db: Session):
    items = db.query(InventoryItem).all()
    return [
        [it.sku, it.product, it.category, it.branch, it.quantity, it.value,
         it.movement, _inventory_risk(it), it.id, it.reorder_level, it.lead_time_days, it.safety_stock]
        for it in items
    ]
 
 
def _ageing_bucket(due: date) -> str:
    days = (REFERENCE_DATE - due).days
    if days <= 30:
        return "0\u201330 days"
    if days <= 60:
        return "31\u201360 days"
    if days <= 90:
        return "61\u201390 days"
    return "90+ days"
 
 
def get_payment_table(db: Session):
    rows = db.query(Voucher).filter(Voucher.voucher_type.in_(["Receipt", "Payment"])).all()
    result = []
    for v in rows:
        # cash and cleared vouchers are money that already moved, not open
        # receivable/payable lines
        if v.payment_mode == "Cash" or v.status == "Cleared":
            continue
        ageing = _ageing_bucket(v.due_date) if v.due_date else "\u2014"
        invoice_no = f"INV-{1900 + v.id}" if v.payment_type == "Receivable" else f"BILL-{v.id}"
        result.append([invoice_no, v.party_name, v.payment_type, v.due_date.isoformat() if v.due_date else "",
                        v.amount, ageing, v.status, v.id])
    return result
 
 
def get_alerts(db: Session):
    alerts = []
 
    for it in db.query(InventoryItem).all():
        if it.quantity < 0:
            alerts.append(["high", "Negative stock requires review",
                            f"{it.product} has {int(it.quantity)} units in the {it.branch}.", "inventory"])
        elif it.quantity < it.reorder_level:
            alerts.append(["medium", "Product below reorder level",
                            f"{it.product} is at {int(it.quantity)} units, below the {int(it.reorder_level)}-unit reorder point.", "inventory"])
        elif it.quantity > it.reorder_level * 4:
            alerts.append(["low", "Slow-moving stock needs action",
                            f"₹{it.value/100000:.1f}L of {it.product} is overstocked at {it.branch}.", "inventory"])
 
    overdue = defaultdict(list)   # (Receivable/Payable, party) -> [vouchers]
    for v in db.query(Voucher).filter(Voucher.payment_type.isnot(None),
                                      Voucher.payment_mode != "Cash",
                                      Voucher.status != "Cleared").all():
        if v.due_date and v.due_date < REFERENCE_DATE:
            overdue[(v.payment_type, v.party_name)].append(v)
 
    for (ptype, party), rows in overdue.items():
        oldest = max((REFERENCE_DATE - v.due_date).days for v in rows)
        total = sum(v.amount for v in rows)
        alerts.append(["high" if oldest > 60 else "medium",
                       f"{ptype} overdue",
                       f"{party} has {len(rows)} overdue item(s) totalling "
                       f"\u20b9{total:,.0f}, oldest {oldest} days past due.", "cashflow"])
 
    # sales drop vs previous 30 days
    cur = sum(v.amount - (v.returns_amount or 0) for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
              if v.voucher_date and REFERENCE_DATE - timedelta(days=29) <= v.voucher_date <= REFERENCE_DATE)
    prev = sum(v.amount - (v.returns_amount or 0) for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
               if v.voucher_date and REFERENCE_DATE - timedelta(days=59) <= v.voucher_date <= REFERENCE_DATE - timedelta(days=30))
    if prev and (cur - prev) / prev <= -0.15:
        alerts.append(["medium", "Low sales alert",
                       f"Net sales this month are {((cur - prev) / prev) * 100:.0f}% below the previous 30 days.", "sales"])

    last_sale = {}
    for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all():
        last_sale[v.party_name] = max(last_sale.get(v.party_name, v.voucher_date), v.voucher_date)
    for party, last in last_sale.items():
        if last and (REFERENCE_DATE - last).days >= 60:
            alerts.append(["medium", "Customer inactivity alert",
                           f"{party} has not bought for {(REFERENCE_DATE - last).days} days.", "sales"])

    series = defaultdict(list)
    for v in db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all():
        if v.quantity:
            series[(v.party_name, v.product)].append((v.voucher_date, v.amount / v.quantity))
    for (supplier, product), pts in series.items():
        pts = sorted(pts)
        if len(pts) >= 2:
            base = sum(p[1] for p in pts[:-1]) / (len(pts) - 1)
            if base and (pts[-1][1] - base) / base >= 0.08:
                alerts.append(["low", "Purchase price increase",
                               f"{supplier} / {product} unit cost rose {(pts[-1][1] - base) / base * 100:.1f}%.", "purchases"])

    limits = {p.party_name: p.credit_limit for p in db.query(PartyMaster).all() if p.credit_limit}
    open_rec = defaultdict(float)
    for v in db.query(Voucher).filter(Voucher.payment_type == "Receivable", Voucher.status != "Cleared",
                                      Voucher.payment_mode != "Cash").all():
        open_rec[v.party_name] += v.amount
    for party, amt in open_rec.items():
        if party in limits and amt > limits[party]:
            alerts.append(["high", "Credit limit crossed",
                           f"{party} outstanding ₹{amt:,.0f} exceeds limit ₹{limits[party]:,.0f}.", "cashflow"])

    sync = db.query(SyncEvent).order_by(SyncEvent.id.desc()).first()
    if sync is None:
        alerts.append(["low", "Data alert", "No Tally or synthetic sync has been recorded yet.", "overview"])
    elif sync.status == "error":
        alerts.append(["high", "Tally sync failed", sync.message or "Last Sync TallyPrime attempt failed.", "overview"])
    elif sync.finished_at and (REFERENCE_DATE.isoformat() and (datetime.utcnow() - sync.finished_at).days >= 1) and sync.source == "tally":
        alerts.append(["medium", "Tally data may be stale",
                       f"Last successful Tally sync was {sync.finished_at.isoformat(timespec='minutes')}.", "overview"])

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: order.get(a[0], 3))
    return alerts
 