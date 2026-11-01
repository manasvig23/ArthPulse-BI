"""
    python generate_synthetic.py            # writes into ./synthetic_data/

Produces four Excel files shaped like TallyPrime register exports:
    sales_register.xlsx, purchase_register.xlsx,
    receipts_payments.xlsx, stock_summary.xlsx

Dates run 1 Mar 2026 -> 24 Aug 2026 so they line up with the
REFERENCE_DATE (25 Aug 2026) used in app/rules.py.

Built-in situations the dashboards can detect:
  - a Section 269ST split-cash pattern (same party, same day, > Rs 2L cash)
  - slow-paying customers (overdue receivables)
  - short deliveries with debit notes (purchase variance)
  - negative, low and overstocked items
  - customers that are new, growing, declining and inactive
"""

import os
import random
from datetime import date, timedelta
 
import pandas as pd
 
random.seed(42)
 
START = date(2026, 3, 1)
END = date(2026, 8, 24)
OUT = "synthetic_data"
os.makedirs(OUT, exist_ok=True)
 
# name, territory, salesperson, orders/month, trend per month, active_from, active_to
CUSTOMERS = [
    ("Sapphire Retail",    "West",  "Ananya Shah", 5, +0.12, START, END),
    ("Metro Grocers",      "North", "Rohan Mehta", 5, -0.12, START, END),
    ("HomeStyle",          "West",  "Ananya Shah", 4,  0.00, START, END),
    ("Lakshmi Provisions", "South", "Kiran Rao",   4, +0.05, START, END),
    ("Green Basket",       "East",  "Rohan Mehta", 4, +0.10, date(2026, 7, 8), END),   # new
    ("Daily Needs",        "North", "Rohan Mehta", 3,  0.00, START, date(2026, 5, 28)),  # inactive
    ("Fresh Mart",         "South", "Kiran Rao",   5, +0.15, START, END),
    ("Urban Pantry",       "West",  "Ananya Shah", 3,  0.00, START, END),
    ("Kisan Stores",       "East",  "Kiran Rao",   4, -0.10, START, END),
    ("Nature's Basket",    "North", "Rohan Mehta", 3, +0.08, START, END),
    ("Bharat Bazaar",      "South", "Kiran Rao",   4,  0.00, START, END),
    ("Sunrise Supermart",  "East",  "Ananya Shah", 3, +0.05, START, END),
]
SLOW_PAYERS = {"Metro Grocers", "HomeStyle", "Kisan Stores"}
 
# name, category, unit price
PRODUCTS = [
    ("Organic Oats 1kg",       "Breakfast", 210),
    ("Almond Granola 500g",    "Breakfast", 260),
    ("Wildflower Honey 500g",  "Honey",     267),
    ("Chia Seed Mix 500g",     "Seeds",     288),
    ("Peanut Butter 340g",     "Spreads",   190),
    ("Muesli 750g",            "Breakfast", 240),
    ("Cashew Pack 250g",       "Dry Fruits", 310),
    ("Jaggery Powder 1kg",     "Staples",   120),
]
 
# supplier, item, category, unit cost
SUPPLIERS = [
    ("Apex Packaging",   "Compostable Pouches", "Packaging",    164),
    ("Harvest Foods",    "Rolled Oats Bulk",    "Raw Material", 178),
    ("Sunrise Traders",  "Almonds Premium",     "Raw Material", 289),
    ("CleanCo Supplies", "Cleaning Supplies",   "Consumables",   92),
    ("Orchard Nuts",     "Cashew Raw",          "Raw Material", 265),
    ("Golden Hive",      "Honey Bulk",          "Raw Material", 210),
]
 
DAYS = (END - START).days
 
 
def months_between(d):
    return (d.year - START.year) * 12 + d.month - START.month
 
 
