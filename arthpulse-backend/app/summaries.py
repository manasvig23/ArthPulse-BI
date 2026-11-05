from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import rules
from .models import Voucher, InventoryItem, PartyMaster, SalesTarget, StockMovement
from .rules import REFERENCE_DATE
PERIOD_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "yearly": 365,
}

PERIOD_LABELS = {
    "daily": "Today",
    "weekly": "This week",
    "monthly": "This month",
    "yearly": "This year",
}

AGEING_ORDER = ["0–30 days", "31–60 days", "61–90 days", "90+ days"]
# ------------------------------------------------------------- windows

def as_of_date(db: Session) -> date:
    latest = db.query(func.max(Voucher.voucher_date)).scalar()
    return min(latest, REFERENCE_DATE) if latest else REFERENCE_DATE


def get_window(
    db: Session,
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    comparison: str = "previous_period",
):
    """
    Returns current and comparison date windows.
    """

    if financial_year:
        try:
            first_year = int(financial_year.split("-")[0])
            start = date(first_year, 4, 1)
            end = date(first_year + 1, 3, 31)
        except (ValueError, IndexError):
            raise ValueError("Invalid financial year. Use YYYY-YY format.")

    elif start_date and end_date:
        start = start_date
        end = end_date

    else:
        if period not in PERIOD_DAYS:
            period = "monthly"

        end = as_of_date(db)
        start = end - timedelta(days=PERIOD_DAYS[period] - 1)

    if start > end:
        raise ValueError("Start date cannot be after end date.")

    if comparison == "none":
        return start, end, None, None

    if comparison == "previous_month":
        prev_end = start - timedelta(days=1)
        prev_start = date(prev_end.year, prev_end.month, 1)
        return start, end, prev_start, prev_end

    if comparison == "previous_year":
        try:
            prev_start = start.replace(year=start.year - 1)
            prev_end = end.replace(year=end.year - 1)
        except ValueError:
            prev_start = start.replace(year=start.year - 1, day=28)
            prev_end = end.replace(year=end.year - 1, day=28)

        return start, end, prev_start, prev_end

    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    return start, end, prev_start, prev_end

def _within(rows, start, end):
    if start is None or end is None:
        return []
    return [
        v for v in rows
        if v.voucher_date and start <= v.voucher_date <= end
    ]

def _net(v):
    return v.amount - (v.returns_amount or 0)

def _pct_change(cur, prev):
    return None if not prev else round((cur - prev) / prev * 100, 1)

def _money(x):
    return f"₹{x / 100000:.1f}L" if abs(x) >= 100000 else f"₹{x:,.0f}"

def _days(value):
    return "—" if value is None else f"{value:.0f} days"

