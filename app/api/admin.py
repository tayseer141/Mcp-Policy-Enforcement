"""
Admin dashboard router (HTML view layer).

This module is the HTML face of the admin area. All data mutations now
flow through the JSON API in app/api/admin_api.py — the templates
intercept their forms and call those endpoints via fetch().

This file owns:
  - Session management (login/logout): these still work via form POST
    because they set/clear an HttpOnly cookie and need to redirect.
  - GET pages that render the admin shell with seeded data.

Pages
-----
GET  /admin/login                       login form
POST /admin/login                       verify user + admin role, set cookie
POST /admin/logout                      clear the cookie

GET  /admin                             overview (counters + recent decisions)
GET  /admin/audit                       filterable audit log
GET  /admin/users                       users page (mutations via JSON API)
GET  /admin/roles                       roles page (mutations via JSON API)
GET  /admin/customers                   customer directory (read-only)

Access control
--------------
Every route except /admin/login is guarded by `require_admin`, which
reuses the same RBAC model the rest of the system relies on. An
"admin" is simply a user whose role name matches ADMIN_ROLE_NAME.
There is no separate admin table. The same dependency is reused by
the admin JSON API for symmetry.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_session_token,
    verify_password,
    verify_session_token,
)
from app.db.deps import get_db
from app.models.customer_model import Customer
from app.models.rbac_models import Permission, Role, User
from app.services.audit_service import (
    decision_counters,
    distinct_tools,
    distinct_usernames,
    list_decisions,
)


router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


# --- session helpers ---------------------------------------------------

ADMIN_COOKIE_NAME = "admin_session"
# If your seed data uses capitalised "Admin", change this to "Admin".
ADMIN_ROLE_NAME = "admin"


def _current_admin(request: Request, db: Session) -> Optional[User]:
    # The cookie is an HMAC-signed, expiring session token — not a plain
    # username. verify_session_token fails closed on forgery or expiry.
    username = verify_session_token(request.cookies.get(ADMIN_COOKIE_NAME))
    if not username:
        return None

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.role:
        return None
    if user.role.name != ADMIN_ROLE_NAME:
        return None
    return user


def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """
    Cookie-based admin guard. Reused by the admin JSON API (admin_api.py)
    so HTML pages and JSON clients share the exact same auth path.
    """
    user = _current_admin(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="admin_login_required")
    return user


def _tool_backed_permission_names() -> set[str]:
    """
    Names of permissions that correspond to a registered @mcp.tool().
    Used by the dashboard to mark which permissions are auto-synced
    (and therefore will re-appear on next server start if deleted).
    Imported by admin_api.py for the same purpose.
    """
    try:
        from app.mcp.server import mcp
        return set(mcp._tool_manager._tools.keys())
    except Exception:
        return set()


# --- login / logout ----------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        "admin/login.html",
        {
            "request": request,
            "title": "Admin Login",
            "error": error,
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()

    # One error code for unknown user AND wrong password, so the form
    # can't be used to enumerate valid usernames.
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(
            url="/admin/login?error=bad_credentials", status_code=303
        )
    if not user.role or user.role.name != ADMIN_ROLE_NAME:
        return RedirectResponse(
            url="/admin/login?error=not_admin", status_code=303
        )

    ttl_seconds = settings.ADMIN_SESSION_TTL_HOURS * 3600
    token = create_session_token(user.username, ttl_seconds)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        max_age=ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


# --- dashboard overview ------------------------------------------------


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    counters = decision_counters(db)
    recent = list_decisions(db, limit=15)
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "title": "Admin Dashboard",
            "admin_user": user,
            "counters": counters,
            "recent": recent,
            "active_tab": "overview",
        },
    )


# --- audit log ---------------------------------------------------------


@router.get("/audit", response_class=HTMLResponse)
def audit_view(
    request: Request,
    username_filter: Optional[str] = Query(default=None, alias="username"),
    tool_name: Optional[str] = Query(default=None),
    stage: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    rows = list_decisions(
        db,
        username=username_filter,
        tool_name=tool_name,
        stage=stage,
        decision=decision,
        limit=limit,
    )
    return templates.TemplateResponse(
        "admin/audit.html",
        {
            "request": request,
            "title": "Audit Log",
            "admin_user": user,
            "rows": rows,
            "active_tab": "audit",
            "filters": {
                "username": username_filter or "",
                "tool_name": tool_name or "",
                "stage": stage or "",
                "decision": decision or "",
                "limit": limit,
            },
            "known_usernames": distinct_usernames(db),
            "known_tools": distinct_tools(db),
            "known_stages": ["rbac", "intent", "policy", "validation"],
        },
    )


# --- users -------------------------------------------------------------
# Mutations live in app/api/admin_api.py at /api/v1/admin/users.


@router.get("/users", response_class=HTMLResponse)
def users_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.username.asc()).all()
    roles = db.query(Role).order_by(Role.name.asc()).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "title": "Users",
            "admin_user": user,
            "users": users,
            "roles": roles,
            "active_tab": "users",
        },
    )


# --- roles & permissions ----------------------------------------------
# Mutations live in app/api/admin_api.py at /api/v1/admin/roles and
# /api/v1/admin/permissions.


@router.get("/roles", response_class=HTMLResponse)
def roles_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    roles = db.query(Role).order_by(Role.name.asc()).all()
    all_permissions = (
        db.query(Permission).order_by(Permission.name.asc()).all()
    )
    return templates.TemplateResponse(
        "admin/roles.html",
        {
            "request": request,
            "title": "Roles & Permissions",
            "admin_user": user,
            "roles": roles,
            "all_permissions": all_permissions,
            "tool_backed_permissions": _tool_backed_permission_names(),
            "active_tab": "roles",
            "admin_role_name": ADMIN_ROLE_NAME,
        },
    )


# --- customers ---------------------------------------------------------


@router.get("/customers", response_class=HTMLResponse)
def customers_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    customers = db.query(Customer).order_by(Customer.id.asc()).all()
    return templates.TemplateResponse(
        "admin/customers.html",
        {
            "request": request,
            "title": "Customers",
            "admin_user": user,
            "customers": customers,
            "active_tab": "customers",
        },
    )


# --- policies ----------------------------------------------------------
# Mutations live in app/api/policy_api.py at /api/v1/admin/policies. The
# natural-language authoring box also calls that API (POST .../draft then
# POST .../policies on confirm).


@router.get("/policies", response_class=HTMLResponse)
def policies_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from app.models.policy_model import Policy
    from app.policy.catalog import POLICY_TYPES

    policies = (
        db.query(Policy)
        .order_by(Policy.tool_name.asc(), Policy.name.asc())
        .all()
    )
    policy_types = [
        {
            "policy_type": ptype,
            "tool_name": spec["tool_name"],
            "label": spec["label"],
            "unit": spec["unit"],
            "value_kind": spec["value_kind"],
            "default": spec["default"],
            "help": spec["help"],
        }
        for ptype, spec in POLICY_TYPES.items()
    ]
    return templates.TemplateResponse(
        "admin/policies.html",
        {
            "request": request,
            "title": "Policies",
            "admin_user": user,
            "policies": policies,
            "policy_types": policy_types,
            "active_tab": "policies",
        },
    )