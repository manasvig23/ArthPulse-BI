from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.aichat import ai_service
from . import (
    auth, compliance, export_files, forecasts, quality,
    recommendations, rules, schema, summaries, tally_sync,
)
from .database import Base, SessionLocal, engine, get_db
from .models import InventoryItem, Recommendation, User, Voucher


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("DEBUG: Starting database metadata creation...")
    Base.metadata.create_all(bind=engine)
    print("DEBUG: Ensuring schema...")
    schema.ensure_schema()
    print("DEBUG: Opening database session...")
    db = SessionLocal()
    try:
        removed = auth.purge_legacy_demo_users(db)
        if removed:
            print(f"Removed {removed} leftover demo account(s).")
        if auth.ensure_default_admin(db):
            shown = (
                "the password from ARTHPULSE_ADMIN_PASSWORD"
                if auth.DEFAULT_ADMIN_PASSWORD != auth.BUILTIN_ADMIN_PASSWORD
                else f"password '{auth.BUILTIN_ADMIN_PASSWORD}' (change it after signing in)"
            )
            print(
                f"Created the default administrator: username "
                f"'{auth.DEFAULT_ADMIN_USERNAME}', {shown}."
            )
    finally:
        db.close()
    yield


app = FastAPI(title="ArthPulse API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ArthPulse API is running"}


# --------------------------------------------------------------- helpers

