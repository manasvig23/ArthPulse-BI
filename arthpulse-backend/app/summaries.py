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
from .models import Voucher, InventoryItem, PartyMaster, SalesTarget, StockMovement
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
 
    customer_rev = defaultdict(float)
    product_rev = defaultdict(float)
    group_rev = defaultdict(float)
    city_rev = defaultdict(float)
    state_rev = defaultdict(float)
    pincode_rev = defaultdict(float)
    person_rev = defaultdict(float)
    discount_total = 0
    pairs = defaultdict(int)
    for v in cur:
        net_v = _net(v)
        customer_rev[v.party_name] += net_v
        product_rev[v.product or "Unspecified"] += net_v
        group_rev[v.category or "Unassigned"] += net_v
        city_rev[v.city or "Unassigned"] += net_v
        state_rev[v.state or "Unassigned"] += net_v
        pincode_rev[v.pincode or "—"] += net_v
        person_rev[v.salesperson or "Unassigned"] += net_v
        discount_total += v.discount_amount or (v.amount * (v.discount_pct or 0) / 100)
    def _rank(d, n=5):
        ordered = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
        return {"top": [[k, round(v)] for k, v in ordered[:n] if v > 0],
                "bottom": [[k, round(v)] for k, v in ordered[-n:] if v > 0 and k not in {x[0] for x in ordered[:n]}]}

    # basket: products sharing a customer+date
    basket_key = defaultdict(set)
    for v in cur:
        basket_key[(v.party_name, v.voucher_date)].add(v.product)
    pair_count = defaultdict(int)
    for items in basket_key.values():
        items = [p for p in items if p]
        for i, a in enumerate(sorted(items)):
            for b in sorted(items)[i + 1:]:
                pair_count[(a, b)] += 1
    basket = [[a, b, n] for (a, b), n in sorted(pair_count.items(), key=lambda kv: -kv[1])[:5]]

    history = []
    for party, amt in sorted(customer_rev.items(), key=lambda kv: -kv[1])[:8]:
        mix = defaultdict(float)
        outstanding = 0
        for v in sales:
            if v.party_name == party:
                mix[v.product or "Unspecified"] += _net(v)
        history.append({
            "customer": party, "period_sales": round(amt),
            "products": [[k, round(v)] for k, v in sorted(mix.items(), key=lambda kv: -kv[1])[:4]],
        })

    return {
        "gross": round(gross), "returns": round(returns), "net": round(net),
        "returns_pct": round(returns / gross * 100, 1) if gross else 0,
        "growth": _pct_change(net, prev_net),
        "territories": {k: round(v) for k, v in territories.items() if v > 0},
        "segments": dict(segments),
        "cross_sell": cross_sell,
        "customers": _rank(customer_rev),
        "products": _rank(product_rev),
        "groups": _rank(group_rev),
        "cities": {k: round(v) for k, v in city_rev.items() if v > 0},
        "states": {k: round(v) for k, v in state_rev.items() if v > 0},
        "pincodes": {k: round(v) for k, v in list(pincode_rev.items())[:8] if v > 0},
        "salespeople": {k: round(v) for k, v in person_rev.items() if v > 0},
        "basket": basket,
        "discount_value": round(discount_total),
        "customer_history": history,
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
        "vs_stock": None,
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

    godowns = defaultdict(lambda: {"qty": 0, "value": 0, "skus": 0})
    for it in items:
        g = godowns[it.branch or "Main"]
        g["qty"] += it.quantity or 0
        g["value"] += it.value or 0
        g["skus"] += 1
    ageing_rows = []
    for it in items:
        days = None
        if it.last_movement_date:
            days = (as_of - it.last_movement_date).days
        ageing_rows.append([it.product, it.branch, days if days is not None else "—", it.movement, round(it.value)])
    moves = db.query(StockMovement).order_by(StockMovement.movement_date.desc()).limit(40).all()
    move_rows = [[m.movement_date.isoformat() if m.movement_date else "", m.voucher_type, m.product,
                  m.godown, m.inward_qty, m.outward_qty] for m in moves]
    high_slow = [[it.product, it.branch, round(it.value), it.movement]
                 for it in items if it.movement in ("Slow-moving", "Non-moving") and it.value > 0]
    high_slow.sort(key=lambda r: -r[2])

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
        "godowns": {k: {"qty": round(v["qty"]), "value": round(v["value"]), "skus": v["skus"]} for k, v in godowns.items()},
        "ageing": ageing_rows[:20],
        "movements": move_rows,
        "high_value_slow": high_slow[:8],
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

    pay_age = {b: 0 for b in AGEING_ORDER}
    for r in pay:
        pay_age[r[5]] = pay_age.get(r[5], 0) + r[4]

    limits = {p.party_name: p.credit_limit for p in db.query(PartyMaster).all() if p.credit_limit}
    outstanding = defaultdict(float)
    for r in rec:
        outstanding[r[1]] += r[4]
    breaches = [[party, round(amt), round(limits[party])]
                for party, amt in outstanding.items() if party in limits and amt > limits[party]]

    behaviour = []
    cleared = db.query(Voucher).filter(Voucher.voucher_type == "Receipt", Voucher.status == "Cleared").all()
    lags = defaultdict(list)
    for v in cleared:
        if v.due_date and v.voucher_date:
            lags[v.party_name].append((v.voucher_date - v.due_date).days + 30)
    for party, days in lags.items():
        avg = sum(days) / len(days)
        behaviour.append([party, round(avg, 1), "Late" if avg > 35 else "On time"])
    behaviour.sort(key=lambda r: -r[1])

    cash_bank = {"cash_in": 0, "cash_out": 0, "bank_in": 0, "bank_out": 0}
    for v in db.query(Voucher).filter(Voucher.voucher_type.in_(["Receipt", "Payment"])).all():
        key_in = "cash_in" if v.payment_mode == "Cash" else "bank_in"
        key_out = "cash_out" if v.payment_mode == "Cash" else "bank_out"
        if v.voucher_type == "Receipt":
            cash_bank[key_in] += v.amount
        else:
            cash_bank[key_out] += v.amount

    due_today = sum(r[4] for r in rec + pay if r[3] == as_of.isoformat())

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
        "payable_ageing": {k: round(v) for k, v in pay_age.items()},
        "credit_breaches": breaches,
        "payment_behaviour": behaviour[:8],
        "cash_bank": {k: round(v) for k, v in cash_bank.items()},
        "due_today": round(due_today),
        "forecast_in": round(receivables),
        "forecast_out": round(payables),
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
 
    sales_s["trend"] = overview["trend"]   # Sales page draws this even without 'overview' access

    # sales vs target for the window's month
    month_key = end.strftime("%Y-%m")
    targets = db.query(SalesTarget).filter(SalesTarget.month == month_key).all()
    actual_by = defaultdict(float)
    for v in cur_sales:
        actual_by[v.party_name] += _net(v)
    sales_s["targets"] = [[t.party_name, round(t.target_amount), round(actual_by.get(t.party_name, 0)),
                           round(actual_by.get(t.party_name, 0) - t.target_amount)]
                          for t in sorted(targets, key=lambda x: x.party_name)[:12]]

    purch_s["vs_stock"] = []
    stock_by = {it.product: it for it in db.query(InventoryItem).all()}
    bought = defaultdict(float)
    sold_qty = defaultdict(float)
    for v in cur_purchases:
        bought[v.product] += v.quantity or 0
    for v in cur_sales:
        sold_qty[v.product] += v.quantity or 0
    for product in sorted(set(bought) | set(sold_qty) | set(stock_by))[:12]:
        it = stock_by.get(product)
        purch_s["vs_stock"].append([
            product, round(bought.get(product, 0)), round(sold_qty.get(product, 0)),
            round(it.quantity) if it else 0, it.branch if it else "—",
        ])

    return {
        "period": period, "label": PERIOD_LABELS[period],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview, "sales": sales_s, "purchases": purch_s,
        "inventory": inv_s, "cashflow": cash_s,
        "filters": {
            "products": sorted({v.product for v in sales + purchases if v.product}),
            "customers": sorted({v.party_name for v in sales}),
            "suppliers": sorted({v.party_name for v in purchases}),
            "godowns": sorted({it.branch for it in db.query(InventoryItem).all() if it.branch}),
        },
    }
 