def _filter_transactions(
    rows,
    product=None,
    party=None,
    location=None,
):
    """Apply transaction-level dimension filters."""

    result = []

    for v in rows:
        if product and v.product != product:
            continue

        if party and v.party_name != party:
            continue

        if location and (v.godown or "Main") != location:
            continue

        result.append(v)

    return result
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

    names = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    gross = defaultdict(float)
    net = defaultdict(float)

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

    prev_net = (
        sum(_net(v) for v in _within(sales, prev_start, prev_end))
        if prev_start and prev_end else 0
    )

    territories = defaultdict(float)

    for v in cur:
        territories[v.territory or "Unassigned"] += _net(v)

    party_segment = {v.party_name: v.segment for v in sales}
    segments = defaultdict(int)

    for seg in set(party_segment.values()):
        segments[seg or "Unclassified"] += 1

    product_rev = defaultdict(float)
    bought = defaultdict(set)
    orders = defaultdict(list)
    party_rev = defaultdict(float)

    for v in sales:
        product_rev[v.product] += _net(v)
        bought[v.party_name].add(v.product)
        orders[v.party_name].append(v.amount)
        party_rev[v.party_name] += _net(v)

    ranked_products = sorted(
        product_rev,
        key=product_rev.get,
        reverse=True,
    )

    cross_sell = []

    for party in sorted(party_rev, key=party_rev.get, reverse=True):
        if party_segment.get(party) == "Inactive":
            continue

        missing = [
            p for p in ranked_products
            if p not in bought[party]
        ]

        if missing:
            avg_order = sum(orders[party]) / len(orders[party])

            cross_sell.append([
                party,
                f"Recommend {missing[0]}",
                f"~{_money(avg_order)} per order",
            ])

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

    for v in cur:
        net_v = _net(v)

        customer_rev[v.party_name] += net_v
        product_rev[v.product or "Unspecified"] += net_v
        group_rev[v.category or "Unassigned"] += net_v
        city_rev[v.city or "Unassigned"] += net_v
        state_rev[v.state or "Unassigned"] += net_v
        pincode_rev[v.pincode or "—"] += net_v
        person_rev[v.salesperson or "Unassigned"] += net_v

        discount_total += (
            v.discount_amount
            or (v.amount * (v.discount_pct or 0) / 100)
        )

    def _rank(d, n=5):
        ordered = sorted(
            d.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )

        top_names = {x[0] for x in ordered[:n]}

        return {
            "top": [
                [k, round(v)]
                for k, v in ordered[:n]
                if v > 0
            ],
            "bottom": [
                [k, round(v)]
                for k, v in ordered[-n:]
                if v > 0 and k not in top_names
            ],
        }

    basket_key = defaultdict(set)

    for v in cur:
        basket_key[(v.party_name, v.voucher_date)].add(v.product)

    pair_count = defaultdict(int)

    for items in basket_key.values():
        items = [p for p in items if p]

        for i, a in enumerate(sorted(items)):
            for b in sorted(items)[i + 1:]:
                pair_count[(a, b)] += 1

    basket = [
        [a, b, n]
        for (a, b), n in sorted(
            pair_count.items(),
            key=lambda kv: -kv[1],
        )[:5]
    ]

    history = []

    for party, amt in sorted(
        customer_rev.items(),
        key=lambda kv: -kv[1],
    )[:8]:
        mix = defaultdict(float)

        for v in sales:
            if v.party_name == party:
                mix[v.product or "Unspecified"] += _net(v)

        history.append({
            "customer": party,
            "period_sales": round(amt),
            "products": [
                [k, round(v)]
                for k, v in sorted(
                    mix.items(),
                    key=lambda kv: -kv[1],
                )[:4]
            ],
        })

    return {
        "gross": round(gross),
        "returns": round(returns),
        "net": round(net),
        "returns_pct": round(returns / gross * 100, 1) if gross else 0,
        "growth": _pct_change(net, prev_net),
        "territories": {
            k: round(v)
            for k, v in territories.items()
            if v > 0
        },
        "segments": dict(segments),
        "cross_sell": cross_sell,
        "customers": _rank(customer_rev),
        "products": _rank(product_rev),
        "groups": _rank(group_rev),
        "cities": {
            k: round(v)
            for k, v in city_rev.items()
            if v > 0
        },
        "states": {
            k: round(v)
            for k, v in state_rev.items()
            if v > 0
        },
        "pincodes": {
            k: round(v)
            for k, v in list(pincode_rev.items())[:8]
            if v > 0
        },
        "salespeople": {
            k: round(v)
            for k, v in person_rev.items()
            if v > 0
        },
        "basket": basket,
        "discount_value": round(discount_total),
        "customer_history": history,
    }

def _purchases_section(purchases, cur, prev_start, prev_end):
    total = sum(v.amount for v in cur)

    prev_total = (
        sum(v.amount for v in _within(purchases, prev_start, prev_end))
        if prev_start and prev_end else 0
    )

    short = [v for v in cur if v.debit_note]

    debit_value = sum(
        (
            (v.quantity - (v.received_quantity or 0))
            / v.quantity
        ) * v.amount
        for v in short
        if v.quantity
    )

    open_pos = [
        v for v in purchases
        if v.status and v.status != "Received"
    ]

    spend = defaultdict(float)

    for v in cur:
        spend[v.party_name] += v.amount

    ordered = sorted(
        spend.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )

    supplier_spend = {
        k: round(v)
        for k, v in ordered[:3]
    }

    other = sum(v for _, v in ordered[3:])

    if other:
        supplier_spend["Other suppliers"] = round(other)

    top_name, top_amt = (
        ordered[0] if ordered else ("—", 0)
    )

    series = defaultdict(list)

    for v in sorted(purchases, key=lambda x: x.voucher_date):
        if v.quantity:
            series[(v.party_name, v.product)].append(
                v.amount / v.quantity
            )

    moves = []

    for (supplier, product), costs in series.items():
        if len(costs) >= 2:
            base = sum(costs[:-1]) / len(costs[:-1])

            if base:
                change = (costs[-1] - base) / base * 100
                moves.append((
                    abs(change),
                    supplier,
                    product,
                    change,
                ))

    moves.sort(reverse=True)

    price_moves = []

    for _, supplier, product, change in moves[:3]:
        text = (
            "No change"
            if abs(change) < 0.5
            else f"{'↑' if change > 0 else '↓'} {abs(change):.1f}%"
        )

        price_moves.append([supplier, text, product])

    return {
        "total": round(total),
        "growth": _pct_change(total, prev_total),
        "debit_notes": len(short),
        "debit_note_value": round(debit_value),
        "open_pos": len(open_pos),
        "open_po_value": round(sum(v.amount for v in open_pos)),
        "top_supplier": top_name,
        "top_share": round(top_amt / total * 100) if total else 0,
        "supplier_spend": supplier_spend,
        "price_moves": price_moves,
        "vs_stock": None,
    }


