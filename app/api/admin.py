"""
Admin dashboard router.

Pages
-----
GET  /admin/login       login form
POST /admin/login       verifies user exists + has admin role, sets cookie
POST /admin/logout      clears the cookie
GET  /admin             overview (counters + latest decisions)
GET  /admin/audit       filterable audit log
GET  /admin/users       users & their assigned role
POST /admin/users/assign-role   reassign a user's role
GET  /admin/roles       roles & their permissions
GET  /admin/employees   employee directory

Access control
--------------
Every route except /admin/login is guarded by `require_admin`, which
reuses the same RBAC model the rest of the system relies on. There is
no separate admin table: an "admin" is simply a user whose role is
named "admin". If the admin role is missing that permission, the
dashboard is unreachable — which is the whole point.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.employee_model import Employee
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

ADMIN_COOKIE_NAME = "admin_user"
ADMIN_ROLE_NAME = "admin"


def _current_admin(request: Request, db: Session) -> Optional[User]:
    """
    Resolve the admin user from the cookie, or return None if the
    visitor is not logged in / not an admin.
    """
    username = request.cookies.get(ADMIN_COOKIE_NAME)
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
    Dependency for protected admin routes. On failure we raise an
    HTTPException with status 401/403, which a lightweight exception
    handler on the FastAPI app converts into a redirect to /admin/login.

    This keeps each route body clean (`user = Depends(require_admin)`)
    while still producing a friendly redirect rather than a JSON error.
    """
    user = _current_admin(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="admin_login_required")
    return user


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
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return RedirectResponse(
            url="/admin/login?error=unknown_user", status_code=303
        )
    if not user.role or user.role.name != ADMIN_ROLE_NAME:
        return RedirectResponse(
            url="/admin/login?error=not_admin", status_code=303
        )

    response = RedirectResponse(url="/admin", status_code=303)
    # httponly + samesite=lax is sufficient for a demo; change to
    # secure=True behind HTTPS in production.
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=user.username,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


# --- dashboard pages ---------------------------------------------------


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


@router.get("/audit", response_class=HTMLResponse)
def audit_view(
    request: Request,
    username_filter: Optional[str] = Query(default=None, alias="username"),
    tool_name: Optional[str] = Query(default=None),
    stage: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),  # allow | deny
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


@router.get("/users", response_class=HTMLResponse)
def users_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
    notice: Optional[str] = None,
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
            "notice": notice,
            "active_tab": "users",
        },
    )


@router.post("/users/assign-role")
def assign_role(
    target_username: str = Form(...),
    role_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.username == target_username).first()
    if not target:
        return RedirectResponse(
            url="/admin/users?notice=user_not_found", status_code=303
        )

    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return RedirectResponse(
            url="/admin/users?notice=role_not_found", status_code=303
        )

    # Guard: don't let an admin demote themselves out of the admin role.
    if target.id == user.id and role.name != ADMIN_ROLE_NAME:
        return RedirectResponse(
            url="/admin/users?notice=cannot_demote_self", status_code=303
        )

    target.role = role
    db.commit()
    return RedirectResponse(
        url="/admin/users?notice=role_updated", status_code=303
    )


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
            "active_tab": "roles",
        },
    )


@router.get("/employees", response_class=HTMLResponse)
def employees_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    employees = db.query(Employee).order_by(Employee.id.asc()).all()
    return templates.TemplateResponse(
        "admin/employees.html",
        {
            "request": request,
            "title": "Employees",
            "admin_user": user,
            "employees": employees,
            "active_tab": "employees",
        },
    )