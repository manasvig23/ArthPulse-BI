"""
Dashboard summaries, computed from the vouchers and stock tables.

Everything the frontend used to hardcode (KPI cards, trend bars, ageing,
supplier shares, working-capital days ...) is calculated here, so the
cards always agree with the tables underneath them.

Periods are rolling windows ending on the latest voucher date in the
database (capped at REFERENCE_DATE):
    daily = last 1 day, weekly = 7, monthly = 30, yearly = 365 days.
Growth compares a window with the equal-length window just before it.

Honest approximations (no cost-of-goods or credit-limit data in Tally
register exports):
    * "Sales less purchases" is a margin PROXY, not true gross profit.
    * Stock turnover divides sales (at selling price) by stock value (at cost).
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import rules
from .models import Voucher, InventoryItem
from .rules import REFERENCE_DATE

PERIOD_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}
PERIOD_LABELS = {"daily": "Today", "weekly": "This week",
                 "monthly": "This month", "yearly": "This year"}
AGEING_ORDER = ["0\u201330 days", "31\u201360 days", "61\u201390 days", "90+ days"]


# ------------------------------------------------------------- windows
def as_of_date(db: Session) -> date:
    latest = db.query(func.max(Voucher.voucher_date)).scalar()
    return min(latest, REFERENCE_DATE) if latest else REFERENCE_DATE


def get_window(db: Session, period: str):
    days = PERIOD_DAYS.get(period, 30)
    end = as_of_date(db)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return start, end, prev_start, prev_end


def _within(rows, start, end):
    return [v for v in rows if start <= v.voucher_date <= end]


def _net(v):
    return v.amount - (v.returns_amount or 0)


def _pct_change(cur, prev):
    return None if not prev else round((cur - prev) / prev * 100, 1)


def _money(x):
    return f"\u20b9{x / 100000:.1f}L" if abs(x) >= 100000 else f"\u20b9{x:,.0f}"


def _days(value):
    return "\u2014" if value is None else f"{value:.0f} days"


# --------------------------------------------------------------- trend
def _month_trend(sales, as_of, months=6):
    keys = []
    y, m = as_of.year, as_of.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    gross, net = defaultdict(float), defaultdict(float)
    for v in sales:
        k = (v.voucher_date.year, v.voucher_date.month)
        gross[k] += v.amount
        net[k] += _net(v)
    return {
        "labels": [names[m - 1] for _, m in keys],
        "gross": [round(gross[k]) for k in keys],
        "net": [round(net[k]) for k in keys],
    }


# ----------------------------------------------------------- sections
def _sales_section(sales, cur, start, end, prev_start, prev_end):
    gross = sum(v.amount for v in cur)
    returns = sum(v.returns_amount or 0 for v in cur)
    net = gross - returns
    prev_net = sum(_net(v) for v in _within(sales, prev_start, prev_end))

    territories = defaultdict(float)
    for v in cur:
        territories[v.territory or "Unassigned"] += _net(v)

    # customers (not vouchers) per segment, over full history
    party_segment = {v.party_name: v.segment for v in sales}
    segments = defaultdict(int)
    for seg in party_segment.values():
        segments[seg or "Unclassified"] += 1

    # cross-sell: best-selling product each active customer has never bought
    product_rev = defaultdict(float)
    bought = defaultdict(set)
    orders = defaultdict(list)
    party_rev = defaultdict(float)
    for v in sales:
        product_rev[v.product] += _net(v)
        bought[v.party_name].add(v.product)
        orders[v.party_name].append(v.amount)
        party_rev[v.party_name] += _net(v)
    ranked_products = sorted(product_rev, key=product_rev.get, reverse=True)
    cross_sell = []
    for party in sorted(party_rev, key=party_rev.get, reverse=True):
        if party_segment.get(party) == "Inactive":
            continue
        missing = [p for p in ranked_products if p not in bought[party]]
        if missing:
            avg_order = sum(orders[party]) / len(orders[party])
            cross_sell.append([party, f"Recommend {missing[0]}",
                               f"~{_money(avg_order)} per order"])
        if len(cross_sell) == 3:
            break

    return {
        "gross": round(gross), "returns": round(returns), "net": round(net),
        "returns_pct": round(returns / gross * 100, 1) if gross else 0,
        "growth": _pct_change(net, prev_net),
        "territories": {k: round(v) for k, v in territories.items() if v > 0},
        "segments": dict(segments),
        "cross_sell": cross_sell,
    }


def _purchases_section(purchases, cur, prev_start, prev_end):
    total = sum(v.amount for v in cur)
    prev_total = sum(v.amount for v in _within(purchases, prev_start, prev_end))

    short = [v for v in cur if v.debit_note]
    debit_value = sum(((v.quantity - (v.received_quantity or 0)) / v.quantity) * v.amount
                      for v in short if v.quantity)

    open_pos = [v for v in purchases if v.status and v.status != "Received"]

    spend = defaultdict(float)
    for v in cur:
        spend[v.party_name] += v.amount
    ordered = sorted(spend.items(), key=lambda kv: kv[1], reverse=True)
    supplier_spend = {k: round(v) for k, v in ordered[:3]}
    other = sum(v for _, v in ordered[3:])
    if other:
        supplier_spend["Other suppliers"] = round(other)
    top_name, top_amt = (ordered[0] if ordered else ("\u2014", 0))

    # price movement: latest unit cost vs average of earlier purchases
    series = defaultdict(list)
    for v in sorted(purchases, key=lambda x: x.voucher_date):
        if v.quantity:
            series[(v.party_name, v.product)].append(v.amount / v.quantity)
    moves = []
    for (supplier, product), costs in series.items():
        if len(costs) >= 2:
            base = sum(costs[:-1]) / len(costs[:-1])
            change = (costs[-1] - base) / base * 100
            moves.append((abs(change), supplier, product, change))
    moves.sort(reverse=True)
    up, down = "\u2191", "\u2193"
    price_moves = []
    for _, supplier, product, c in moves[:3]:
        text = "No change" if abs(c) < 0.5 else f"{up if c > 0 else down} {abs(c):.1f}%"
        price_moves.append([supplier, text, product])

    return {
        "total": round(total), "growth": _pct_change(total, prev_total),
        "debit_notes": len(short), "debit_note_value": round(debit_value),
        "open_pos": len(open_pos), "open_po_value": round(sum(v.amount for v in open_pos)),
        "top_supplier": top_name,
        "top_share": round(top_amt / total * 100) if total else 0,
        "supplier_spend": supplier_spend,
        "price_moves": price_moves,
    }


def _inventory_section(db, sales, as_of):
    items = db.query(InventoryItem).all()
    risk = {it.id: rules._inventory_risk(it) for it in items}
    stock_value = sum(it.value for it in items)
    low = sum(1 for it in items if risk[it.id] == "Low stock")
    negative = sum(1 for it in items if risk[it.id] == "Negative stock")
    overstock_value = sum(it.value for it in items if risk[it.id] == "Overstock")
    slow = sum(it.value for it in items if it.movement == "Slow-moving")
    non = sum(it.value for it in items if it.movement == "Non-moving")

    net_90 = sum(_net(v) for v in _within(sales, as_of - timedelta(days=89), as_of))
    turnover = (net_90 / stock_value) * (365 / 90) if stock_value else None
    inv_days = (stock_value / net_90 * 90) if net_90 else None

    return {
        "stock_value": round(stock_value), "low_stock": low, "negative": negative,
        "overstock_value": round(overstock_value),
        "inventory_days": inv_days,
        "efficiency": [
            ["Stock turnover (sales \u00f7 stock, annualised)",
             f"{turnover:.1f}x" if turnover else "\u2014"],
            ["Days of inventory", _days(inv_days)],
            ["Slow-moving value", _money(slow)],
            ["Non-moving value", _money(non)],
        ],
    }


def _cashflow_section(db, sales, purchases, as_of, inv_days):
    rows = rules.get_payment_table(db)   # open items only
    rec = [r for r in rows if r[2] == "Receivable"]
    pay = [r for r in rows if r[2] == "Payable"]
    receivables = sum(r[4] for r in rec)
    payables = sum(r[4] for r in pay)

    ageing = {b: 0 for b in AGEING_ORDER}
    for r in rec:
        ageing[r[5]] = ageing.get(r[5], 0) + r[4]

    by_party = defaultdict(float)
    for r in rec:
        by_party[r[1]] += r[4]
    top_party, top_amt = (max(by_party.items(), key=lambda kv: kv[1])
                          if by_party else ("\u2014", 0))

    s90 = sum(_net(v) for v in _within(sales, as_of - timedelta(days=89), as_of))
    p90 = sum(v.amount for v in _within(purchases, as_of - timedelta(days=89), as_of))
    rec_days = receivables / (s90 / 90) if s90 else None
    pay_days = payables / (p90 / 90) if p90 else None
    ccc = (rec_days + inv_days - pay_days) if None not in (rec_days, inv_days, pay_days) else None

    stock_value = db.query(func.sum(InventoryItem.value)).scalar() or 0
    return {
        "receivables": round(receivables),
        "overdue_receivables": round(sum(r[4] for r in rec if r[6] == "Overdue")),
        "payables": round(payables),
        "payables_due_week": round(sum(r[4] for r in pay if r[6] == "Due this week")),
        "top_debtor": top_party,
        "top_debtor_share": round(top_amt / receivables * 100) if receivables else 0,
        "top_debtor_amount": round(top_amt),
        "ageing": {k: round(v) for k, v in ageing.items()},
        "net_working_capital": round(receivables + stock_value - payables),
        "working_capital": [
            ["Receivable days", _days(rec_days)],
            ["Payable days", _days(pay_days)],
            ["Inventory days", _days(inv_days)],
            ["Cash conversion cycle", _days(ccc)],
        ],
    }


# ---------------------------------------------------------------- main
def build_summary(db: Session, period: str = "monthly"):
    if period not in PERIOD_DAYS:
        period = "monthly"
    start, end, prev_start, prev_end = get_window(db, period)

    sales = db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
    purchases = db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all()

    cur_sales = _within(sales, start, end)
    cur_purchases = _within(purchases, start, end)

    sales_s = _sales_section(sales, cur_sales, start, end, prev_start, prev_end)
    purch_s = _purchases_section(purchases, cur_purchases, prev_start, prev_end)
    inv_s = _inventory_section(db, sales, end)
    cash_s = _cashflow_section(db, sales, purchases, end, inv_s["inventory_days"])

    proxy = sales_s["net"] - purch_s["total"]
    overview = {
        "net_sales": sales_s["net"], "growth": sales_s["growth"],
        "sales_less_purchases": proxy,
        "margin_pct": round(proxy / sales_s["net"] * 100, 1) if sales_s["net"] else 0,
        "receivables": cash_s["receivables"], "overdue": cash_s["overdue_receivables"],
        "stock_value": inv_s["stock_value"],
        "replenishment_risks": inv_s["low_stock"] + inv_s["negative"],
        "trend": _month_trend(sales, end),
    }

    return {
        "period": period, "label": PERIOD_LABELS[period],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview, "sales": sales_s, "purchases": purch_s,
        "inventory": inv_s, "cashflow": cash_s,
    }