"""
    python -m app.import_tally --reset \
        --sales synthetic_data/sales_register.xlsx \
        --purchases synthetic_data/purchase_register.xlsx \
        --payments synthetic_data/receipts_payments.xlsx \
        --stock synthetic_data/stock_summary.xlsx

--reset   wipes existing vouchers and stock first (use it when switching
          from seed data to an export, otherwise rows pile up).

Required columns per file are listed in the *_COLUMNS dictionaries. Each
entry is a LIST of header names Tally might use; the first match wins.
Columns marked optional are used when present and defaulted otherwise.
Tally does not export territory / salesperson by default, so for real
exports those stay "Unassigned".

After loading, two things are COMPUTED from the data (not typed in):
  * customer segment  (New / Active / Growing / Declining / Inactive)
  * stock movement    (Fast / Slow / Non-moving, from last 90 days)
"""

import argparse
import sys
from datetime import datetime, timedelta
from collections import defaultdict
 
import pandas as pd
 
from .database import Base, engine, SessionLocal
from .models import (Voucher, InventoryItem, SupplierProfile,
                     Gstr2bInvoice, GstReturn)
from .rules import REFERENCE_DATE
 
Base.metadata.create_all(bind=engine)
 
SKIP_PARTIES = {"", "grand total", "total", "nan"}
 
SALES_COLUMNS = {
    "date": ["Date"],
    "party": ["Particulars", "Party's A/c Name", "Party Name", "Ledger"],
    "amount": ["Amount", "Value", "Gross Total", "Debit"],
    "product": ["Item Name", "Product", "Stock Item"],          # optional
    "quantity": ["Quantity", "Qty"],                            # optional
    "returns": ["Returns", "Credit Note Amount"],               # optional
    "territory": ["Territory", "Cost Centre"],                  # optional
    "salesperson": ["Salesperson", "Sales Person"],             # optional
    "invoice": ["Invoice No", "Voucher No.", "Vch No."],        # optional
    "gstin": ["GSTIN", "GSTIN/UIN"],                            # optional
    "gst": ["GST", "GST Amount", "Tax Amount"],                 # optional
}
PURCHASE_COLUMNS = {
    "date": ["Date"],
    "party": ["Particulars", "Party's A/c Name", "Party Name", "Ledger"],
    "amount": ["Amount", "Value", "Gross Total", "Credit"],
    "product": ["Item Name", "Product", "Stock Item"],          # optional
    "quantity": ["Quantity", "Qty"],                            # optional
    "received": ["Received Qty", "Received Quantity"],          # optional
    "po": ["PO Number", "Order No.", "Order No"],               # optional
    "debit_note": ["Debit Note"],                               # optional
    "status": ["Status"],                                       # optional
    "invoice": ["Invoice No", "Supplier Invoice No", "Voucher No."],   # optional
    "gstin": ["GSTIN", "GSTIN/UIN"],                            # optional
    "gst": ["GST", "GST Amount", "Tax Amount"],                 # optional
}
PAYMENT_COLUMNS = {
    "date": ["Date"],
    "party": ["Particulars", "Party's A/c Name", "Party Name", "Ledger"],
    "voucher_type": ["Vch Type", "Voucher Type"],
    "amount": ["Amount", "Value", "Debit", "Credit"],
    "mode": ["Mode", "Payment Mode"],                           # optional
    "due": ["Due Date"],                                        # optional
    "status": ["Status"],                                       # optional
    "nature": ["Nature", "Nature of Payment"],                  # optional (TDS)
    "tds": ["TDS Deducted", "TDS Amount"],                      # optional (TDS)
}
PROFILE_COLUMNS = {
    "party": ["Party", "Particulars", "Name"],
    "gstin": ["GSTIN"],
    "msme": ["MSME"],
    "agreement": ["Written Agreement", "Agreement"],
    "transporter": ["Transporter"],
    "payee": ["Payee Type"],
}
GSTR2B_COLUMNS = {
    "month": ["Month"],
    "gstin": ["Supplier GSTIN", "GSTIN"],
    "supplier": ["Supplier", "Trade Name"],
    "invoice": ["Invoice No", "Invoice Number"],
    "taxable": ["Taxable Value"],
    "tax": ["Tax", "Tax Amount"],
}
RETURN_COLUMNS = {
    "month": ["Month"],
    "gstr1": ["GSTR-1 Tax"],
    "paid": ["GSTR-3B Tax Paid"],
    "itc": ["GSTR-3B ITC Claimed"],
}
STOCK_COLUMNS = {
    "item": ["Item Name", "Stock Item", "Particulars"],
    "quantity": ["Closing Qty", "Closing Balance", "Quantity"],
    "value": ["Closing Value", "Value"],
    "sku": ["SKU", "Item Code"],                                # optional
    "category": ["Category", "Stock Group", "Under"],           # optional
    "godown": ["Godown", "Location", "Branch"],                 # optional
    "reorder": ["Reorder Level", "Reorder Qty"],                # optional
}
REQUIRED = {
    "sales": ("date", "party", "amount"),
    "purchases": ("date", "party", "amount"),
    "payments": ("date", "party", "amount"),
    "stock": ("item", "quantity", "value"),
    "profiles": ("party",),
    "gstr2b": ("month", "gstin", "invoice", "tax"),
    "returns": ("month", "gstr1", "paid", "itc"),
}
 
 
# ------------------------------------------------------------ helpers
def _read(path):
    return pd.read_excel(path) if path.endswith((".xlsx", ".xls")) else pd.read_csv(path)
 
 