# ---------------------------------------------------------------- sales
sales = []
for name, terr, rep, per_month, trend, a_from, a_to in CUSTOMERS:
    d = a_from
    while d <= a_to:
        m = months_between(d)
        weight = max(0.2, 1 + trend * m)
        if random.random() < (per_month * weight) / 30:
            prod, cat, price = random.choice(PRODUCTS)
            qty = random.choice([60, 80, 100, 120, 150, 200, 260, 320, 400])
            amount = round(qty * price * random.uniform(0.95, 1.05), -1)
            returns = 0
            if random.random() < 0.08:
                returns = round(amount * random.uniform(0.03, 0.08), -1)
            sales.append({
                "Date": d, "Particulars": name, "Item Name": prod,
                "Quantity": qty, "Amount": amount, "Returns": returns,
                "Territory": terr, "Salesperson": rep,
            })
        d += timedelta(days=1)
 
# ------------------------------------------------------------ purchases
purchases = []
po = 800
d = START
while d <= END:
    if random.random() < 0.28:
        sup, item, cat, cost = random.choice(SUPPLIERS)
        po += 1
        qty = random.choice([300, 500, 800, 1200, 1800, 2500])
        short = random.random() < 0.18
        received = int(qty * random.uniform(0.88, 0.97)) if short else qty
        age = (END - d).days
        status = "Received" if age > 20 else random.choice(["In transit", "Received", "Delayed"])
        if status != "Received" and not short:
            received = int(qty * random.choice([0, 0.5, 1]))
        purchases.append({
            "Date": d, "Particulars": sup, "Item Name": item,
            "PO Number": f"PO-{po}", "Quantity": qty, "Received Qty": received,
            "Amount": round(qty * cost * random.uniform(0.97, 1.03), -1),
            "Debit Note": f"DN-{100 + len(purchases)}" if short else "",
            "Status": status,
        })
    d += timedelta(days=1)
 
# ------------------------------------------------- receipts & payments
rp = []
 
 
def add_rp(day, party, vtype, amount, mode, due, status, nature="", tds=0):
    rp.append({"Date": day, "Particulars": party, "Vch Type": vtype,
               "Amount": amount, "Mode": mode, "Due Date": due, "Status": status,
               "Nature": nature, "TDS Deducted": tds})
 
 
for s in sales:
    net = s["Amount"] - s["Returns"]
    age = (END - s["Date"]).days
    slow = s["Particulars"] in SLOW_PAYERS
    p_paid = 0.97 if age > 75 else 0.8 if age > 45 else 0.5
    if slow:
        p_paid -= 0.35
    due = s["Date"] + timedelta(days=30)
    if random.random() < p_paid:
        lag = random.randint(35, 70) if slow else random.randint(12, 38)
        pay_day = min(s["Date"] + timedelta(days=lag), END)
        mode = "Cash" if net <= 40000 and random.random() < 0.35 else "Bank"
        add_rp(pay_day, s["Particulars"], "Receipt", net, mode, due, "Cleared")
    else:
        add_rp(s["Date"], s["Particulars"], "Receipt", net, "Bank", due, "Pending")
 
for p in purchases:
    age = (END - p["Date"]).days
    due = p["Date"] + timedelta(days=30)
    if age > 35 and random.random() < 0.9:
        pay_day = min(p["Date"] + timedelta(days=random.randint(22, 40)), END)
        add_rp(pay_day, p["Particulars"], "Payment", p["Amount"], "Bank", due, "Cleared")
    else:
        add_rp(p["Date"], p["Particulars"], "Payment", p["Amount"], "Bank", due, "Pending")
 
# Deliberate Section 269ST pattern: split cash receipts, same party + day
for amt in (120000, 95000):
    add_rp(date(2026, 7, 20), "Sapphire Retail", "Receipt", amt, "Cash",
           date(2026, 7, 20), "Cleared")
# a second, borderline-clean day (exactly under the limit -> should NOT alert)
for amt in (90000, 100000):
    add_rp(date(2026, 6, 15), "Fresh Mart", "Receipt", amt, "Cash",
           date(2026, 6, 15), "Cleared")
 