def _inventory_section(db, sales, as_of, location=None):
    query = db.query(InventoryItem)

    if location:
        query = query.filter(InventoryItem.branch == location)

    items = query.all()

    risk = {
        it.id: rules._inventory_risk(it)
        for it in items
    }

    stock_value = sum(it.value for it in items)

    low = sum(
        1 for it in items
        if risk[it.id] == "Low stock"
    )

    negative = sum(
        1 for it in items
        if risk[it.id] == "Negative stock"
    )

    overstock_value = sum(
        it.value for it in items
        if risk[it.id] == "Overstock"
    )

    slow = sum(
        it.value for it in items
        if it.movement == "Slow-moving"
    )

    non = sum(
        it.value for it in items
        if it.movement == "Non-moving"
    )

    net_90 = sum(
        _net(v)
        for v in _within(
            sales,
            as_of - timedelta(days=89),
            as_of,
        )
    )

    turnover = (
        (net_90 / stock_value) * (365 / 90)
        if stock_value else None
    )

    inv_days = (
        (stock_value / net_90 * 90)
        if net_90 else None
    )

    godowns = defaultdict(
        lambda: {"qty": 0, "value": 0, "skus": 0}
    )

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

        ageing_rows.append([
            it.product,
            it.branch,
            days if days is not None else "—",
            it.movement,
            round(it.value),
        ])

    moves_query = db.query(StockMovement)

    if location:
        moves_query = moves_query.filter(
            StockMovement.godown == location
        )

    moves = (
        moves_query
        .order_by(StockMovement.movement_date.desc())
        .limit(40)
        .all()
    )

    move_rows = [
        [
            m.movement_date.isoformat() if m.movement_date else "",
            m.voucher_type,
            m.product,
            m.godown,
            m.inward_qty,
            m.outward_qty,
        ]
        for m in moves
    ]

    high_slow = [
        [it.product, it.branch, round(it.value), it.movement]
        for it in items
        if it.movement in ("Slow-moving", "Non-moving")
        and it.value > 0
    ]

    high_slow.sort(key=lambda r: -r[2])

    return {
        "stock_value": round(stock_value),
        "low_stock": low,
        "negative": negative,
        "overstock_value": round(overstock_value),
        "inventory_days": inv_days,
        "efficiency": [
            [
                "Stock turnover (sales ÷ stock, annualised)",
                f"{turnover:.1f}x" if turnover else "—",
            ],
            ["Days of inventory", _days(inv_days)],
            ["Slow-moving value", _money(slow)],
            ["Non-moving value", _money(non)],
        ],
        "godowns": {
            k: {
                "qty": round(v["qty"]),
                "value": round(v["value"]),
                "skus": v["skus"],
            }
            for k, v in godowns.items()
        },
        "ageing": ageing_rows[:20],
        "movements": move_rows,
        "high_value_slow": high_slow[:8],
    }