def _find_column(df, candidates):
    for name in candidates:
        for col in df.columns:
            if str(col).strip().lower() == name.strip().lower():
                return col
    return None
 
 
def _map_columns(df, spec, kind, path):
    cols = {k: _find_column(df, v) for k, v in spec.items()}
    missing = [k for k in REQUIRED[kind] if cols[k] is None]
    if missing:
        print(f"  Could not find columns for {missing} in {path}. "
              f"Headers found: {list(df.columns)}")
        return None
    return cols
 
 
def _val(row, col, default=None):
    if col is None:
        return default
    v = row.get(col)
    return default if pd.isna(v) else v
 
 
def _parse_date(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, str):
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None
    return pd.to_datetime(value).date()
 
 
def _clean_amount(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return 0.0
    if isinstance(value, str):
        value = (value.replace(",", "").replace("\u20b9", "")
                 .replace("Dr", "").replace("Cr", "").strip())
        if value in ("", "-"):
            return 0.0
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0.0
 
 
def _text(value):
    """Cell -> clean string, or None when empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None
 
 
def _yes(value):
    return str(value).strip().lower() in ("yes", "y", "true", "1")
 
 
def _party(row, cols):
    p = _val(row, cols["party"])
    if p is None or str(p).strip().lower() in SKIP_PARTIES:
        return None
    return str(p).strip()
 
 
# ------------------------------------------------------------ importers
def import_sales(path, db):
    df = _read(path)
    cols = _map_columns(df, SALES_COLUMNS, "sales", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        party = _party(row, cols)
        if not party:
            continue
        db.add(Voucher(
            voucher_date=_parse_date(_val(row, cols["date"])),
            voucher_type="Sales", party_name=party,
            product=str(_val(row, cols["product"], "Unspecified")).strip(),
            category="Unassigned",
            territory=str(_val(row, cols["territory"], "Unassigned")).strip(),
            salesperson=str(_val(row, cols["salesperson"], "Unassigned")).strip(),
            quantity=_clean_amount(_val(row, cols["quantity"])),
            amount=_clean_amount(_val(row, cols["amount"])),
            returns_amount=_clean_amount(_val(row, cols["returns"])),
            invoice_no=_text(_val(row, cols["invoice"])),
            gstin=_text(_val(row, cols["gstin"])),
            gst_amount=_clean_amount(_val(row, cols["gst"])),
            segment="Active",
        ))
        n += 1
    return n
 
 
def import_purchases(path, db):
    df = _read(path)
    cols = _map_columns(df, PURCHASE_COLUMNS, "purchases", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        party = _party(row, cols)
        if not party:
            continue
        qty = _clean_amount(_val(row, cols["quantity"]))
        dn = _val(row, cols["debit_note"])
        db.add(Voucher(
            voucher_date=_parse_date(_val(row, cols["date"])),
            voucher_type="Purchase", party_name=party,
            product=str(_val(row, cols["product"], "Unspecified")).strip(),
            category="Unassigned",
            po_number=str(_val(row, cols["po"], f"PO-AUTO-{n + 1}")).strip(),
            quantity=qty,
            received_quantity=_clean_amount(_val(row, cols["received"], qty)),
            amount=_clean_amount(_val(row, cols["amount"])),
            debit_note=str(dn).strip() if dn else None,
            invoice_no=_text(_val(row, cols["invoice"])),
            gstin=_text(_val(row, cols["gstin"])),
            gst_amount=_clean_amount(_val(row, cols["gst"])),
            status=str(_val(row, cols["status"], "Received")).strip(),
        ))
        n += 1
    return n
 
 
def _open_item_status(due):
    """Status for items still unpaid, judged against REFERENCE_DATE."""
    if due is None:
        return "Pending"
    if due < REFERENCE_DATE:
        return "Overdue"
    if due <= REFERENCE_DATE + timedelta(days=7):
        return "Due this week"
    return "Due later"
 
 
def import_payments(path, db):
    df = _read(path)
    cols = _map_columns(df, PAYMENT_COLUMNS, "payments", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        party = _party(row, cols)
        if not party:
            continue
        vt = str(_val(row, cols["voucher_type"], "")).strip().lower()
        is_receipt = "receipt" in vt or "cash" in vt
        day = _parse_date(_val(row, cols["date"]))
        due = _parse_date(_val(row, cols["due"])) or day
        raw_status = str(_val(row, cols["status"], "Pending")).strip()
        status = "Cleared" if raw_status.lower() == "cleared" else _open_item_status(due)
        db.add(Voucher(
            voucher_date=day,
            voucher_type="Receipt" if is_receipt else "Payment",
            party_name=party,
            payment_type="Receivable" if is_receipt else "Payable",
            amount=_clean_amount(_val(row, cols["amount"])),
            payment_mode=str(_val(row, cols["mode"], "Bank")).strip(),
            nature=_text(_val(row, cols["nature"])),
            tds_deducted=_clean_amount(_val(row, cols["tds"])),
            due_date=due, status=status,
        ))
        n += 1
    return n
 
 
def import_stock(path, db):
    df = _read(path)
    cols = _map_columns(df, STOCK_COLUMNS, "stock", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        item = _val(row, cols["item"])
        if item is None or str(item).strip().lower() in SKIP_PARTIES:
            continue
        qty = _val(row, cols["quantity"], 0)
        if isinstance(qty, str):
            qty = float(qty.replace(",", "") or 0)   # keep the minus sign
        db.add(InventoryItem(
            sku=str(_val(row, cols["sku"], f"SKU-{n + 1:04d}")).strip(),
            product=str(item).strip(),
            category=str(_val(row, cols["category"], "Unassigned")).strip(),
            branch=str(_val(row, cols["godown"], "Main")).strip(),
            quantity=float(qty),
            value=_clean_amount(_val(row, cols["value"])),
            movement="Unclassified",
            reorder_level=float(_val(row, cols["reorder"], 20)),
        ))
        n += 1
    return n
 
 
def import_profiles(path, db):
    df = _read(path)
    cols = _map_columns(df, PROFILE_COLUMNS, "profiles", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        party = _party(row, cols)
        if not party:
            continue
        db.add(SupplierProfile(
            party_name=party, gstin=_text(_val(row, cols["gstin"])),
            is_msme=_yes(_val(row, cols["msme"], "No")),
            has_agreement=_yes(_val(row, cols["agreement"], "No")),
            is_transporter=_yes(_val(row, cols["transporter"], "No")),
            payee_type=str(_val(row, cols["payee"], "Company")).strip(),
        ))
        n += 1
    return n
 
 
def import_gstr2b(path, db):
    df = _read(path)
    cols = _map_columns(df, GSTR2B_COLUMNS, "gstr2b", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        db.add(Gstr2bInvoice(
            month=str(_val(row, cols["month"])).strip(),
            supplier_gstin=str(_val(row, cols["gstin"])).strip(),
            supplier_name=_text(_val(row, cols["supplier"])),
            invoice_no=str(_val(row, cols["invoice"])).strip(),
            taxable_value=_clean_amount(_val(row, cols["taxable"])),
            tax_amount=_clean_amount(_val(row, cols["tax"])),
        ))
        n += 1
    return n
 
 
def import_gst_returns(path, db):
    df = _read(path)
    cols = _map_columns(df, RETURN_COLUMNS, "returns", path)
    if not cols:
        return 0
    n = 0
    for _, row in df.iterrows():
        db.add(GstReturn(
            month=str(_val(row, cols["month"])).strip(),
            gstr1_tax=_clean_amount(_val(row, cols["gstr1"])),
            gstr3b_tax_paid=_clean_amount(_val(row, cols["paid"])),
            gstr3b_itc_claimed=_clean_amount(_val(row, cols["itc"])),
        ))
        n += 1
    return n
 
 
# ------------------------------------------------- computed enrichments
def compute_segments(db):
    """New / Inactive / Growing / Declining / Active, from sales history."""
    by_party = defaultdict(list)
    for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all():
        by_party[v.party_name].append(v)
 
    for party, rows in by_party.items():
        first = min(v.voucher_date for v in rows)
        last = max(v.voucher_date for v in rows)
        recent = sum(v.amount for v in rows
                     if REFERENCE_DATE - timedelta(days=90) < v.voucher_date <= REFERENCE_DATE)
        prev = sum(v.amount for v in rows
                   if REFERENCE_DATE - timedelta(days=180) < v.voucher_date
                   <= REFERENCE_DATE - timedelta(days=90))
        if first >= REFERENCE_DATE - timedelta(days=60):
            seg = "New"
        elif last < REFERENCE_DATE - timedelta(days=60):
            seg = "Inactive"
        elif prev > 0 and recent / prev > 1.15:
            seg = "Growing"
        elif prev > 0 and recent / prev < 0.85:
            seg = "Declining"
        else:
            seg = "Active"
        for v in rows:
            v.segment = seg
 
 
def compute_movement(db):
    """
    Fast / Slow / Non-moving, from units moved in the last 90 days.
    Relative, not absolute: finished goods (items that appear in sales)
    and inputs (raw material, packaging) are each split at their own
    median, and anything that barely moved relative to stock on hand is
    Non-moving.
    """
    since = REFERENCE_DATE - timedelta(days=90)
    sold, bought = defaultdict(float), defaultdict(float)
    for v in db.query(Voucher).filter(Voucher.voucher_type.in_(["Sales", "Purchase"])).all():
        if v.voucher_date and since < v.voucher_date <= REFERENCE_DATE and v.product:
            (sold if v.voucher_type == "Sales" else bought)[v.product] += v.quantity or 0
 
    items = db.query(InventoryItem).all()
    for group_is_finished in (True, False):
        group = [it for it in items if (it.product in sold) == group_is_finished]
        moved = {it.id: (sold if group_is_finished else bought).get(it.product, 0)
                 for it in group}
        vals = sorted(moved.values())
        median = vals[len(vals) // 2] if vals else 0
        for it in group:
            m = moved[it.id]
            if m == 0 or m < max(it.quantity, 1) * 0.5:
                it.movement = "Non-moving"
            elif m >= median:
                it.movement = "Fast-moving"
            else:
                it.movement = "Slow-moving"
 
 
# ---------------------------------------------------------------- main
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sales")
    ap.add_argument("--purchases")
    ap.add_argument("--payments")
    ap.add_argument("--stock")
    ap.add_argument("--suppliers", help="supplier_profile.xlsx (MSME / transporter / payee type)")
    ap.add_argument("--gstr2b", help="gstr2b_invoices.xlsx")
    ap.add_argument("--gst-returns", dest="gst_returns", help="gst_returns.xlsx")
    ap.add_argument("--reset", action="store_true",
                    help="rebuild the data tables (wipes imported data, keeps user accounts) before importing")
    a = ap.parse_args()
 
    if not any([a.sales, a.purchases, a.payments, a.stock, a.suppliers, a.gstr2b, a.gst_returns]):
        print("Provide at least one input file (see --help)")
        sys.exit(1)
 
    if a.reset:
        # drop + create (not just DELETE) so new columns / tables are picked up.
        # The users table is deliberately left alone: accounts are entered by hand.
        data_tables = [t for t in Base.metadata.sorted_tables if t.name != "users"]
        Base.metadata.drop_all(bind=engine, tables=data_tables)
        Base.metadata.create_all(bind=engine)
        print("Rebuilt the data tables (user accounts were kept).")
    db = SessionLocal()
 
    total = 0
    for flag, fn, label in [(a.sales, import_sales, "sales"),
                            (a.purchases, import_purchases, "purchase"),
                            (a.payments, import_payments, "receipt/payment"),
                            (a.stock, import_stock, "stock"),
                            (a.suppliers, import_profiles, "supplier profile"),
                            (a.gstr2b, import_gstr2b, "GSTR-2B invoice"),
                            (a.gst_returns, import_gst_returns, "GST return")]:
        if flag:
            n = fn(flag, db)
            print(f"Imported {n} {label} rows from {flag}")
            total += n
    db.flush()
    compute_segments(db)
    compute_movement(db)
    db.commit()
    db.close()
    print(f"Done. {total} records imported.")
 