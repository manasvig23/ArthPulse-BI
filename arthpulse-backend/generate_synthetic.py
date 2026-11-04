"""
    python generate_synthetic.py            # writes into ./synthetic_data/

Produces TallyPrime-identical register exports and master files:
    - sales_register.xlsx (includes City, State, Pincode, Discount %, Gross vs Net)
    - purchase_register.xlsx
    - receipts_payments.xlsx
    - stock_summary.xlsx
    - stock_movement.xlsx (Inward, Outward, Transfer log across godowns)
    - customer_profile.xlsx (Territory, City, State, Pincode, Credit Limit)
    - sales_targets.xlsx (Monthly targets vs actual comparison)
    - sync_status.xlsx (Last updated timestamp, sync success state)
    - gstr2b_invoices.xlsx & gst_returns.xlsx
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

STATE_CODES = {
    "Maharashtra": "27", "Delhi": "07", "Karnataka": "29", "West Bengal": "19",
    "Punjab": "03", "Tamil Nadu": "33", "Gujarat": "24", "Bihar": "10",
    "Rajasthan": "08", "Telangana": "36", "Assam": "18"
}

def fake_gstin(name, state):
    code = STATE_CODES.get(state, "27")
    n = sum(ord(c) * (i + 3) for i, c in enumerate(name))
    pan = "".join("ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(n // (7 ** k)) % 26] for k in range(5)) + f"{n % 10000:04d}" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[n % 26]
    return f"{code}{pan}1Z{n % 10}"

# Customer Master: name, territory, salesperson, city, state, pincode, credit_limit, orders/month, trend, active_from, active_to
CUSTOMERS = [
    ("Sapphire Retail",    "West",  "Ananya Shah", "Mumbai",     "Maharashtra", "400001",  900000, 5, +0.12, START, END), # Will breach limit
    ("Metro Grocers",      "North", "Rohan Mehta", "Delhi",      "Delhi",       "110001",  600000, 5, -0.12, START, END), # Will breach limit
    ("HomeStyle",          "West",  "Ananya Shah", "Pune",       "Maharashtra", "411001",  800000, 4,  0.00, START, END),
    ("Lakshmi Provisions", "South", "Kiran Rao",   "Bengaluru",  "Karnataka",   "560001", 1200000, 4, +0.05, START, END),
    ("Green Basket",       "East",  "Rohan Mehta", "Kolkata",    "West Bengal", "700001",  600000, 4, +0.10, date(2026, 7, 8), END),
    ("Daily Needs",        "North", "Rohan Mehta", "Chandigarh", "Punjab",      "160001",  500000, 3,  0.00, START, date(2026, 5, 28)),
    ("Fresh Mart",         "South", "Kiran Rao",   "Chennai",    "Tamil Nadu",  "600001", 2000000, 5, +0.15, START, END),
    ("Urban Pantry",       "West",  "Ananya Shah", "Ahmedabad",  "Gujarat",     "380001",  700000, 3,  0.00, START, END),
    ("Kisan Stores",       "East",  "Kiran Rao",   "Patna",      "Bihar",       "800001",  900000, 4, -0.10, START, END),
    ("Nature's Basket",    "North", "Rohan Mehta", "Jaipur",     "Rajasthan",   "302001", 1100000, 3, +0.08, START, END),
    ("Bharat Bazaar",      "South", "Kiran Rao",   "Hyderabad",  "Telangana",   "500001", 1300000, 4,  0.00, START, END),
    ("Sunrise Supermart",  "East",  "Ananya Shah", "Guwahati",   "Assam",       "781001",  750000, 3, +0.05, START, END),
]
SLOW_PAYERS = {"Metro Grocers", "Sapphire Retail", "HomeStyle", "Kisan Stores"}

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

SUPPLIERS = [
    ("Apex Packaging",   "Compostable Pouches", "Packaging",    164, "Central Godown"),
    ("Harvest Foods",    "Rolled Oats Bulk",    "Raw Material", 178, "Central Godown"),
    ("Sunrise Traders",  "Almonds Premium",     "Raw Material", 289, "Central Godown"),
    ("CleanCo Supplies", "Cleaning Supplies",   "Consumables",   92, "Central Godown"),
    ("Orchard Nuts",     "Cashew Raw",          "Raw Material", 265, "Mumbai Branch"),
    ("Golden Hive",      "Honey Bulk",          "Raw Material", 210, "Pune Branch"),
]

GODOWNS = ["Central Godown", "Mumbai Branch", "Pune Branch"]

# ---------------------------------------------------------------- Customer Profile
customer_rows = [{
    "Customer": name, "Territory": terr, "Salesperson": rep,
    "City": city, "State": state, "Pincode": pincode,
    "Credit Limit": limit, "Active Status": "Active" if a_to == END else "Inactive"
} for name, terr, rep, city, state, pincode, limit, per_month, trend, a_from, a_to in CUSTOMERS]

# ---------------------------------------------------------------- Sales Register
sales = []
for name, terr, rep, city, state, pincode, limit, per_month, trend, a_from, a_to in CUSTOMERS:
    d = a_from
    while d <= a_to:
        m = (d.year - START.year) * 12 + d.month - START.month
        weight = max(0.2, 1 + trend * m)
        if random.random() < (per_month * weight) / 30:
            prod, cat, price = random.choice(PRODUCTS)
            qty = random.choice([60, 80, 100, 120, 150, 200, 260, 320, 400])
            gross_amt = round(qty * price * random.uniform(0.95, 1.05), -1)
            disc_pct = random.choice([0, 0, 0, 5, 10])
            disc_amt = round(gross_amt * disc_pct / 100, -1)
            amount = gross_amt - disc_amt
            returns = round(amount * random.uniform(0.03, 0.08), -1) if random.random() < 0.08 else 0
            sales.append({
                "Date": d, "Particulars": name, "Item Name": prod, "Category": cat,
                "Quantity": qty, "Gross Amount": gross_amt, "Discount %": disc_pct,
                "Discount Amount": disc_amt, "Amount": amount, "Returns": returns,
                "Godown": random.choice(GODOWNS), "Territory": terr, "Salesperson": rep,
                "City": city, "State": state, "Pincode": pincode,
                "GSTIN": fake_gstin(name, state)
            })
        d += timedelta(days=1)

# ---------------------------------------------------------------- Purchase Register
purchases = []
po = 800
d = START
while d <= END:
    if random.random() < 0.28:
        sup, item, cat, cost, godown = random.choice(SUPPLIERS)
        po += 1
        qty = random.choice([300, 500, 800, 1200, 1800, 2500])
        short = random.random() < 0.18
        received = int(qty * random.uniform(0.88, 0.97)) if short else qty
        age = (END - d).days
        status = "Received" if age > 20 else random.choice(["In transit", "Received", "Delayed"])
        if status != "Received" and not short:
            received = int(qty * random.choice([0, 0.5, 1]))
        purchases.append({
            "Date": d, "Particulars": sup, "Item Name": item, "Category": cat,
            "PO Number": f"PO-{po}", "Godown": godown, "Quantity": qty, "Received Qty": received,
            "Amount": round(qty * cost * random.uniform(0.97, 1.03), -1),
            "Debit Note": f"DN-{100 + len(purchases)}" if short else "",
            "Status": status,
            "GSTIN": fake_gstin(sup, "Maharashtra")
        })
    d += timedelta(days=1)

# ---------------------------------------------------------------- Receipts & Payments & Compliance
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

# --- Planted Compliance Data ---
# 1. Section 269ST split-cash pattern
for amt in (120000, 95000):
    add_rp(date(2026, 7, 20), "Sapphire Retail", "Receipt", amt, "Cash", date(2026, 7, 20), "Cleared")

# 2. Section 40A(3) cash payments
add_rp(date(2026, 8, 12), "Apex Packaging", "Payment", 6000, "Cash", date(2026, 8, 12), "Cleared")
add_rp(date(2026, 8, 12), "Apex Packaging", "Payment", 7000, "Cash", date(2026, 8, 12), "Cleared")
add_rp(date(2026, 8, 14), "Swift Logistics", "Payment", 30000, "Cash", date(2026, 8, 14), "Cleared")
add_rp(date(2026, 8, 18), "CleanCo Supplies", "Payment", 9000, "Cash", date(2026, 8, 18), "Cleared")

# 3. MSME 43B(h) bills (open payables)
po += 1
purchases.append({"Date": date(2026, 7, 10), "Particulars": "Golden Hive", "Item Name": "Honey Bulk",
                  "PO Number": f"PO-{po}", "Godown": "Pune Branch", "Quantity": 1000, "Received Qty": 1000, "Amount": 210000,
                  "Debit Note": "", "Status": "Received", "GSTIN": fake_gstin("Golden Hive", "Maharashtra")})
add_rp(date(2026, 7, 10), "Golden Hive", "Payment", 210000, "Bank", date(2026, 8, 9), "Pending")

# 4. TDS Payments with Nature
for d_dt in (date(2026, 4, 10), date(2026, 5, 12), date(2026, 6, 15), date(2026, 7, 18)):
    add_rp(d_dt, "BuildRight Works", "Payment", 30000, "Bank", d_dt, "Cleared", "Contractor", 0)
add_rp(date(2026, 6, 5), "Sharma Contractors", "Payment", 15000, "Bank", date(2026, 6, 5), "Cleared", "Contractor", 0)
add_rp(date(2026, 5, 20), "CA Desai & Associates", "Payment", 50000, "Bank", date(2026, 5, 20), "Cleared", "Professional", 2500)
add_rp(date(2026, 7, 20), "CA Desai & Associates", "Payment", 30000, "Bank", date(2026, 7, 20), "Cleared", "Professional", 1500)
add_rp(date(2026, 6, 25), "Kiran Legal", "Payment", 90000, "Bank", date(2026, 6, 25), "Cleared", "Professional", 9000)
for m_idx in (4, 5, 6, 7, 8):
    add_rp(date(2026, m_idx, 5), "Shah Properties", "Payment", 60000, "Bank", date(2026, m_idx, 5), "Cleared", "Rent-Building", 0)
add_rp(date(2026, 7, 15), "Star Agencies", "Payment", 30000, "Bank", date(2026, 7, 15), "Cleared", "Commission", 0)

# Supplier Profile Master
PROFILES = [
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
supplier_profile_rows = [{"Party": n, "GSTIN": fake_gstin(n, "Maharashtra"), "MSME": ms, "Written Agreement": ag,
                          "Transporter": tr, "Payee Type": pt} for n, ms, ag, tr, pt in PROFILES]

# ---------------------------------------------------------------- Reconciled Stock & Movements
stock_summary = [
    ("Organic Oats 1kg",      "FG-101", "Breakfast",    "Central Godown", 260, 500, 10),
    ("Almond Granola 500g",   "FG-118", "Breakfast",    "Mumbai Branch",   292, 300, 7),
    ("Wildflower Honey 500g", "FG-109", "Honey",        "Pune Branch",     150, 250, 12),
    ("Chia Seed Mix 500g",    "FG-145", "Seeds",        "Mumbai Branch",   120, 200, 14),
    ("Peanut Butter 340g",    "FG-152", "Spreads",      "Central Godown", 110, 400, 8),
    ("Muesli 750g",           "FG-160", "Breakfast",    "Pune Branch",     140, 300, 10),
    ("Cashew Pack 250g",      "FG-171", "Dry Fruits",   "Mumbai Branch",   200, 250, 15),
    ("Jaggery Powder 1kg",    "FG-180", "Staples",      "Central Godown",  80, 600, 5),
    ("Compostable Pouches",   "PK-024", "Packaging",    "Central Godown", 150, 400, 10),
    ("Rolled Oats Bulk",      "RM-017", "Raw Material", "Central Godown", 900, 600, 15),
    ("Almonds Premium",       "RM-021", "Raw Material", "Central Godown", 290, 800, 20),
    ("Honey Bulk",            "RM-030", "Raw Material", "Pune Branch",     210, 300, 12),
]

# Calculate exact inward/outward totals from sales and purchases registers
sales_df = pd.DataFrame(sales)
purchases_df = pd.DataFrame(purchases)

stock_rows = []
stock_movement = []
for name, sku, cat, godown, uv, r_lvl, lead in stock_summary:
    sold_qty = int(sales_df[sales_df["Item Name"] == name]["Quantity"].sum())
    purchased_qty = int(purchases_df[purchases_df["Item Name"] == name]["Quantity"].sum())
    
    opening = 500
    inward = purchased_qty
    outward = sold_qty
    closing = opening + inward - outward
    
    stock_rows.append({
        "Item Name": name, "SKU": sku, "Category": cat, "Godown": godown,
        "Opening Qty": opening, "Opening Value": opening * uv,
        "Inward Qty": inward, "Outward Qty": outward,
        "Closing Qty": closing, "Closing Value": max(closing, 0) * uv,
        "Reorder Level": r_lvl, "Lead Time Days": lead, "Age in Days": random.randint(15, 95)
    })
    stock_movement.append({
        "Date": START + timedelta(days=10), "Vch Type": "Receipt Note",
        "Item Name": name, "Godown": godown, "Inward Qty": inward, "Outward Qty": 0, "Batch": "BATCH-2026-A"
    })
    stock_movement.append({
        "Date": END - timedelta(days=10), "Vch Type": "Delivery Note",
        "Item Name": name, "Godown": godown, "Inward Qty": 0, "Outward Qty": outward, "Batch": "BATCH-2026-A"
    })

# ---------------------------------------------------------------- Realistic Sales Targets
# Derived from actual customer monthly spend with a 92% to 108% factor
sales_df["Date"] = pd.to_datetime(sales_df["Date"])
sales_df["Month"] = sales_df["Date"].dt.strftime("%Y-%m")
customer_monthly_actuals = sales_df.groupby(["Particulars", "Month"])["Amount"].sum().reset_index()
targets = []
for _, row in customer_monthly_actuals.iterrows():
    cust = row["Particulars"]
    m = row["Month"]
    actual = row["Amount"]
    target_val = round(actual * random.uniform(0.92, 1.08), -2)
    targets.append({"Month": m, "Customer": cust, "Target Amount": target_val})

# GST & Numbering
SALES_GST = {"Organic Oats 1kg": 5, "Almond Granola 500g": 18, "Wildflower Honey 500g": 5,
             "Chia Seed Mix 500g": 5, "Peanut Butter 340g": 12, "Muesli 750g": 18,
             "Cashew Pack 250g": 12, "Jaggery Powder 1kg": 5}
PURCHASE_GST = {"Compostable Pouches": 18, "Rolled Oats Bulk": 5, "Almonds Premium": 5,
                "Cleaning Supplies": 18, "Cashew Raw": 5, "Honey Bulk": 5}

for row in sales:
    row["GST"] = round(row["Amount"] * SALES_GST[row["Item Name"]] / 100)
for row in purchases:
    row["GST"] = round(row["Amount"] * PURCHASE_GST[row["Item Name"]] / 100)

ym = lambda d: d.strftime("%Y-%m")
gstr2b = [{"Month": ym(p["Date"]), "Supplier GSTIN": p["GSTIN"], "Supplier": p["Particulars"],
           "Invoice No": p.get("Invoice No", "SI/0001"), "Taxable Value": p["Amount"], "Tax": p["GST"]}
          for p in purchases]

returns = []
for m in ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]:
    out_tax = sum(r["GST"] for r in sales if ym(r["Date"]) == m)
    itc = sum(r["GST"] for r in purchases if ym(r["Date"]) == m)
    paid = out_tax - {"2026-07": 30000, "2026-05": 2000}.get(m, 0)
    returns.append({"Month": m, "GSTR-1 Tax": out_tax, "GSTR-3B Tax Paid": paid, "GSTR-3B ITC Claimed": itc})

sync_status = [{
    "Company Name": "ArthPulse Enterprise Ltd",
    "Last Synced At": "2026-08-25 09:30:00",
    "Sync Status": "SUCCESS",
    "Records Processed": len(sales) + len(purchases) + len(rp),
    "Tally Gateway Port": 9000,
    "Mode": "Hybrid (Synthetic / Live Gateway Ready)"
}]

def save(rows, name):
    df = pd.DataFrame(rows).sort_values("Date") if rows and "Date" in rows[0] else pd.DataFrame(rows)
    df.to_excel(os.path.join(OUT, name), index=False)
    print(f"Generated {name}: {len(df)} rows")

save(sales, "sales_register.xlsx")
save(purchases, "purchase_register.xlsx")
save(rp, "receipts_payments.xlsx")
save(stock_rows, "stock_summary.xlsx")
save(stock_movement, "stock_movement.xlsx")
save(customer_rows, "customer_profile.xlsx")
save(supplier_profile_rows, "supplier_profile.xlsx")
save(targets, "sales_targets.xlsx")
save(sync_status, "sync_status.xlsx")
save(gstr2b, "gstr2b_invoices.xlsx")
save(returns, "gst_returns.xlsx")

print("\nFully corrected and reconciled synthetic dataset generated successfully in './synthetic_data/'!")