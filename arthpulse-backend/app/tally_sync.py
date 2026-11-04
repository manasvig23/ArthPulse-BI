"""Load TallyPrime data or reload the synthetic presentation dataset."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import math

from sqlalchemy.orm import Session

from . import tally_xml
from .database import Base, engine
from .import_tally import compute_movement, compute_segments, load_synthetic_bundle
from .models import InventoryItem, SyncEvent, Voucher
from .rules import REFERENCE_DATE

BACKEND_DIR = Path(__file__).resolve().parent.parent
SYNTHETIC_DIR = BACKEND_DIR / "synthetic_data"

# These tables must survive a normal data replacement.
KEEP_TABLES = {"users", "sync_events"}

# GST reconciliation data is maintained separately from the Tally voucher import.
TAX_TABLES = {"gstr2b_invoices", "gst_returns", "supplier_profiles"}


def _wipe_operational(db: Session, keep_tax: bool = False) -> None:
    """Delete replaceable operational rows inside the current transaction.

    Do not commit here. The caller must commit only after the replacement
    data has been inserted successfully.
    """
    tables = [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in KEEP_TABLES
        and not (keep_tax and table.name in TAX_TABLES)
    ]

    for table in tables:
        db.execute(table.delete())


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
        "stale": bool(
            row.finished_at
            and datetime.utcnow() - row.finished_at > timedelta(hours=24)
        ),
    }


def _log(db: Session, **kwargs) -> SyncEvent:
    event = SyncEvent(**kwargs)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def reload_synthetic(db: Session) -> dict:
    """Replace operational data with the full synthetic presentation dataset."""
    started = datetime.utcnow()
    event = _log(
        db,
        started_at=started,
        source="synthetic",
        status="running",
        message="Loading presentation synthetic registers",
        company="ArthPulse synthetic",
    )

    try:
        # Preserve both login accounts and the history of sync attempts.
        _wipe_operational(db, keep_tax=False)

        counts = load_synthetic_bundle(db, SYNTHETIC_DIR)

        sales_total = sum(
            voucher.amount
            for voucher in db.query(Voucher)
            .filter(Voucher.voucher_type == "Sales")
            .all()
        )

        event.status = "success"
        event.finished_at = datetime.utcnow()
        event.message = "Synthetic Tally-shaped registers loaded for the presentation."
        event.sales_count = counts.get("sales", 0)
        event.purchase_count = counts.get("purchases", 0)
        event.stock_count = counts.get("stock", 0)
        event.dashboard_sales_total = sales_total
        event.tally_sales_total = sales_total

        db.commit()
        return last_sync(db)

    except Exception as exc:
        db.rollback()
        db.refresh(event)
        event.status = "error"
        event.finished_at = datetime.utcnow()
        event.message = str(exc)[:1000]
        db.commit()
        raise


def _nature_from_narration(text: str) -> str | None:
    text = (text or "").lower()

    if "contractor" in text:
        return "Contractor"
    if "professional" in text:
        return "Professional"
    if "rent" in text:
        return "Rent-Building"
    if "commission" in text:
        return "Commission"

    return None


def _validated_vouchers(vouchers: list[dict]) -> list[dict]:
    """Keep only usable supported vouchers; reject an empty import."""
    valid = []
    supported_types = {"Sales", "Purchase", "Receipt", "Payment"}

    for row in vouchers:
        if not isinstance(row, dict):
            continue

        day = row.get("date")
        kind = row.get("voucher_type")
        party = str(row.get("party") or "").strip()

        try:
            amount = float(row.get("amount", 0))
        except (TypeError, ValueError, OverflowError):
            continue

        if (
            day is None
            or kind not in supported_types
            or not party
            or not math.isfinite(amount)
            or amount <= 0
        ):
            continue

        valid.append({**row, "party": party, "amount": amount})

    if not valid:
        raise RuntimeError(
            "Tally returned no usable vouchers. Existing dashboard data was "
            "preserved. Check the selected company, date range, and voucher export."
        )

    return valid


def apply_tally_rows(
    db: Session,
    vouchers: list[dict],
    stock: list[dict],
    company: str,
) -> dict:
    """Replace operational voucher/stock data in the current transaction.

    This function intentionally does not commit. The caller commits the
    imported rows and successful sync event together.
    """
    vouchers = _validated_vouchers(vouchers)

    clean_stock = []
    for row in stock:
        if not isinstance(row, dict):
            continue

        product = str(row.get("product") or "").strip()
        if not product:
            continue

        try:
            quantity = float(row.get("quantity") or 0)
            value = float(row.get("value") or 0)
        except (TypeError, ValueError, OverflowError):
            continue

        if not math.isfinite(quantity) or not math.isfinite(value):
            continue

        clean_stock.append({
            **row,
            "product": product,
            "quantity": quantity,
            "value": value,
        })

    # Validation is complete before the existing operational rows are touched.
    _wipe_operational(db, keep_tax=True)

    sales_count = 0
    purchase_count = 0
    payment_count = 0
    tally_sales_total = 0.0

    for row in vouchers:
        kind = row["voucher_type"]
        day = row["date"]
        amount = row["amount"]
        narration = row.get("narration") or ""

        pending = "Pending"
        due_date = day + timedelta(days=30)

        if due_date < REFERENCE_DATE:
            pending = "Overdue"
        elif due_date <= REFERENCE_DATE + timedelta(days=7):
            pending = "Due this week"

        cash = (
            row.get("mode") == "Cash"
            or "cash" in narration.lower()
        )

        voucher = Voucher(
            voucher_date=day,
            voucher_type=kind,
            party_name=row["party"],
            product=row.get("product") or "Unspecified",
            amount=amount,
            quantity=row.get("quantity") or 0,
            invoice_no=row.get("invoice"),
            gstin=row.get("gstin") or None,
            tally_guid=row.get("guid"),
            payment_mode="Cash" if cash else "Bank",
            nature=_nature_from_narration(narration),
        )

        if kind == "Sales":
            sales_count += 1
            tally_sales_total += amount
            voucher.segment = "Active"

        elif kind == "Purchase":
            purchase_count += 1
            voucher.received_quantity = voucher.quantity
            voucher.status = "Received"
            voucher.po_number = row.get("invoice") or f"PO-{purchase_count}"

        elif kind == "Receipt":
            payment_count += 1
            voucher.payment_type = "Receivable"
            voucher.due_date = due_date
            voucher.status = "Cleared" if cash else pending

        elif kind == "Payment":
            payment_count += 1
            voucher.payment_type = "Payable"
            voucher.due_date = due_date

            # Preserve the intentionally open MSME bill used by the demo.
            if "pending" in narration.lower() or "msme" in narration.lower():
                voucher.status = pending
            else:
                voucher.status = "Cleared" if cash else pending

        db.add(voucher)

    for index, row in enumerate(clean_stock, start=1):
        db.add(
            InventoryItem(
                sku=f"TLY-{index:04d}",
                product=row["product"],
                category=row.get("category") or "Unassigned",
                branch="Main",
                quantity=row["quantity"],
                value=row["value"],
                movement="Unclassified",
                reorder_level=20,
            )
        )

    # Make inserted rows visible to the derived calculations.
    db.flush()
    compute_segments(db)
    compute_movement(db)
    db.flush()

    dashboard_sales_total = sum(
        voucher.amount
        for voucher in db.query(Voucher)
        .filter(Voucher.voucher_type == "Sales")
        .all()
    )

    return {
        "sales": sales_count,
        "purchases": purchase_count,
        "payments": payment_count,
        "stock": len(clean_stock),
        "tally_sales_total": tally_sales_total,
        "dashboard_sales_total": dashboard_sales_total,
        "company": company,
    }


def sync_from_tally(db: Session, company: str | None = None) -> dict:
    """Fetch Tally data and replace operational data only after validation."""
    started = datetime.utcnow()

    ok, ping_message = tally_xml.ping()
    if not ok:
        message = (
            f"Could not reach TallyPrime at {tally_xml.TALLY_URL}. "
            "Open the intended company and enable XML requests on port 9000. "
            f"Detail: {ping_message[:240]}"
        )
        _log(
            db,
            started_at=started,
            finished_at=datetime.utcnow(),
            source="tally",
            status="error",
            company=company or tally_xml.TALLY_COMPANY or None,
            message=message,
        )
        raise RuntimeError(
            f"TallyPrime is not reachable at {tally_xml.TALLY_URL}. "
            "Start Tally, open the demo company, and enable XML/ODBC on port 9000."
        )

    companies = []
    try:
        companies = tally_xml.list_companies()
    except Exception:
        # Some Tally setups do not expose the custom company-list report.
        # Continue using the configured/current company as before.
        companies = []

    chosen_company = (
        company
        or tally_xml.TALLY_COMPANY
        or (companies[0] if companies else "")
    )

    event = _log(
        db,
        started_at=started,
        source="tally",
        status="running",
        company=chosen_company or None,
        message="Exporting vouchers from TallyPrime",
    )

    try:
        raw_vouchers = tally_xml.export_vouchers(chosen_company or None)
        raw_stock = tally_xml.export_stock(chosen_company or None)

        vouchers = tally_xml.parse_vouchers(raw_vouchers)
        stock = tally_xml.parse_stock(raw_stock)

        # Fail before replacing anything if the voucher response is unusable.
        vouchers = _validated_vouchers(vouchers)

        counts = apply_tally_rows(
            db,
            vouchers,
            stock,
            chosen_company,
        )

        event.status = "success"
        event.finished_at = datetime.utcnow()
        event.message = (
            f"Fetched {counts['sales']} sales, "
            f"{counts['purchases']} purchases and "
            f"{counts['stock']} stock items from TallyPrime"
            + (
                f" company '{chosen_company}'."
                if chosen_company
                else "."
            )
        )
        event.sales_count = counts["sales"]
        event.purchase_count = counts["purchases"]
        event.stock_count = counts["stock"]
        event.tally_sales_total = counts["tally_sales_total"]
        event.dashboard_sales_total = counts["dashboard_sales_total"]

        # Commit the replacement and its success record together.
        db.commit()

        info = last_sync(db) or {}
        info["companies"] = companies
        return info

    except Exception as exc:
        # Roll back operational deletes/inserts so previous dashboard data
        # remains intact if any part of the replacement fails.
        db.rollback()
        db.refresh(event)

        event.status = "error"
        event.finished_at = datetime.utcnow()
        event.message = str(exc)[:1000]
        db.commit()
        raise


def push_educational_to_tally(company: str | None = None) -> dict:
    """Insert the Educational-date subset into the open Tally company."""
    ok, message = tally_xml.ping()
    if not ok:
        raise RuntimeError(
            f"TallyPrime is not reachable at {tally_xml.TALLY_URL}: "
            f"{message[:240]}"
        )

    xml = tally_xml.build_educational_import(
        company or tally_xml.TALLY_COMPANY
    )
    response = tally_xml.post_xml(xml)

    path = SYNTHETIC_DIR / "tally_educational_import.xml"
    tally_xml.write_educational_file(str(path))

    response_lower = response.lower()
    looks_ok = (
        "created" in response_lower
        or "success" in response_lower
        or "<status>1</status>" in response_lower
    ) and "error" not in response_lower

    return {
        "ok": looks_ok,
        "message": (
            "Educational-date data was sent to TallyPrime. Review the Tally "
            "response before syncing it back into ArthPulse."
            if looks_ok
            else "TallyPrime responded, but the import response does not confirm "
                 "success. Review the response excerpt before syncing."
        ),
        "file": str(path),
        "tally_response_excerpt": response[:800],
        "looks_ok": looks_ok,
    }


def tally_status() -> dict:
    """Return gateway reachability, configured company, and recent sync status."""
    ok, message = tally_xml.ping()
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
        "detail": None if ok else message[:400],
        "educational_note": (
            "TallyPrime Educational accepts voucher dates on the 1st, 2nd "
            "and 31st only."
        ),
    }
