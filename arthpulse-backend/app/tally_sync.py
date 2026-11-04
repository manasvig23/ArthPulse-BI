"""Load TallyPrime Educational company data, or reload the synthetic presentation set."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from . import tally_xml
from .database import Base, engine
from .import_tally import compute_movement, compute_segments, load_synthetic_bundle
from .models import (
    InventoryItem, PartyMaster, SalesTarget, StockMovement, SyncEvent, Voucher,
)
from .rules import REFERENCE_DATE

BACKEND_DIR = Path(__file__).resolve().parent.parent
SYNTHETIC_DIR = BACKEND_DIR / "synthetic_data"
KEEP_TABLES = {"users"}


def _wipe_operational(db: Session, keep_tax=False):
    tables = [t for t in reversed(Base.metadata.sorted_tables)
              if t.name not in KEEP_TABLES and not (keep_tax and t.name in {"gstr2b_invoices", "gst_returns", "supplier_profiles"})]
    for t in tables:
        db.execute(t.delete())
    db.commit()


def last_sync(db: Session) -> dict | None:
    row = db.query(SyncEvent).order_by(SyncEvent.id.desc()).first()
    if not row:
        return None
    return {
        "id": row.id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "source": row.source,
        "company": row.company,
        "status": row.status,
        "message": row.message,
        "sales_count": row.sales_count,
        "purchase_count": row.purchase_count,
        "stock_count": row.stock_count,
        "tally_sales_total": row.tally_sales_total,
        "dashboard_sales_total": row.dashboard_sales_total,
        "stale": bool(row.finished_at and datetime.utcnow() - row.finished_at > timedelta(hours=24)),
    }


def _log(db, **kwargs) -> SyncEvent:
    ev = SyncEvent(**kwargs)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def reload_synthetic(db: Session) -> dict:
    started = datetime.utcnow()
    ev = _log(db, started_at=started, source="synthetic", status="running",
              message="Loading presentation synthetic registers", company="ArthPulse synthetic")
    try:
        data_tables = [t for t in Base.metadata.sorted_tables if t.name != "users"]
        Base.metadata.drop_all(bind=engine, tables=data_tables)
        Base.metadata.create_all(bind=engine)
        counts = load_synthetic_bundle(db, SYNTHETIC_DIR)
        sales_total = sum(v.amount for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all())
        ev.status = "success"
        ev.finished_at = datetime.utcnow()
        ev.message = "Synthetic Tally-shaped registers loaded for the presentation."
        ev.sales_count = counts.get("sales", 0)
        ev.purchase_count = counts.get("purchases", 0)
        ev.stock_count = counts.get("stock", 0)
        ev.dashboard_sales_total = sales_total
        ev.tally_sales_total = sales_total
        db.commit()
        return last_sync(db)
    except Exception as e:
        ev.status = "error"
        ev.finished_at = datetime.utcnow()
        ev.message = str(e)
        db.commit()
        raise


def _nature_from_narration(text: str) -> str | None:
    t = (text or "").lower()
    if "contractor" in t:
        return "Contractor"
    if "professional" in t:
        return "Professional"
    if "rent" in t:
        return "Rent-Building"
    if "commission" in t:
        return "Commission"
    return None


def apply_tally_rows(db: Session, vouchers: list[dict], stock: list[dict], company: str) -> dict:
    """Replace operational vouchers/stock with Tally export; keep GST/supplier tables."""
    _wipe_operational(db, keep_tax=True)
    sales_n = purch_n = pay_n = 0
    tally_sales = 0.0
    for row in vouchers:
        if not row.get("date") or not row.get("amount"):
            continue
        kind = row["voucher_type"]
        pending = "Pending"
        due = row["date"] + timedelta(days=30)
        if due < REFERENCE_DATE:
            pending = "Overdue"
        elif due <= REFERENCE_DATE + timedelta(days=7):
            pending = "Due this week"
        cash = row.get("mode") == "Cash" or "cash" in (row.get("narration") or "").lower()
        v = Voucher(
            voucher_date=row["date"],
            voucher_type=kind,
            party_name=row["party"],
            product=row.get("product") or "Unspecified",
            amount=row["amount"],
            quantity=row.get("quantity") or 0,
            invoice_no=row.get("invoice"),
            gstin=row.get("gstin") or None,
            tally_guid=row.get("guid"),
            payment_mode="Cash" if cash else "Bank",
            nature=_nature_from_narration(row.get("narration")),
        )
        if kind == "Sales":
            sales_n += 1
            tally_sales += row["amount"]
            v.segment = "Active"
        elif kind == "Purchase":
            purch_n += 1
            v.received_quantity = v.quantity
            v.status = "Received"
            v.po_number = row.get("invoice") or f"PO-{purch_n}"
        elif kind == "Receipt":
            pay_n += 1
            v.payment_type = "Receivable"
            v.due_date = due
            v.status = "Cleared" if cash else pending
        elif kind == "Payment":
            pay_n += 1
            v.payment_type = "Payable"
            v.due_date = due
            # MSME planted bill stays open so 43B(h) still fires
            if "pending" in (row.get("narration") or "").lower() or "msme" in (row.get("narration") or "").lower():
                v.status = pending
            else:
                v.status = "Cleared" if cash else pending
        db.add(v)

    stock_n = 0
    for i, row in enumerate(stock, 1):
        if not row.get("product"):
            continue
        db.add(InventoryItem(
            sku=f"TLY-{i:04d}",
            product=row["product"],
            category=row.get("category") or "Unassigned",
            branch="Main",
            quantity=row.get("quantity") or 0,
            value=row.get("value") or 0,
            movement="Unclassified",
            reorder_level=20,
        ))
        stock_n += 1
    db.flush()
    compute_segments(db)
    compute_movement(db)
    db.commit()
    dash_sales = sum(v.amount for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all())
    return {
        "sales": sales_n, "purchases": purch_n, "payments": pay_n, "stock": stock_n,
        "tally_sales_total": tally_sales, "dashboard_sales_total": dash_sales,
        "company": company,
    }


def sync_from_tally(db: Session, company: str | None = None) -> dict:
    started = datetime.utcnow()
    ok, ping_msg = tally_xml.ping()
    if not ok:
        _log(db, started_at=started, finished_at=datetime.utcnow(), source="tally",
             status="error", company=company or tally_xml.TALLY_COMPANY or None,
             message="Could not reach TallyPrime at "
                     f"{tally_xml.TALLY_URL}. Open the demo company, enable XML "
                     f"requests (port 9000), then try again. Detail: {ping_msg[:240]}")
        raise RuntimeError(
            f"TallyPrime is not reachable at {tally_xml.TALLY_URL}. "
            "Start Tally, open the demo company, and enable XML/ODBC on port 9000."
        )

    companies = []
    try:
        companies = tally_xml.list_companies()
    except Exception:
        companies = []
    chosen = company or tally_xml.TALLY_COMPANY or (companies[0] if companies else "")
    ev = _log(db, started_at=started, source="tally", status="running",
              company=chosen or None, message="Exporting vouchers from TallyPrime")

    try:
        raw_v = tally_xml.export_vouchers(chosen or None)
        raw_s = tally_xml.export_stock(chosen or None)
        vouchers = tally_xml.parse_vouchers(raw_v)
        stock = tally_xml.parse_stock(raw_s)
        if not vouchers:
            raise RuntimeError(
                "Tally responded but no vouchers were read. Confirm the Educational "
                "demo company is open and contains the ArthPulse import "
                "(dates 1, 2 and 31 only)."
            )
        counts = apply_tally_rows(db, vouchers, stock, chosen)
        ev.status = "success"
        ev.finished_at = datetime.utcnow()
        ev.message = (
            f"Fetched {counts['sales']} sales, {counts['purchases']} purchases and "
            f"{counts['stock']} stock items from TallyPrime"
            + (f" company '{chosen}'." if chosen else ".")
        )
        ev.sales_count = counts["sales"]
        ev.purchase_count = counts["purchases"]
        ev.stock_count = counts["stock"]
        ev.tally_sales_total = counts["tally_sales_total"]
        ev.dashboard_sales_total = counts["dashboard_sales_total"]
        db.commit()
        info = last_sync(db)
        info["companies"] = companies
        return info
    except Exception as e:
        ev.status = "error"
        ev.finished_at = datetime.utcnow()
        ev.message = str(e)
        db.commit()
        raise


def push_educational_to_tally(company: str | None = None) -> dict:
    """Insert the Educational-date subset into the open Tally company."""
    ok, msg = tally_xml.ping()
    if not ok:
        raise RuntimeError(f"TallyPrime is not reachable at {tally_xml.TALLY_URL}: {msg[:240]}")
    xml = tally_xml.build_educational_import(company or tally_xml.TALLY_COMPANY)
    response = tally_xml.post_xml(xml)
    path = SYNTHETIC_DIR / "tally_educational_import.xml"
    tally_xml.write_educational_file(str(path))
    created = "created" in response.lower() or "success" in response.lower() or "<status>1</status>" in response.lower()
    return {
        "ok": True,
        "message": "Educational vouchers (dates 1, 2 and 31) sent to TallyPrime. "
                   "If ledgers already existed, duplicates may have been ignored.",
        "file": str(path),
        "tally_response_excerpt": response[:800],
        "looks_ok": created or "error" not in response.lower(),
    }


def tally_status() -> dict:
    ok, msg = tally_xml.ping()
    companies = []
    if ok:
        try:
            companies = tally_xml.list_companies()
        except Exception:
            companies = []
    return {
        "reachable": ok,
        "url": tally_xml.TALLY_URL,
        "configured_company": tally_xml.TALLY_COMPANY or None,
        "companies": companies,
        "detail": None if ok else msg[:400],
        "educational_note": "TallyPrime Educational accepts voucher dates on the 1st, 2nd and 31st only.",
    }
