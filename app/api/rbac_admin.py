from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.rbac_models import Role, User, Permission, RolePermission

router = APIRouter(prefix="/admin/rbac", tags=["admin-rbac"])


# -------------------------
# Request Schemas
# -------------------------

class RoleCreate(BaseModel):
    name: str


class PermissionCreate(BaseModel):
    name: str


class UserCreate(BaseModel):
    username: str
    role_name: str


class AssignPermissionRequest(BaseModel):
    role_name: str
    permission_name: str


class RemovePermissionRequest(BaseModel):
    role_name: str
    permission_name: str


# -------------------------
# Admin Guard
# -------------------------

def require_admin(db: Session, x_username: str | None):
    if not x_username:
        raise HTTPException(status_code=401, detail="Missing x-username header")

    user = db.query(User).filter(User.username == x_username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.role or user.role.name != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return user


# -------------------------
# Endpoints
# -------------------------

@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    roles = db.query(Role).all()
    result = []

    for role in roles:
        role_permissions = (
            db.query(Permission.name)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .filter(RolePermission.role_id == role.id)
            .all()
        )

        result.append(
            {
                "id": role.id,
                "name": role.name,
                "permissions": [p.name for p in role_permissions],
            }
        )

    return {"roles": result}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    users = db.query(User).all()
    return {
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "role": user.role.name if user.role else None,
            }
            for user in users
        ]
    }


@router.post("/roles")
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    existing = db.query(Role).filter(Role.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role already exists")

    role = Role(name=payload.name)
    db.add(role)
    db.commit()
    db.refresh(role)

    return {
        "message": "Role created successfully",
        "role": {
            "id": role.id,
            "name": role.name,
        },
    }


@router.post("/permissions")
def create_permission(
    payload: PermissionCreate,
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    existing = db.query(Permission).filter(Permission.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Permission already exists")

    permission = Permission(name=payload.name)
    db.add(permission)
    db.commit()
    db.refresh(permission)

    return {
        "message": "Permission created successfully",
        "permission": {
            "id": permission.id,
            "name": permission.name,
        },
    }


@router.post("/users")
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    user = User(username=payload.username, role_id=role.id)
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message": "User created successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": role.name,
        },
    }


@router.post("/assign-permission")
def assign_permission_to_role(
    payload: AssignPermissionRequest,
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    permission = db.query(Permission).filter(Permission.name == payload.permission_name).first()
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")

    existing_link = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
        .first()
    )

    if existing_link:
        raise HTTPException(status_code=400, detail="Permission already assigned to role")

    link = RolePermission(role_id=role.id, permission_id=permission.id)
    db.add(link)
    db.commit()

    return {
        "message": "Permission assigned successfully",
        "role": role.name,
        "permission": permission.name,
    }


@router.delete("/remove-permission")
def remove_permission_from_role(
    payload: RemovePermissionRequest,
    db: Session = Depends(get_db),
    x_username: str | None = Header(default=None),
):
    require_admin(db, x_username)

    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    permission = db.query(Permission).filter(Permission.name == payload.permission_name).first()
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")

    link = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=404, detail="Permission is not assigned to this role")

    db.delete(link)
    db.commit()

    return {
        "message": "Permission removed successfully",
        "role": role.name,
        "permission": permission.name,
    }