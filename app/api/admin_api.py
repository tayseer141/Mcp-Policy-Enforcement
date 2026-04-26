"""
Admin JSON API.

This module is the platform-grade admin surface. The HTML admin pages
(in app/api/admin.py) and any future external client speak to the
system through these endpoints. The HTML pages are now thin clients of
this API — see app/templates/admin/users.html and roles.html.

Auth model
----------
Every endpoint here is guarded by `require_admin` (cookie-based admin
session), reusing the same dependency the HTML routes use. Browser
fetch() calls send the cookie automatically because the API is on the
same origin.

Conventions
-----------
- GET endpoints return resource models from app.schemas.admin.
- Mutation endpoints return ActionResponse with a stable `code` and
  human-friendly `message`.
- Failures raise HTTPException with detail = {"code": ..., "message": ...}
  so clients can localise on `code` while still rendering `message`
  by default.
- Status codes are used semantically:
    400 - validation
    403 - forbidden by self-protection rules
    404 - resource not found
    409 - conflict (already exists, has dependants, etc.)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.admin import (
    ADMIN_ROLE_NAME,
    _tool_backed_permission_names,
    require_admin,
)
from app.db.deps import get_db
from app.models.rbac_models import Permission, Role, User
from app.schemas.admin import (
    ActionResponse,
    AddPermissionRequest,
    AssignRoleRequest,
    CreateRoleRequest,
    CreateUserRequest,
    PermissionPublic,
    RolePublic,
    UserPublic,
)


router = APIRouter(prefix="/api/v1/admin", tags=["admin-api"])


# ---------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------

def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


# ---------------------------------------------------------------------
# Resource serializers (ORM -> Pydantic)
# ---------------------------------------------------------------------

def _serialize_user(u: User) -> UserPublic:
    return UserPublic(
        username=u.username,
        role=u.role.name if u.role else None,
    )


def _serialize_role(r: Role) -> RolePublic:
    return RolePublic(
        name=r.name,
        permissions=[p.name for p in r.permissions],
        users=[u.username for u in r.users] if hasattr(r, "users") else [],
        is_system=(r.name == ADMIN_ROLE_NAME),
    )


def _serialize_permission(p: Permission, tool_backed: set[str], roles: list[Role]) -> PermissionPublic:
    used_in = [r.name for r in roles if p in r.permissions]
    return PermissionPublic(
        name=p.name,
        is_tool_backed=(p.name in tool_backed),
        used_in_roles=used_in,
    )


# =====================================================================
# Users
# =====================================================================

@router.get("/users", response_model=list[UserPublic])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[UserPublic]:
    rows = db.query(User).order_by(User.username.asc()).all()
    return [_serialize_user(u) for u in rows]


@router.post(
    "/users",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    username = payload.username.strip()
    if not username:
        raise _api_error(400, "invalid_username", "Username cannot be empty.")

    if db.query(User).filter(User.username == username).first():
        raise _api_error(409, "user_exists", "A user with that username already exists.")

    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise _api_error(404, "role_not_found", "That role was not found.")

    db.add(User(username=username, role_id=role.id))
    db.commit()
    return ActionResponse(code="user_created", message="User created.")


@router.patch("/users/{username}/role", response_model=ActionResponse)
def assign_role(
    username: str,
    payload: AssignRoleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ActionResponse:
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise _api_error(404, "user_not_found", "That user was not found.")

    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise _api_error(404, "role_not_found", "That role was not found.")

    # Self-protection: prevent the current admin from demoting themselves
    # out of the admin role.
    if target.id == admin.id and role.name != ADMIN_ROLE_NAME:
        raise _api_error(
            403,
            "cannot_demote_self",
            "You cannot demote your own admin account.",
        )

    target.role = role
    db.commit()
    return ActionResponse(code="role_updated", message="Role updated.")


@router.delete("/users/{username}", response_model=ActionResponse)
def delete_user(
    username: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ActionResponse:
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise _api_error(404, "user_not_found", "That user was not found.")

    if target.id == admin.id:
        raise _api_error(
            403,
            "cannot_delete_self",
            "You cannot delete your own admin account.",
        )

    db.delete(target)
    db.commit()
    return ActionResponse(code="user_deleted", message="User deleted.")


# =====================================================================
# Roles
# =====================================================================

@router.get("/roles", response_model=list[RolePublic])
def list_roles(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[RolePublic]:
    rows = db.query(Role).order_by(Role.name.asc()).all()
    return [_serialize_role(r) for r in rows]


@router.post(
    "/roles",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_role(
    payload: CreateRoleRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    name = payload.name.strip()
    if not name:
        raise _api_error(400, "invalid_name", "Name cannot be empty.")

    if db.query(Role).filter(Role.name == name).first():
        raise _api_error(409, "role_exists", "A role with that name already exists.")

    db.add(Role(name=name))
    db.commit()
    return ActionResponse(code="role_created", message="Role created.")


@router.delete("/roles/{name}", response_model=ActionResponse)
def delete_role(
    name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        raise _api_error(404, "role_not_found", "That role was not found.")

    if role.name == ADMIN_ROLE_NAME:
        raise _api_error(
            403,
            "cannot_delete_admin_role",
            "The admin role cannot be deleted.",
        )

    if role.users:
        raise _api_error(
            409,
            "role_has_users",
            "Cannot delete a role that still has users assigned.",
        )

    db.delete(role)
    db.commit()
    return ActionResponse(code="role_deleted", message="Role deleted.")


@router.post(
    "/roles/{name}/permissions",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_permission_to_role(
    name: str,
    payload: AddPermissionRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        raise _api_error(404, "role_not_found", "That role was not found.")

    permission = (
        db.query(Permission).filter(Permission.name == payload.permission_name).first()
    )
    if not permission:
        raise _api_error(404, "permission_not_found", "That permission was not found.")

    if permission in role.permissions:
        raise _api_error(
            409,
            "permission_already_assigned",
            "That permission is already on the role.",
        )

    role.permissions.append(permission)
    db.commit()
    return ActionResponse(code="permission_added", message="Permission attached to role.")


@router.delete(
    "/roles/{name}/permissions/{permission_name}",
    response_model=ActionResponse,
)
def remove_permission_from_role(
    name: str,
    permission_name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        raise _api_error(404, "role_not_found", "That role was not found.")

    permission = (
        db.query(Permission).filter(Permission.name == permission_name).first()
    )
    if not permission:
        raise _api_error(404, "permission_not_found", "That permission was not found.")

    if permission not in role.permissions:
        raise _api_error(
            409,
            "permission_not_on_role",
            "That permission is not currently on the role.",
        )

    role.permissions.remove(permission)
    db.commit()
    return ActionResponse(code="permission_removed", message="Permission removed from role.")


# =====================================================================
# Permissions
# =====================================================================
#
# There is intentionally no POST /permissions — permissions are a
# property of registered tools, not something an admin invents. The
# tool-sync pass in app/mcp/server.py creates them on startup. The only
# write action exposed here is delete.

@router.get("/permissions", response_model=list[PermissionPublic])
def list_permissions(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[PermissionPublic]:
    rows = db.query(Permission).order_by(Permission.name.asc()).all()
    roles = db.query(Role).all()
    tool_backed = _tool_backed_permission_names()
    return [_serialize_permission(p, tool_backed, roles) for p in rows]


@router.delete("/permissions/{name}", response_model=ActionResponse)
def delete_permission(
    name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    permission = db.query(Permission).filter(Permission.name == name).first()
    if not permission:
        raise _api_error(404, "permission_not_found", "That permission was not found.")

    # Detach from every role first so the association table never has
    # dangling rows.
    if hasattr(permission, "roles"):
        for role in list(permission.roles):
            if permission in role.permissions:
                role.permissions.remove(permission)

    db.delete(permission)
    db.commit()
    return ActionResponse(code="permission_deleted", message="Permission deleted.")