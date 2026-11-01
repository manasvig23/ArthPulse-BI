from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import auth, compliance, rules, summaries
from .database import Base, SessionLocal, engine, get_db
from .models import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup: make sure every table exists, clear leftover demo accounts, ensure an admin exists."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        removed = auth.purge_legacy_demo_users(db)
        if removed:
            print(f"Removed {removed} leftover demo account(s).")
        if auth.ensure_default_admin(db):
            shown = "the password from ARTHPULSE_ADMIN_PASSWORD" if auth.DEFAULT_ADMIN_PASSWORD != auth.BUILTIN_ADMIN_PASSWORD \
                else f"password '{auth.BUILTIN_ADMIN_PASSWORD}' (change it after signing in)"
            print(f"Created the default administrator: username '{auth.DEFAULT_ADMIN_USERNAME}', {shown}.")
    finally:
        db.close()
    yield


app = FastAPI(title="ArthPulse API", lifespan=lifespan)

# Allow the frontend (Vite dev server etc.) to call this API from the browser.
# Loosened for the demo -- restrict to your real frontend origin before deploying.
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
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    # same message for "no such user" and "wrong password" so usernames cannot be probed
    if user is None or not user.is_active or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return {"token": auth.create_token(user.username, user.role), "user": auth.public_user(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(auth.get_current_user)):
    return auth.public_user(user)


@app.get("/api/auth/roles")
def roles_overview(_user: User = Depends(auth.require_area("users")), db: Session = Depends(get_db)):
    """Admin only: the permission matrix and the list of users."""
    return {
        "areas": [{"id": k, "label": v} for k, v in auth.AREAS.items()],
        "roles": [{"id": k, "label": v["label"], "areas": v["areas"]} for k, v in auth.ROLES.items()],
        "users": [{"username": u.username, "full_name": u.full_name,
                   "role": u.role, "role_label": auth.ROLES.get(u.role, {}).get("label", u.role),
                   "active": u.is_active} for u in db.query(User).order_by(User.id).all()],
    }


# ------------------------------------------------------------- dashboards
@app.get("/api/sales")
def sales(period: str | None = None, _user: User = Depends(auth.require_area("sales")),
          db: Session = Depends(get_db)):
    """All sales rows, or only those inside the period window if given."""
    if period in summaries.PERIOD_DAYS:
        start, end, _, _ = summaries.get_window(db, period)
        return rules.get_sales_table(db, start, end)
    return rules.get_sales_table(db)


@app.get("/api/purchases")
def purchases(period: str | None = None, _user: User = Depends(auth.require_area("purchases")),
              db: Session = Depends(get_db)):
    if period in summaries.PERIOD_DAYS:
        start, end, _, _ = summaries.get_window(db, period)
        return rules.get_purchase_table(db, start, end)
    return rules.get_purchase_table(db)


@app.get("/api/inventory")
def inventory(_user: User = Depends(auth.require_area("inventory")), db: Session = Depends(get_db)):
    return rules.get_inventory_table(db)


@app.get("/api/payments")
def payments(_user: User = Depends(auth.require_area("cashflow")), db: Session = Depends(get_db)):
    return rules.get_payment_table(db)


@app.get("/api/summary")
def summary(period: str = "monthly", user: User = Depends(auth.get_current_user),
            db: Session = Depends(get_db)):
    """KPIs and breakdowns, trimmed to the sections this user's role may see."""
    data = summaries.build_summary(db, period)
    allowed = set(auth.areas_for(user))
    for section in ("overview", "sales", "purchases", "inventory", "cashflow"):
        if section not in allowed:
            data.pop(section, None)
    return data


@app.get("/api/alerts")
def alerts(user: User = Depends(auth.require_area("alerts")), db: Session = Depends(get_db)):
    """Stock, payment and compliance alerts, limited to areas the role may see."""
    allowed = set(auth.areas_for(user))
    combined = [a for a in rules.get_alerts(db) + compliance.alert_rows(db) if a[3] in allowed]
    order = {"high": 0, "medium": 1, "low": 2}
    combined.sort(key=lambda a: order.get(a[0], 3))
    return combined


@app.get("/api/compliance")
def compliance_report(_user: User = Depends(auth.require_area("compliance")),
                      db: Session = Depends(get_db)):
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
    user = db.query(User).filter(User.username == username.lower()).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")
    return user


def _not_self(actor: User, target: User, what: str):
    """An admin may not demote, disable or delete their own account (would risk locking everyone out)."""
    if actor.username == target.username:
        raise HTTPException(status_code=400, detail=f"You cannot {what} your own account. Ask another administrator.")


def _row(u: User):
    return {"username": u.username, "full_name": u.full_name, "role": u.role,
            "role_label": auth.ROLES.get(u.role, {}).get("label", u.role), "active": u.is_active}


@app.post("/api/users", status_code=201)
def add_user(body: NewUserBody, _user: User = Depends(auth.require_area("users")),
             db: Session = Depends(get_db)):
    return _row(auth.create_user(db, body.username, body.full_name, body.role, body.password))


@app.patch("/api/users/{username}")
def update_user(username: str, body: UserUpdateBody, actor: User = Depends(auth.require_area("users")),
                db: Session = Depends(get_db)):
    user = _target(db, username)
    if body.role is not None and body.role != user.role:
        if body.role not in auth.ROLES:
            raise HTTPException(status_code=400, detail="Unknown role.")
        _not_self(actor, user, "change the role of")
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        _not_self(actor, user, "disable" if not body.is_active else "re-enable")
        user.is_active = body.is_active
    if body.full_name is not None:
        name = " ".join(body.full_name.split())
        if not 2 <= len(name) <= 60:
            raise HTTPException(status_code=400, detail="Full name must be 2-60 characters.")
        user.full_name = name
    db.commit()
    return _row(user)


@app.post("/api/users/{username}/password")
def reset_password(username: str, body: PasswordBody, _user: User = Depends(auth.require_area("users")),
                   db: Session = Depends(get_db)):
    user = _target(db, username)
    auth.validate_password(body.password, user.username)
    user.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True}


@app.delete("/api/users/{username}")
def delete_user(username: str, actor: User = Depends(auth.require_area("users")),
                db: Session = Depends(get_db)):
    user = _target(db, username)
    _not_self(actor, user, "delete")
    db.delete(user)
    db.commit()
    return {"ok": True}