def _cashflow_section(
    db,
    sales,
    purchases,
    as_of,
    inv_days,
    location=None,
):
    rows = rules.get_payment_table(db)

    if location:
        # Payment-table rows do not expose a location field.
        # Leave this section unfiltered rather than incorrectly
        # excluding or assigning payment records.
        pass

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

    top_party, top_amt = (
        max(by_party.items(), key=lambda kv: kv[1])
        if by_party else ("—", 0)
    )

    s90 = sum(
        _net(v)
        for v in _within(
            sales,
            as_of - timedelta(days=89),
            as_of,
        )
    )

    p90 = sum(
        v.amount
        for v in _within(
            purchases,
            as_of - timedelta(days=89),
            as_of,
        )
    )

    rec_days = receivables / (s90 / 90) if s90 else None
    pay_days = payables / (p90 / 90) if p90 else None

    ccc = (
        rec_days + inv_days - pay_days
        if None not in (rec_days, inv_days, pay_days)
        else None
    )

    stock_value = db.query(
        func.sum(InventoryItem.value)
    ).scalar() or 0

    pay_age = {b: 0 for b in AGEING_ORDER}

    for r in pay:
        pay_age[r[5]] = pay_age.get(r[5], 0) + r[4]

    limits = {
        p.party_name: p.credit_limit
        for p in db.query(PartyMaster).all()
        if p.credit_limit
    }

    outstanding = defaultdict(float)

    for r in rec:
        outstanding[r[1]] += r[4]

    breaches = [
        [party, round(amt), round(limits[party])]
        for party, amt in outstanding.items()
        if party in limits and amt > limits[party]
    ]

    behaviour = []

    cleared = (
        db.query(Voucher)
        .filter(
            Voucher.voucher_type == "Receipt",
            Voucher.status == "Cleared",
        )
        .all()
    )

    lags = defaultdict(list)

    for v in cleared:
        if v.due_date and v.voucher_date:
            lags[v.party_name].append(
                (v.voucher_date - v.due_date).days + 30
            )

    for party, days in lags.items():
        avg = sum(days) / len(days)

        behaviour.append([
            party,
            round(avg, 1),
            "Late" if avg > 35 else "On time",
        ])

    behaviour.sort(key=lambda r: -r[1])

    cash_bank = {
        "cash_in": 0,
        "cash_out": 0,
        "bank_in": 0,
        "bank_out": 0,
    }

    payment_vouchers = (
        db.query(Voucher)
        .filter(
            Voucher.voucher_type.in_(["Receipt", "Payment"])
        )
        .all()
    )

    for v in payment_vouchers:
        key_in = (
            "cash_in"
            if v.payment_mode == "Cash"
            else "bank_in"
        )

        key_out = (
            "cash_out"
            if v.payment_mode == "Cash"
            else "bank_out"
        )

        if v.voucher_type == "Receipt":
            cash_bank[key_in] += v.amount
        else:
            cash_bank[key_out] += v.amount

    due_today = sum(
        r[4]
        for r in rec + pay
        if r[3] == as_of.isoformat()
    )

    return {
        "receivables": round(receivables),
        "overdue_receivables": round(
            sum(r[4] for r in rec if r[6] == "Overdue")
        ),
        "payables": round(payables),
        "payables_due_week": round(
            sum(r[4] for r in pay if r[6] == "Due this week")
        ),
        "top_debtor": top_party,
        "top_debtor_share": (
            round(top_amt / receivables * 100)
            if receivables else 0
        ),
        "top_debtor_amount": round(top_amt),
        "ageing": {
            k: round(v)
            for k, v in ageing.items()
        },
        "net_working_capital": round(
            receivables + stock_value - payables
        ),
        "working_capital": [
            ["Receivable days", _days(rec_days)],
            ["Payable days", _days(pay_days)],
            ["Inventory days", _days(inv_days)],
            ["Cash conversion cycle", _days(ccc)],
        ],
        "payable_ageing": {
            k: round(v)
            for k, v in pay_age.items()
        },
        "credit_breaches": breaches,
        "payment_behaviour": behaviour[:8],
        "cash_bank": {
            k: round(v)
            for k, v in cash_bank.items()
        },
        "due_today": round(due_today),
        "forecast_in": round(receivables),
        "forecast_out": round(payables),
    }
# ---------------------------------------------------------------- main

