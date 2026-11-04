from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.aichat import ai_service
from . import auth, compliance, export_files, forecasts, quality, recommendations, rules, schema, summaries, tally_sync
from .database import Base, SessionLocal, engine, get_db
from .models import InventoryItem, Recommendation, User, Voucher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup: make sure every table exists, clear leftover demo accounts, ensure an admin exists."""
    Base.metadata.create_all(bind=engine)
    schema.ensure_schema()
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

# Allow the frontend (Vite dev server etc.) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ArthPulse API is running"}


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

    # Use the same message for an unknown username and an incorrect password.
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
    """Admin only: the permission matrix and the list of users."""
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
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/sync/synthetic")
def sync_synthetic(
    _user: User = Depends(auth.require_area("users")),
    db: Session = Depends(get_db),
):
    try:
        return tally_sync.reload_synthetic(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync/push-educational")
def push_educational(
    body: SyncBody | None = None,
    _user: User = Depends(auth.require_area("users")),
):
    try:
        return tally_sync.push_educational_to_tally(
            body.company if body else None
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ------------------------------------------------------------- dashboards
@app.get("/api/sales")
def sales(
    period: str | None = None,
    _user: User = Depends(auth.require_area("sales")),
    db: Session = Depends(get_db),
):
    """All sales rows, or only those inside the period window if given."""
    if period in summaries.PERIOD_DAYS:
        start, end, _, _ = summaries.get_window(db, period)
        return rules.get_sales_table(db, start, end)

    return rules.get_sales_table(db)


@app.get("/api/purchases")
def purchases(
    period: str | None = None,
    _user: User = Depends(auth.require_area("purchases")),
    db: Session = Depends(get_db),
):
    if period in summaries.PERIOD_DAYS:
        start, end, _, _ = summaries.get_window(db, period)
        return rules.get_purchase_table(db, start, end)

    return rules.get_purchase_table(db)


@app.get("/api/inventory")
def inventory(
    _user: User = Depends(auth.require_area("inventory")),
    db: Session = Depends(get_db),
):
    return rules.get_inventory_table(db)


@app.get("/api/payments")
def payments(
    _user: User = Depends(auth.require_area("cashflow")),
    db: Session = Depends(get_db),
):
    return rules.get_payment_table(db)


@app.get("/api/summary")
def summary(
    period: str = "monthly",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """KPIs and breakdowns, trimmed to the sections this user's role may see."""
    data = summaries.build_summary(db, period)
    allowed = set(auth.areas_for(user))

    for section in ("overview", "sales", "purchases", "inventory", "cashflow"):
        if section not in allowed:
            data.pop(section, None)

    return data


@app.get("/api/alerts")
def alerts(
    user: User = Depends(auth.require_area("alerts")),
    db: Session = Depends(get_db),
):
    """Stock, payment and compliance alerts, limited to areas the role may see."""
    allowed = set(auth.areas_for(user))
    combined = [
        a
        for a in rules.get_alerts(db) + compliance.alert_rows(db)
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
    """All five compliance checks with findings, evidence and exposure."""
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
    """Prevent an admin from locking themselves out of the system."""
    if actor.username == target.username:
        raise HTTPException(
            status_code=400,
            detail=f"You cannot {what} your own account. Ask another administrator.",
        )


def _row(u: User):
    return {
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
        "role_label": auth.ROLES.get(u.role, {}).get("label", u.role),
        "active": u.is_active,
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
            actor,
            user,
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
        raise HTTPException(
            status_code=400,
            detail="Please enter a question.",
        )

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
    action: str  # "saved", "dismissed", "useful", "not_useful"


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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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


@app.get("/api/export/excel")
def export_excel(
    period: str = "monthly",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    sheets = {}

    if "sales" in auth.areas_for(user):
        sheets["Sales"] = [
            ["Customer", "Product", "Territory", "Salesperson", "Amount", "Returns", "Segment"],
            *rules.get_sales_table(db),
        ]

    if "purchases" in auth.areas_for(user):
        sheets["Purchases"] = [
            ["PO", "Supplier", "Product", "Qty", "Received", "Variance", "DN", "Status"],
            *rules.get_purchase_table(db),
        ]

    if "inventory" in auth.areas_for(user):
        sheets["Inventory"] = [
            ["SKU", "Product", "Category", "Godown", "Qty", "Value", "Movement", "Risk"],
            *rules.get_inventory_table(db),
        ]

    if "cashflow" in auth.areas_for(user):
        sheets["Payments"] = [
            ["Invoice", "Party", "Type", "Due", "Amount", "Ageing", "Status"],
            *rules.get_payment_table(db),
        ]

    if not sheets:
        raise HTTPException(
            status_code=403,
            detail="Nothing to export for this role.",
        )

    data = export_files.excel_workbook(sheets)

    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=arthpulse-{period}.xlsx"
        },
    )


@app.get("/api/export/pdf")
def export_pdf(
    period: str = "monthly",
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    s = summaries.build_summary(db, period)
    o = s.get("overview") or {}

    lines = [
        f"Period: {s.get('label')} ({s['window']['start']} to {s['window']['end']})",
        f"Net sales {o.get('net_sales')}, receivables {o.get('receivables')}, stock {o.get('stock_value')}.",
        "ArthPulse suggestions only — the owner decides.",
    ]

    tables = []

    if "sales" in auth.areas_for(user):
        tables.append(
            (
                "Sales (sample)",
                [
                    ["Customer", "Product", "Amount"],
                    *[
                        [r[0], r[1], r[4]]
                        for r in rules.get_sales_table(db)[:15]
                    ],
                ],
            )
        )

    data = export_files.pdf_report(
        "ArthPulse executive report",
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
