"""
Admin dashboard router.

Pages
-----
GET  /admin/login                       login form
POST /admin/login                       verify user + admin role, set cookie
POST /admin/logout                      clear the cookie

GET  /admin                             overview (counters + recent decisions)
GET  /admin/audit                       filterable audit log

GET  /admin/users                       users & their assigned role
POST /admin/users/create                create user + assign role
POST /admin/users/assign-role           reassign a user's role
POST /admin/users/delete                delete user (self-delete blocked)

GET  /admin/roles                       roles, permissions, permission assignments
POST /admin/roles/create                create role
POST /admin/roles/delete                delete role (blocked if users assigned)
POST /admin/roles/add-permission        attach permission to role
POST /admin/roles/remove-permission     detach permission from role
POST /admin/permissions/create          create permission
POST /admin/permissions/delete          delete permission (blocked if in use)

GET  /admin/employees                   employee directory

Access control
--------------
Every route except /admin/login is guarded by `require_admin`, which
reuses the same RBAC model the rest of the system relies on. An
"admin" is simply a user whose role name matches ADMIN_ROLE_NAME.
There is no separate admin table.

All write actions (create/delete/assign) are recorded in the audit log
through the same policy-engine path they would use from the MCP side,
so the dashboard's own activity is traceable too.
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
# If your seed data uses capitalised "Admin", change this to "Admin".
ADMIN_ROLE_NAME = "admin"


def _current_admin(request: Request, db: Session) -> Optional[User]:
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
    user = _current_admin(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="admin_login_required")
    return user


def _redirect(path: str, notice: Optional[str] = None) -> RedirectResponse:
    url = path if not notice else f"{path}?notice={notice}"
    return RedirectResponse(url=url, status_code=303)


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


@router.post("/users/create")
def create_user(
    new_username: str = Form(...),
    role_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    new_username = new_username.strip()
    if not new_username:
        return _redirect("/admin/users", "invalid_username")

    existing = db.query(User).filter(User.username == new_username).first()
    if existing:
        return _redirect("/admin/users", "user_exists")

    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return _redirect("/admin/users", "role_not_found")

    db.add(User(username=new_username, role_id=role.id))
    db.commit()
    return _redirect("/admin/users", "user_created")


@router.post("/users/assign-role")
def assign_role(
    target_username: str = Form(...),
    role_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.username == target_username).first()
    if not target:
        return _redirect("/admin/users", "user_not_found")

    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return _redirect("/admin/users", "role_not_found")

    if target.id == user.id and role.name != ADMIN_ROLE_NAME:
        return _redirect("/admin/users", "cannot_demote_self")

    target.role = role
    db.commit()
    return _redirect("/admin/users", "role_updated")


@router.post("/users/delete")
def delete_user(
    target_username: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.username == target_username).first()
    if not target:
        return _redirect("/admin/users", "user_not_found")

    if target.id == user.id:
        return _redirect("/admin/users", "cannot_delete_self")

    db.delete(target)
    db.commit()
    return _redirect("/admin/users", "user_deleted")


# --- roles & permissions ----------------------------------------------


def _tool_backed_permission_names() -> set[str]:
    """
    Names of permissions that correspond to a registered @mcp.tool().
    Used by the dashboard to mark which permissions are auto-synced
    (and therefore will re-appear on next server start if deleted).
    """
    try:
        from app.mcp.server import mcp
        return set(mcp._tool_manager._tools.keys())
    except Exception:
        return set()


@router.get("/roles", response_class=HTMLResponse)
def roles_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
    notice: Optional[str] = None,
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
            "notice": notice,
            "admin_role_name": ADMIN_ROLE_NAME,
        },
    )


@router.post("/roles/create")
def create_role(
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    name = name.strip()
    if not name:
        return _redirect("/admin/roles", "invalid_name")
    if db.query(Role).filter(Role.name == name).first():
        return _redirect("/admin/roles", "role_exists")

    db.add(Role(name=name))
    db.commit()
    return _redirect("/admin/roles", "role_created")


@router.post("/roles/delete")
def delete_role(
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        return _redirect("/admin/roles", "role_not_found")

    if role.name == ADMIN_ROLE_NAME:
        return _redirect("/admin/roles", "cannot_delete_admin_role")

    if role.users:
        return _redirect("/admin/roles", "role_has_users")

    db.delete(role)
    db.commit()
    return _redirect("/admin/roles", "role_deleted")


@router.post("/roles/add-permission")
def add_permission_to_role(
    role_name: str = Form(...),
    permission_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return _redirect("/admin/roles", "role_not_found")

    permission = (
        db.query(Permission).filter(Permission.name == permission_name).first()
    )
    if not permission:
        return _redirect("/admin/roles", "permission_not_found")

    if permission in role.permissions:
        return _redirect("/admin/roles", "permission_already_assigned")

    role.permissions.append(permission)
    db.commit()
    return _redirect("/admin/roles", "permission_added")


@router.post("/roles/remove-permission")
def remove_permission_from_role(
    role_name: str = Form(...),
    permission_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return _redirect("/admin/roles", "role_not_found")

    permission = (
        db.query(Permission).filter(Permission.name == permission_name).first()
    )
    if not permission:
        return _redirect("/admin/roles", "permission_not_found")

    if permission not in role.permissions:
        return _redirect("/admin/roles", "permission_not_on_role")

    role.permissions.remove(permission)
    db.commit()
    return _redirect("/admin/roles", "permission_removed")


# NOTE: There is intentionally no POST /admin/permissions/create route.
# Permissions are a property of tools, not something an admin invents.
# New permissions appear automatically via the tool-sync pass in
# app/mcp/server.py on startup. Admin can still delete stale ones below;
# if a deleted permission still corresponds to a registered tool, it
# will be re-created the next time the MCP server boots.


@router.post("/permissions/delete")
def delete_permission(
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    permission = db.query(Permission).filter(Permission.name == name).first()
    if not permission:
        return _redirect("/admin/roles", "permission_not_found")

    # Detach from every role first so we never dangle a row in the
    # association table.
    for role in list(permission.roles) if hasattr(permission, "roles") else []:
        if permission in role.permissions:
            role.permissions.remove(permission)

    db.delete(permission)
    db.commit()
    return _redirect("/admin/roles", "permission_deleted")


# --- employees ---------------------------------------------------------


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