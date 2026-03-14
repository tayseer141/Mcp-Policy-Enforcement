from sqlalchemy.orm import Session
from app.models.rbac_models import User, Role, Permission, RolePermission


def check_permission(db: Session, username: str, permission_name: str) -> bool:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return False

    permission = db.query(Permission).filter(Permission.name == permission_name).first()
    if not permission:
        return False

    role_permission = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == user.role_id,
            RolePermission.permission_id == permission.id
        )
        .first()
    )

    return role_permission is not None