# ============================================================ COMPLIANCE DATA
# Everything below uses NO randomness, so the sales / purchase / receipt data
# above is unchanged by it.
 
# --- planted: Section 40A(3) cash payments
add_rp(date(2026, 8, 12), "Apex Packaging", "Payment", 6000, "Cash", date(2026, 8, 12), "Cleared")
add_rp(date(2026, 8, 12), "Apex Packaging", "Payment", 7000, "Cash", date(2026, 8, 12), "Cleared")   # 13,000 in a day -> flag
add_rp(date(2026, 8, 14), "Swift Logistics", "Payment", 30000, "Cash", date(2026, 8, 14), "Cleared")  # transporter, under 35,000 -> ok
add_rp(date(2026, 8, 18), "CleanCo Supplies", "Payment", 9000, "Cash", date(2026, 8, 18), "Cleared")  # under 10,000 -> ok
 
# --- planted: MSME 43B(h) bills (open payables)
po += 1
purchases.append({"Date": date(2026, 7, 10), "Particulars": "Golden Hive", "Item Name": "Honey Bulk",
                  "PO Number": f"PO-{po}", "Quantity": 1000, "Received Qty": 1000, "Amount": 210000,
                  "Debit Note": "", "Status": "Received"})
add_rp(date(2026, 7, 10), "Golden Hive", "Payment", 210000, "Bank", date(2026, 8, 9), "Pending")   # day 46 of 45 -> breached
po += 1
purchases.append({"Date": date(2026, 8, 20), "Particulars": "Apex Packaging", "Item Name": "Compostable Pouches",
                  "PO Number": f"PO-{po}", "Quantity": 500, "Received Qty": 500, "Amount": 80000,
                  "Debit Note": "", "Status": "Received"})
add_rp(date(2026, 8, 20), "Apex Packaging", "Payment", 80000, "Bank", date(2026, 9, 19), "Pending")  # day 5 of 15 -> ok
 
# --- planted: TDS payments (Amount = gross bill value, TDS Deducted separate)
for d in (date(2026, 4, 10), date(2026, 5, 12), date(2026, 6, 15), date(2026, 7, 18)):
    add_rp(d, "BuildRight Works", "Payment", 30000, "Bank", d, "Cleared", "Contractor", 0)      # 1.2L, no TDS -> flag
add_rp(date(2026, 6, 5), "Sharma Contractors", "Payment", 15000, "Bank", date(2026, 6, 5), "Cleared", "Contractor", 0)
add_rp(date(2026, 7, 6), "Sharma Contractors", "Payment", 13000, "Bank", date(2026, 7, 6), "Cleared", "Contractor", 0)  # 28k, under limits -> ok
add_rp(date(2026, 5, 20), "CA Desai & Associates", "Payment", 50000, "Bank", date(2026, 5, 20), "Cleared", "Professional", 2500)
add_rp(date(2026, 7, 20), "CA Desai & Associates", "Payment", 30000, "Bank", date(2026, 7, 20), "Cleared", "Professional", 1500)  # 5% not 10% -> short
add_rp(date(2026, 6, 25), "Kiran Legal", "Payment", 90000, "Bank", date(2026, 6, 25), "Cleared", "Professional", 9000)  # correct -> ok
for m in (4, 5, 6, 7, 8):
    add_rp(date(2026, m, 5), "Shah Properties", "Payment", 60000, "Bank", date(2026, m, 5), "Cleared", "Rent-Building", 0)  # no TDS -> flag
add_rp(date(2026, 7, 15), "Star Agencies", "Payment", 30000, "Bank", date(2026, 7, 15), "Cleared", "Commission", 0)   # flag
add_rp(date(2026, 7, 22), "Agent Raman", "Payment", 18000, "Bank", date(2026, 7, 22), "Cleared", "Commission", 0)    # under 20,000 -> ok
 