def build_summary(
    db: Session,
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    customer: str | None = None,
    supplier: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
):
    if period not in PERIOD_DAYS:
        period = "monthly"

    if comparison not in (
        "previous_period",
        "previous_month",
        "previous_year",
        "none",
    ):
        comparison = "previous_period"

    start, end, prev_start, prev_end = get_window(
        db,
        period,
        start_date,
        end_date,
        financial_year,
        comparison,
    )

    all_sales = (
        db.query(Voucher)
        .filter(Voucher.voucher_type == "Sales")
        .all()
    )

    all_purchases = (
        db.query(Voucher)
        .filter(Voucher.voucher_type == "Purchase")
        .all()
    )

    # Apply the relevant dimension filters before calculations.
    sales = _filter_transactions(
        all_sales,
        product=product,
        party=customer,
        location=location,
    )

    purchases = _filter_transactions(
        all_purchases,
        product=product,
        party=supplier,
        location=location,
    )

    cur_sales = _within(sales, start, end)
    cur_purchases = _within(purchases, start, end)

    sales_s = _sales_section(
        sales,
        cur_sales,
        start,
        end,
        prev_start,
        prev_end,
    )

    purch_s = _purchases_section(
        purchases,
        cur_purchases,
        prev_start,
        prev_end,
    )

    inv_s = _inventory_section(
        db,
        sales,
        end,
        location,
    )

    cash_s = _cashflow_section(
        db,
        sales,
        purchases,
        end,
        inv_s["inventory_days"],
        location,
    )

    proxy = sales_s["net"] - purch_s["total"]

    overview = {
        "net_sales": sales_s["net"],
        "growth": sales_s["growth"],
        "sales_less_purchases": proxy,
        "margin_pct": (
            round(proxy / sales_s["net"] * 100, 1)
            if sales_s["net"] else 0
        ),
        "receivables": cash_s["receivables"],
        "overdue": cash_s["overdue_receivables"],
        "stock_value": inv_s["stock_value"],
        "replenishment_risks": (
            inv_s["low_stock"] + inv_s["negative"]
        ),
        "trend": _month_trend(sales, end),
    }

    sales_s["trend"] = overview["trend"]

    month_key = end.strftime("%Y-%m")

    targets = (
        db.query(SalesTarget)
        .filter(SalesTarget.month == month_key)
        .all()
    )

    actual_by = defaultdict(float)

    for v in cur_sales:
        actual_by[v.party_name] += _net(v)

    sales_s["targets"] = [
        [
            t.party_name,
            round(t.target_amount),
            round(actual_by.get(t.party_name, 0)),
            round(
                actual_by.get(t.party_name, 0)
                - t.target_amount
            ),
        ]
        for t in sorted(
            targets,
            key=lambda x: x.party_name,
        )[:12]
        if not customer or t.party_name == customer
    ]

    purch_s["vs_stock"] = []

    stock_query = db.query(InventoryItem)

    if location:
        stock_query = stock_query.filter(
            InventoryItem.branch == location
        )

    stock_items = stock_query.all()
    stock_by = {
        it.product: it
        for it in stock_items
    }

    bought = defaultdict(float)
    sold_qty = defaultdict(float)

    for v in cur_purchases:
        bought[v.product] += v.quantity or 0

    for v in cur_sales:
        sold_qty[v.product] += v.quantity or 0

    for product_name in sorted(
        set(bought) | set(sold_qty) | set(stock_by)
    )[:12]:
        it = stock_by.get(product_name)

        purch_s["vs_stock"].append([
            product_name,
            round(bought.get(product_name, 0)),
            round(sold_qty.get(product_name, 0)),
            round(it.quantity) if it else 0,
            it.branch if it else "—",
        ])

    # Filter choices remain global so users can change selections
    # without losing the other available options.
    all_inventory = db.query(InventoryItem).all()

    return {
        "period": period,
        "label": (
            financial_year
            if financial_year
            else f"{start.isoformat()} to {end.isoformat()}"
            if start_date and end_date
            else PERIOD_LABELS[period]
        ),
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "comparison_start": (
                prev_start.isoformat()
                if prev_start else None
            ),
            "comparison_end": (
                prev_end.isoformat()
                if prev_end else None
            ),
            "comparison": comparison,
        },
        "overview": overview,
        "sales": sales_s,
        "purchases": purch_s,
        "inventory": inv_s,
        "cashflow": cash_s,
        "filters": {
            "products": sorted({
                v.product
                for v in all_sales + all_purchases
                if v.product
            }),
            "customers": sorted({
                v.party_name
                for v in all_sales
                if v.party_name
            }),
            "suppliers": sorted({
                v.party_name
                for v in all_purchases
                if v.party_name
            }),
            "godowns": sorted({
                it.branch
                for it in all_inventory
                if it.branch
            } | {
                v.godown
                for v in all_sales + all_purchases
                if v.godown
            }),
        },
    }