def _build_summary(
    db,
    period,
    start_date,
    end_date,
    financial_year,
    product,
    customer,
    supplier,
    location,
    comparison,
):
    try:
        return summaries.build_summary(
            db=db,
            period=period,
            start_date=start_date,
            end_date=end_date,
            financial_year=financial_year,
            product=product,
            customer=customer,
            supplier=supplier,
            location=location,
            comparison=comparison,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _date_window(
    db,
    period,
    start_date,
    end_date,
    financial_year,
    comparison,
):
    try:
        return summaries.get_window(
            db,
            period,
            start_date,
            end_date,
            financial_year,
            comparison,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _filter_rows(rows, product=None, party=None, location=None):
    result = []
    for row in rows:
        # Sales/purchase table columns:
        # party, product, territory, salesperson, ..., godown is not
        # included in the display row, so location filtering is done
        # against the underlying vouchers in the endpoint instead.
        if product and len(row) > 1 and row[1] != product:
            continue
        if party and row and row[0] != party:
            continue
        result.append(row)
    return result


def _filtered_vouchers(
    db,
    voucher_type,
    start,
    end,
    product=None,
    party=None,
    location=None,
):
    query = db.query(Voucher).filter(
        Voucher.voucher_type == voucher_type
    )
    if start:
        query = query.filter(Voucher.voucher_date >= start)
    if end:
        query = query.filter(Voucher.voucher_date <= end)
    if product:
        query = query.filter(Voucher.product == product)
    if party:
        query = query.filter(Voucher.party_name == party)
    if location:
        query = query.filter(Voucher.godown == location)
    return query.all()


def _sales_rows(vouchers):
    return [
        [
            v.party_name, v.product, v.territory, v.salesperson,
            v.amount, v.returns_amount, v.segment, v.id,
            v.invoice_no, v.city, v.state, v.pincode, v.discount_pct,
        ]
        for v in vouchers
    ]


def _purchase_rows(vouchers):
    return [
        [
            v.po_number, v.party_name, v.product, v.quantity,
            v.received_quantity,
            (v.received_quantity or 0) - (v.quantity or 0),
            v.debit_note or "—", v.status, v.id, v.invoice_no,
        ]
        for v in vouchers
    ]


def _export_filters(
    db,
    period,
    start_date,
    end_date,
    financial_year,
    product,
    customer,
    supplier,
    location,
    comparison,
):
    return _build_summary(
        db, period, start_date, end_date, financial_year,
        product, customer, supplier, location, comparison,
    )


# ------------------------------------------------------------------ auth

class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(User.username == body.username.strip().lower())
        .first()
    )
    if (
        user is None
        or not user.is_active
        or not auth.verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Wrong username or password")

    return {
        "token": auth.create_token(user.username, user.role),
        "user": auth.public_user(user),
    }


@app.get("/api/auth/me")
def me(user: User = Depends(auth.get_current_user)):
    return auth.public_user(user)


@app.get("/api/auth/roles")
def roles_overview(
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    return {
        "areas": [{"id": k, "label": v} for k, v in auth.AREAS.items()],
        "roles": [
            {"id": k, "label": v["label"], "areas": v["areas"]}
            for k, v in auth.ROLES.items()
        ],
        "users": [
            {
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "role_label": auth.ROLES.get(u.role, {}).get("label", u.role),
                "active": u.is_active,
            }
            for u in db.query(User).order_by(User.id).all()
        ],
    }


# ------------------------------------------------------------- tally sync

class SyncBody(BaseModel):
    company: str | None = None


@app.get("/api/sync/status")
def sync_status(
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    info = tally_sync.tally_status()
    info["last"] = tally_sync.last_sync(db)
    info["can_sync"] = "users" in auth.areas_for(user)
    return info


@app.post("/api/sync/tally")
def sync_from_tally(
    body: SyncBody | None = None,
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    try:
        return tally_sync.sync_from_tally(db, body.company if body else None)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/sync/synthetic")
def sync_synthetic(
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    try:
        return tally_sync.reload_synthetic(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/sync/push-educational")
def push_educational(
    body: SyncBody | None = None,
    _user: User = Depends(auth.require_area("users")),
):
    try:
        return tally_sync.push_educational_to_tally(
            body.company if body else None
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ------------------------------------------------------------- dashboards

@app.get("/api/sales")
def sales(
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    customer: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
    _user: User = Depends(auth.require_area("sales")),
    db: Session = Depends(get_db),
):
    start, end, _, _ = _date_window(
        db, period, start_date, end_date, financial_year, comparison
    )
    rows = _filtered_vouchers(
        db, "Sales", start, end, product, customer, location
    )
    return _sales_rows(rows)


@app.get("/api/purchases")
def purchases(
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    supplier: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
    _user: User = Depends(auth.require_area("purchases")),
    db: Session = Depends(get_db),
):
    start, end, _, _ = _date_window(
        db, period, start_date, end_date, financial_year, comparison
    )
    rows = _filtered_vouchers(
        db, "Purchase", start, end, product, supplier, location
    )
    return _purchase_rows(rows)


@app.get("/api/inventory")
def inventory(
    product: str | None = None,
    location: str | None = None,
    _user: User = Depends(auth.require_area("inventory")),
    db: Session = Depends(get_db),
):
    query = db.query(InventoryItem)
    if product:
        query = query.filter(InventoryItem.product == product)
    if location:
        query = query.filter(InventoryItem.branch == location)

    items = query.all()
    return [
        [
            it.sku, it.product, it.category, it.branch, it.quantity,
            it.value, it.movement, rules._inventory_risk(it), it.id,
            it.reorder_level, it.lead_time_days, it.safety_stock,
        ]
        for it in items
    ]


@app.get("/api/payments")
def payments(
    _user: User = Depends(auth.require_area("cashflow")),
    db: Session = Depends(get_db),
):
    return rules.get_payment_table(db)


@app.get("/api/summary")
def summary(
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    customer: str | None = None,
    supplier: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    data = _build_summary(
        db, period, start_date, end_date, financial_year,
        product, customer, supplier, location, comparison,
    )
    allowed = set(auth.areas_for(user))

    for section in ("overview", "sales", "purchases", "inventory", "cashflow"):
        if section not in allowed:
            data.pop(section, None)

    return data


# ---------------------------------------------------------------- alerts

@app.get("/api/alerts")
def alerts(
    user: User = Depends(auth.require_area("alerts")),
    db: Session = Depends(get_db),
):
    allowed = set(auth.areas_for(user))
    combined = [
        a for a in rules.get_alerts(db) + compliance.alert_rows(db)
        if a[3] in allowed
    ]
    order = {"high": 0, "medium": 1, "low": 2}
    combined.sort(key=lambda a: order.get(a[0], 3))
    return combined


@app.get("/api/compliance")
def compliance_report(
    _user: User = Depends(auth.require_area("compliance")),
    db: Session = Depends(get_db),
):
    return compliance.build_compliance(db)


# ------------------------------------------------------- user management

class NewUserBody(BaseModel):
    username: str
    full_name: str
    role: str
    password: str


class UserUpdateBody(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordBody(BaseModel):
    password: str


def _target(db: Session, username: str) -> User:
    user = (
        db.query(User)
        .filter(User.username == username.lower())
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")
    return user


def _not_self(actor: User, target: User, what: str):
    if actor.username == target.username:
        raise HTTPException(
            status_code=400,
            detail=f"You cannot {what} your own account. Ask another administrator.",
        )


def _row(user: User):
    return {
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "role_label": auth.ROLES.get(user.role, {}).get("label", user.role),
        "active": user.is_active,
    }


@app.post("/api/users", status_code=201)
def add_user(
    body: NewUserBody,
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    return _row(
        auth.create_user(
            db, body.username, body.full_name, body.role, body.password
        )
    )


@app.patch("/api/users/{username}")
def update_user(
    username: str,
    body: UserUpdateBody,
    actor: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    user = _target(db, username)

    if body.role is not None and body.role != user.role:
        if body.role not in auth.ROLES:
            raise HTTPException(status_code=400, detail="Unknown role.")
        _not_self(actor, user, "change the role of")
        user.role = body.role

    if body.is_active is not None and body.is_active != user.is_active:
        _not_self(
            actor, user,
            "disable" if not body.is_active else "re-enable",
        )
        user.is_active = body.is_active

    if body.full_name is not None:
        name = " ".join(body.full_name.split())
        if not 2 <= len(name) <= 60:
            raise HTTPException(
                status_code=400,
                detail="Full name must be 2-60 characters.",
            )
        user.full_name = name

    db.commit()
    return _row(user)


@app.post("/api/users/{username}/password")
def reset_password(
    username: str,
    body: PasswordBody,
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    user = _target(db, username)
    auth.validate_password(body.password, user.username)
    user.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True}


@app.delete("/api/users/{username}")
def delete_user(
    username: str,
    actor: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    user = _target(db, username)
    _not_self(actor, user, "delete")
    db.delete(user)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------- AI chat

class ChatRequest(BaseModel):
    question: str
    period: str = "monthly"


@app.post("/api/ai/chat")
def chat_with_arth_ai(
    payload: ChatRequest,
    _user: User = Depends(auth.get_current_user),
):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a question.")
    if payload.period not in summaries.PERIOD_DAYS:
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Choose daily, weekly, monthly, or yearly.",
        )
    return ai_service.answer_query(
        user_prompt=question,
        period=payload.period,
    )


class RecommendationFeedback(BaseModel):
    recommendation_id: str
    action: str


@app.get("/api/recommendations")
def get_recommendations(
    period: str = "monthly",
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(Recommendation).count() == 0:
        recommendations.refresh_recommendations(db, period)
    return recommendations.list_recommendations(db)


@app.post("/api/recommendations/refresh")
def refresh_recs(
    period: str = "monthly",
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return recommendations.refresh_recommendations(db, period)


@app.post("/api/ai/recommendation-feedback")
def submit_recommendation_feedback(
    payload: RecommendationFeedback,
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = recommendations.set_feedback(
            db, payload.recommendation_id, payload.action
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="No such recommendation.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "recommendation": row}


@app.get("/api/forecasts")
def get_forecasts(
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return forecasts.build_forecasts(db)


@app.get("/api/quality")
def get_quality(
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return quality.build_quality(db)


@app.get("/api/explainability")
def get_explain(
    period: str = "monthly",
    _user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    from .explainability import explain_sales_drivers

    if period not in summaries.PERIOD_DAYS:
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Choose daily, weekly, monthly, or yearly.",
        )
    return explain_sales_drivers(db, period)


@app.get("/api/vouchers/{voucher_id}")
def voucher_detail(
    voucher_id: int,
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    v = db.query(Voucher).filter(Voucher.id == voucher_id).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Voucher not found.")

    area = {
        "Sales": "sales",
        "Purchase": "purchases",
        "Receipt": "cashflow",
        "Payment": "cashflow",
    }.get(v.voucher_type)

    if (
        area
        and area not in auth.areas_for(user)
        and "overview" not in auth.areas_for(user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Your role cannot open that voucher.",
        )

    return {
        "id": v.id,
        "date": v.voucher_date.isoformat() if v.voucher_date else None,
        "type": v.voucher_type,
        "party": v.party_name,
        "product": v.product,
        "amount": v.amount,
        "returns": v.returns_amount,
        "invoice": v.invoice_no,
        "city": v.city,
        "state": v.state,
        "pincode": v.pincode,
        "gstin": v.gstin,
        "gst": v.gst_amount,
        "mode": v.payment_mode,
        "status": v.status,
        "due_date": v.due_date.isoformat() if v.due_date else None,
        "po": v.po_number,
        "quantity": v.quantity,
        "received": v.received_quantity,
        "discount_pct": v.discount_pct,
        "territory": v.territory,
        "salesperson": v.salesperson,
        "godown": v.godown,
        "segment": v.segment,
    }


class StockSettings(BaseModel):
    reorder_level: float | None = None
    safety_stock: float | None = None
    lead_time_days: float | None = None


@app.patch("/api/inventory/{sku}")
def update_stock_settings(
    sku: str,
    body: StockSettings,
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    item = db.query(InventoryItem).filter(InventoryItem.sku == sku).first()
    if item is None:
        raise HTTPException(status_code=404, detail="SKU not found.")

    if body.reorder_level is not None:
        item.reorder_level = body.reorder_level
    if body.safety_stock is not None:
        item.safety_stock = body.safety_stock
    if body.lead_time_days is not None:
        item.lead_time_days = body.lead_time_days

    db.commit()
    return {
        "sku": item.sku,
        "reorder_level": item.reorder_level,
        "safety_stock": item.safety_stock,
        "lead_time_days": item.lead_time_days,
    }


# --------------------------------------------------------------- exports

@app.get("/api/export/excel")
def export_excel(
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    customer: str | None = None,
    supplier: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    summary_data = _export_filters(
        db, period, start_date, end_date, financial_year,
        product, customer, supplier, location, comparison,
    )
    start = date.fromisoformat(summary_data["window"]["start"])
    end = date.fromisoformat(summary_data["window"]["end"])
    sheets = {}
    areas = set(auth.areas_for(user))

    if "sales" in areas:
        sales_rows = _filtered_vouchers(
            db, "Sales", start, end, product, customer, location
        )
        sheets["Sales"] = [
            [
                "Customer", "Product", "Territory", "Salesperson",
                "Amount", "Returns", "Segment", "Voucher ID",
                "Invoice", "City", "State", "Pincode", "Discount %",
            ],
            *_sales_rows(sales_rows),
        ]

    if "purchases" in areas:
        purchase_rows = _filtered_vouchers(
            db, "Purchase", start, end, product, supplier, location
        )
        sheets["Purchases"] = [
            [
                "PO", "Supplier", "Product", "Qty", "Received",
                "Variance", "Debit Note", "Status", "Voucher ID", "Invoice",
            ],
            *_purchase_rows(purchase_rows),
        ]

    if "inventory" in areas:
        inventory_query = db.query(InventoryItem)
        if product:
            inventory_query = inventory_query.filter(
                InventoryItem.product == product
            )
        if location:
            inventory_query = inventory_query.filter(
                InventoryItem.branch == location
            )
        sheets["Inventory"] = [
            [
                "SKU", "Product", "Category", "Godown", "Qty",
                "Value", "Movement", "Risk", "ID", "Reorder Level",
                "Lead Time", "Safety Stock",
            ],
            *[
                [
                    it.sku, it.product, it.category, it.branch,
                    it.quantity, it.value, it.movement,
                    rules._inventory_risk(it), it.id,
                    it.reorder_level, it.lead_time_days, it.safety_stock,
                ]
                for it in inventory_query.all()
            ],
        ]

    if "cashflow" in areas:
        sheets["Payments"] = [
            [
                "Invoice", "Party", "Type", "Due", "Amount",
                "Ageing", "Status", "Voucher ID",
            ],
            *rules.get_payment_table(db),
        ]

    if not sheets:
        raise HTTPException(
            status_code=403,
            detail="Nothing to export for this role.",
        )

    data = export_files.excel_workbook(sheets)
    filename = f"arthpulse-{period}.xlsx"

    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/pdf")
def export_pdf(
    period: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    financial_year: str | None = None,
    product: str | None = None,
    customer: str | None = None,
    supplier: str | None = None,
    location: str | None = None,
    comparison: str = "previous_period",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    s = _export_filters(
        db, period, start_date, end_date, financial_year,
        product, customer, supplier, location, comparison,
    )
    o = s.get("overview") or {}
    areas = set(auth.areas_for(user))

    window = s["window"]
    lines = [
        f"Period: {s.get('label')} ({window['start']} to {window['end']})",
        f"Comparison: {window.get('comparison', 'none')}",
        f"Net sales: {o.get('net_sales', '—')}",
        f"Sales growth: {s.get('sales', {}).get('growth', '—')}%",
        f"Sales less purchases: {o.get('sales_less_purchases', '—')}",
        f"Receivables: {o.get('receivables', '—')}",
        f"Overdue receivables: {o.get('overdue', '—')}",
        f"Stock value: {o.get('stock_value', '—')}",
        f"Replenishment risks: {o.get('replenishment_risks', '—')}",
        f"Filters — Product: {product or 'All'}; Customer: {customer or 'All'}; "
        f"Supplier: {supplier or 'All'}; Location: {location or 'All'}",
        "ArthPulse suggestions are decision-support information; the owner remains responsible for business decisions.",
    ]

    tables = []

    if "sales" in areas:
        sales = s.get("sales") or {}
        tables.append((
            "Sales KPIs",
            [
                ["Metric", "Value"],
                ["Gross sales", sales.get("gross", 0)],
                ["Returns", sales.get("returns", 0)],
                ["Net sales", sales.get("net", 0)],
                ["Returns %", sales.get("returns_pct", 0)],
                ["Growth %", sales.get("growth", "—")],
                ["Discount value", sales.get("discount_value", 0)],
            ],
        ))
        sales_rows = _filtered_vouchers(
            db, "Sales",
            date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
            product, customer, location,
        )
        tables.append((
            "Sales transactions",
            [
                ["Customer", "Product", "Territory", "Salesperson", "Amount", "Returns", "Segment"],
                *[
                    [
                        v.party_name, v.product, v.territory,
                        v.salesperson, v.amount, v.returns_amount,
                        v.segment,
                    ]
                    for v in sales_rows
                ],
            ],
        ))
        tables.append((
            "Top customers",
            [["Customer", "Net sales"], *(sales.get("customers", {}).get("top") or [])],
        ))
        tables.append((
            "Top products",
            [["Product", "Net sales"], *(sales.get("products", {}).get("top") or [])],
        ))

    if "purchases" in areas:
        purchases_data = s.get("purchases") or {}
        tables.append((
            "Purchase KPIs",
            [
                ["Metric", "Value"],
                ["Total purchases", purchases_data.get("total", 0)],
                ["Growth %", purchases_data.get("growth", "—")],
                ["Debit notes", purchases_data.get("debit_notes", 0)],
                ["Debit note value", purchases_data.get("debit_note_value", 0)],
                ["Open purchase orders", purchases_data.get("open_pos", 0)],
                ["Open PO value", purchases_data.get("open_po_value", 0)],
                ["Top supplier", purchases_data.get("top_supplier", "—")],
            ],
        ))
        purchase_rows = _filtered_vouchers(
            db, "Purchase",
            date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
            product, supplier, location,
        )
        tables.append((
            "Purchase transactions",
            [
                ["PO", "Supplier", "Product", "Qty", "Received", "Variance", "Status"],
                *[
                    [
                        v.po_number, v.party_name, v.product,
                        v.quantity, v.received_quantity,
                        (v.received_quantity or 0) - (v.quantity or 0),
                        v.status,
                    ]
                    for v in purchase_rows
                ],
            ],
        ))

    if "inventory" in areas:
        inv = s.get("inventory") or {}
        tables.append((
            "Inventory KPIs",
            [
                ["Metric", "Value"],
                ["Stock value", inv.get("stock_value", 0)],
                ["Low stock items", inv.get("low_stock", 0)],
                ["Negative stock items", inv.get("negative", 0)],
                ["Overstock value", inv.get("overstock_value", 0)],
                ["Inventory days", inv.get("inventory_days", "—")],
            ],
        ))
        tables.append((
            "Inventory by godown",
            [
                ["Godown", "Quantity", "Value", "SKUs"],
                *[
                    [name, value.get("qty"), value.get("value"), value.get("skus")]
                    for name, value in (inv.get("godowns") or {}).items()
                ],
            ],
        ))
        tables.append((
            "Inventory ageing",
            [["Product", "Godown", "Days since movement", "Movement", "Value"],
             *(inv.get("ageing") or [])],
        ))

    if "cashflow" in areas:
        cash = s.get("cashflow") or {}
        tables.append((
            "Cash flow KPIs",
            [
                ["Metric", "Value"],
                ["Receivables", cash.get("receivables", 0)],
                ["Overdue receivables", cash.get("overdue_receivables", 0)],
                ["Payables", cash.get("payables", 0)],
                ["Payables due this week", cash.get("payables_due_week", 0)],
                ["Net working capital", cash.get("net_working_capital", 0)],
                ["Due today", cash.get("due_today", 0)],
            ],
        ))
        tables.append((
            "Receivables ageing",
            [["Ageing bucket", "Amount"],
             *[[k, v] for k, v in (cash.get("ageing") or {}).items()]],
        ))
        tables.append((
            "Payables ageing",
            [["Ageing bucket", "Amount"],
             *[[k, v] for k, v in (cash.get("payable_ageing") or {}).items()]],
        ))

    data = export_files.pdf_report(
        "ArthPulse Business Report",
        lines,
        tables,
    )

    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=arthpulse-{period}.pdf"
        },
    )