# --- GSTIN, invoice numbers and GST on every sales / purchase row
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
 
 
def fake_gstin(name):
    n = sum(ord(c) * (i + 3) for i, c in enumerate(name))
    pan = "".join(LETTERS[(n // (7 ** k)) % len(LETTERS)] for k in range(5)) + f"{n % 10000:04d}" + LETTERS[n % len(LETTERS)]
    return f"27{pan}1Z{n % 10}"
 
 
SALES_GST = {"Organic Oats 1kg": 5, "Almond Granola 500g": 18, "Wildflower Honey 500g": 5,
             "Chia Seed Mix 500g": 5, "Peanut Butter 340g": 12, "Muesli 750g": 18,
             "Cashew Pack 250g": 12, "Jaggery Powder 1kg": 5}
PURCHASE_GST = {"Compostable Pouches": 18, "Rolled Oats Bulk": 5, "Almonds Premium": 5,
                "Cleaning Supplies": 18, "Cashew Raw": 5, "Honey Bulk": 5}
 
 
def number_rows(rows, prefix):
    order = sorted(range(len(rows)), key=lambda i: (rows[i]["Date"], i))
    for n, i in enumerate(order, 1):
        rows[i]["Invoice No"] = f"{prefix}/{n:04d}"
 
 
number_rows(sales, "S/26-27")
for row in sales:
    row["GSTIN"] = fake_gstin(row["Particulars"])
    row["GST"] = round(row["Amount"] * SALES_GST[row["Item Name"]] / 100)
 
number_rows(purchases, "SI")
for row in purchases:
    row["GSTIN"] = fake_gstin(row["Particulars"])
    row["GST"] = round(row["Amount"] * PURCHASE_GST[row["Item Name"]] / 100)
 
# --- GST portal data: GSTR-2B (what suppliers reported) and monthly returns
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
ym = lambda d: d.strftime("%Y-%m")
 
# Invoices that suppliers have NOT reported (so they are absent from GSTR-2B)
planted_pos = {r["PO Number"] for r in purchases[-2:]}          # never hide the MSME bills
aug = sorted([p for p in purchases if ym(p["Date"]) == "2026-08" and p["PO Number"] not in planted_pos],
             key=lambda p: -p["GST"])
missing, seen = [], set()
for p in aug:                                                    # largest GST, one per supplier
    if p["Particulars"] not in seen:
        missing.append(p); seen.add(p["Particulars"])
    if len(missing) == 2:
        break
jun = sorted([p for p in purchases if ym(p["Date"]) == "2026-06"], key=lambda p: p["GST"])
if jun and jun[0]["GST"] < 10000:
    missing.append(jun[0])                                       # small gap, must stay below the threshold
missing_ids = {(p["GSTIN"], p["Invoice No"]) for p in missing}
 
gstr2b = [{"Month": ym(p["Date"]), "Supplier GSTIN": p["GSTIN"], "Supplier": p["Particulars"],
           "Invoice No": p["Invoice No"], "Taxable Value": p["Amount"], "Tax": p["GST"]}
          for p in purchases if (p["GSTIN"], p["Invoice No"]) not in missing_ids]
 
returns = []
for m in MONTHS:
    out_tax = sum(r["GST"] for r in sales if ym(r["Date"]) == m)
    itc = sum(r["GST"] for r in purchases if ym(r["Date"]) == m)
    paid = out_tax - {"2026-07": 30000, "2026-05": 2000}.get(m, 0)   # July: real gap, May: tiny gap
    returns.append({"Month": m, "GSTR-1 Tax": out_tax, "GSTR-3B Tax Paid": paid, "GSTR-3B ITC Claimed": itc})
 
# --- who each party is (facts Tally registers do not export)
PROFILES = [
    # party, MSME, agreement, transporter, payee type
    ("Apex Packaging", "Yes", "No", "No", "Company"),
    ("Harvest Foods", "No", "No", "No", "Company"),
    ("Sunrise Traders", "No", "No", "No", "Company"),
    ("CleanCo Supplies", "Yes", "Yes", "No", "Company"),
    ("Orchard Nuts", "No", "No", "No", "Company"),
    ("Golden Hive", "Yes", "Yes", "No", "Company"),
    ("Swift Logistics", "No", "No", "Yes", "Company"),
    ("BuildRight Works", "No", "No", "No", "Company"),
    ("Sharma Contractors", "No", "No", "No", "Individual"),
    ("CA Desai & Associates", "No", "No", "No", "Company"),
    ("Kiran Legal", "No", "No", "No", "Company"),
    ("Shah Properties", "No", "No", "No", "Individual"),
    ("Star Agencies", "No", "No", "No", "Company"),
    ("Agent Raman", "No", "No", "No", "Individual"),
]
profile_rows = [{"Party": n, "GSTIN": fake_gstin(n), "MSME": ms, "Written Agreement": ag,
                 "Transporter": tr, "Payee Type": pt} for n, ms, ag, tr, pt in PROFILES]
 
# ---------------------------------------------------------------- stock
stock = [
    # item, sku, category, godown, qty, unit value, reorder level
    ("Organic Oats 1kg",      "FG-101", "Breakfast",    "Central Godown", -12, 260, 50),
    ("Almond Granola 500g",   "FG-118", "Breakfast",    "Mumbai Branch",   18, 292, 30),
    ("Wildflower Honey 500g", "FG-109", "Honey",        "Pune Branch",     86, 150, 25),
    ("Chia Seed Mix 500g",    "FG-145", "Seeds",        "Mumbai Branch",   67, 120, 20),
    ("Peanut Butter 340g",    "FG-152", "Spreads",      "Central Godown", 140, 110, 40),
    ("Muesli 750g",           "FG-160", "Breakfast",    "Pune Branch",     95, 140, 30),
    ("Cashew Pack 250g",      "FG-171", "Dry Fruits",   "Mumbai Branch",   22, 200, 25),
    ("Jaggery Powder 1kg",    "FG-180", "Staples",      "Central Godown", 410,  80, 60),
    ("Compostable Pouches",   "PK-024", "Packaging",    "Central Godown", 120, 150, 40),
    ("Rolled Oats Bulk",      "RM-017", "Raw Material", "Central Godown", 245, 900, 60),
    ("Almonds Premium",       "RM-021", "Raw Material", "Central Godown", 310, 290, 80),
    ("Honey Bulk",            "RM-030", "Raw Material", "Pune Branch",     54, 210, 30),
]
# Sales volumes are in the hundreds of units per order, so stock on hand
# is scaled to match (otherwise "days of inventory" comes out absurdly low).
STOCK_SCALE = 10
stock_rows = [{
    "Item Name": n, "SKU": sku, "Category": c, "Godown": g,
    "Closing Qty": q * STOCK_SCALE, "Closing Value": max(q, 0) * STOCK_SCALE * uv,
    "Reorder Level": r * STOCK_SCALE,
} for n, sku, c, g, q, uv, r in stock]
 
 
def save(rows, name):
    df = pd.DataFrame(rows).sort_values(
        "Date") if rows and "Date" in rows[0] else pd.DataFrame(rows)
    df.to_excel(os.path.join(OUT, name), index=False)
    print(f"{name}: {len(df)} rows")
 
 
save(sales, "sales_register.xlsx")
save(purchases, "purchase_register.xlsx")
save(rp, "receipts_payments.xlsx")
save(stock_rows, "stock_summary.xlsx")
save(profile_rows, "supplier_profile.xlsx")
save(gstr2b, "gstr2b_invoices.xlsx")
save(returns, "gst_returns.xlsx")
 
print("\nPlanted GST gaps:")
for p in missing:
    print(f"  missing from GSTR-2B: {p['Particulars']} {p['Invoice No']} tax {p['GST']}")