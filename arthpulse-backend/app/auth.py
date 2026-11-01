"""
Authentication and role-based access control.

How it works
  * A user signs in with username + password -> the API returns a signed token.
  * The frontend sends it as "Authorization: Bearer <token>" on every request.
  * Each endpoint declares which AREA it belongs to (sales, purchases, ...).
    A role may use an area only if it is listed in ROLES below.

Built with the standard library only (PBKDF2 for passwords, HMAC-SHA256
for tokens), so no extra packages are needed.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
 
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
 
from .database import get_db
from .models import User
 
SECRET = os.environ.get("ARTHPULSE_SECRET", "dev-secret-change-me").encode()
TOKEN_HOURS = 8
MIN_PASSWORD = 8
 
DEFAULT_ADMIN_USERNAME = "admin"
BUILTIN_ADMIN_PASSWORD = "Admin@123"      # documented default
DEFAULT_ADMIN_PASSWORD = os.environ.get("ARTHPULSE_ADMIN_PASSWORD", BUILTIN_ADMIN_PASSWORD)
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
 
LEGACY_DEMO_USERNAMES = {"owner", "sales", "purchase", "inventory", "finance", "admin"}
LEGACY_DEMO_PASSWORD = "demo123"
 
# ------------------------------------------------------ roles and areas
AREAS = {
    "overview": "Business overview",
    "sales": "Sales dashboard",
    "purchases": "Purchase dashboard",
    "inventory": "Inventory dashboard",
    "cashflow": "Cash flow dashboard",
    "compliance": "Compliance engine",
    "alerts": "Alert Centre",
    "reports": "Reports",
    "users": "Access control (admin)",
}
 
# THE permission table. Change a role's areas here and the whole app follows.
ROLES = {
    "owner": {
        "label": "Business Owner",
        "areas": ["overview", "sales", "purchases", "inventory", "cashflow",
                  "compliance", "alerts", "reports"],
    },
    "sales_manager": {
        "label": "Sales Manager",
        "areas": ["sales", "reports"],
    },
    "purchase_manager": {
        "label": "Purchase Manager",
        "areas": ["purchases", "reports"],
    },
    "inventory_manager": {
        "label": "Inventory Manager",
        "areas": ["inventory", "alerts", "reports"],
    },
    "finance": {
        "label": "Finance / Accounts",
        "areas": ["overview", "cashflow", "compliance", "alerts", "reports"],
    },
    "admin": {
        "label": "Administrator",
        "areas": ["overview", "sales", "purchases", "inventory", "cashflow",
                  "compliance", "alerts", "reports", "users"],
    },
}
 
# ----------------------------------------------------------- passwords
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"
 
 
def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False
 
 
# -------------------------------------------------------------- tokens
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
 
 
def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
 
 
def _sign(body: str) -> str:
    return _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
 
 
def create_token(username: str, role: str, hours: float = TOKEN_HOURS) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time() + hours * 3600)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"
 
 
def decode_token(token: str):
    """Returns the payload, or None if the token is forged, malformed or expired."""
    try:
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(body)):
            return None
        payload = json.loads(_unb64(body))
        return payload if payload["exp"] >= time.time() else None
    except Exception:
        return None
 
 
# ---------------------------------------------------------- dependencies
bearer = HTTPBearer(auto_error=False)
 
 
def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    user = db.query(User).filter(User.username == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not available")
    return user
 
 
def areas_for(user: User) -> list[str]:
    return ROLES.get(user.role, {}).get("areas", [])
 
 
def require_area(area: str):
    """Use as Depends(require_area('sales')): 401 if signed out, 403 if the role lacks the area."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if area not in areas_for(user):
            label = ROLES.get(user.role, {}).get("label", user.role)
            raise HTTPException(status_code=403, detail=f"{label} cannot access {AREAS.get(area, area)}")
        return user
    return checker
 
 
def uses_builtin_default_password(user: User) -> bool:
    """True while the default admin still has the documented starting password."""
    return (user.username == DEFAULT_ADMIN_USERNAME
            and verify_password(BUILTIN_ADMIN_PASSWORD, user.password_hash))
 
 
def public_user(user: User) -> dict:
    return {
        "username": user.username, "full_name": user.full_name, "role": user.role,
        "role_label": ROLES.get(user.role, {}).get("label", user.role),
        "areas": areas_for(user),
        "default_password": uses_builtin_default_password(user),
    }
 
 
# -------------------------------------------------------- account management
def validate_new_account(username: str, full_name: str, password: str, role: str | None = None):
    """Returns the cleaned (username, full_name) or raises a 400 with a plain-English reason."""
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Username must be 3-32 characters: lowercase letters, digits, dot, underscore or hyphen.")
    full_name = " ".join(full_name.split())
    if not 2 <= len(full_name) <= 60:
        raise HTTPException(400, "Full name must be 2-60 characters.")
    validate_password(password, username)
    if role is not None and role not in ROLES:
        raise HTTPException(400, "Unknown role.")
    return username, full_name
 
 
def validate_password(password: str, username: str = ""):
    if not MIN_PASSWORD <= len(password) <= 128:
        raise HTTPException(400, f"Password must be {MIN_PASSWORD}-128 characters.")
    if password.lower() in (LEGACY_DEMO_PASSWORD, username):
        raise HTTPException(400, "Choose a less guessable password.")
 
 
def create_user(db: Session, username: str, full_name: str, role: str, password: str) -> User:
    username, full_name = validate_new_account(username, full_name, password, role)
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "That username is already taken.")
    user = User(username=username, full_name=full_name, role=role,
                password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
 
 
def ensure_default_admin(db: Session) -> bool:
    """If there are no users at all, create the default administrator. Returns True if created."""
    if db.query(User).count() > 0:
        return False
    if len(DEFAULT_ADMIN_PASSWORD) < MIN_PASSWORD:
        raise RuntimeError(f"ARTHPULSE_ADMIN_PASSWORD must be at least {MIN_PASSWORD} characters.")
    db.add(User(username=DEFAULT_ADMIN_USERNAME, full_name="System Admin", role="admin",
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD)))
    db.commit()
    return True
 
 
def purge_legacy_demo_users(db: Session) -> int:
    """Delete leftover demo accounts (known username AND the old demo password) from earlier builds."""
    removed = 0
    for user in db.query(User).filter(User.username.in_(LEGACY_DEMO_USERNAMES)).all():
        if verify_password(LEGACY_DEMO_PASSWORD, user.password_hash):
            db.delete(user)
            removed += 1
    if removed:
        db.commit()
    return removed