from sqlalchemy.orm import Session
from app.models.rbac_models import Role, User, Permission, RolePermission
from app.models.employee_model import Employee
from app.models.policy_model import Policy
from app.policy.catalog import POLICY_TYPES


def seed_policies(db: Session):
    """
    Seed one policy per catalog type using the built-in defaults, so a
    fresh database enforces exactly what the old hardcoded constants did
    (delete limit = 1, salary raise cap = 20%). Idempotent.
    """
    if db.query(Policy).first():
        return

    for ptype, spec in POLICY_TYPES.items():
        db.add(
            Policy(
                name=ptype,
                policy_type=ptype,
                tool_name=spec["tool_name"],
                threshold=float(spec["default"]),
                enabled=True,
                description=f"{spec['label']} (seeded default).",
                created_by="system",
                origin="seed",
            )
        )
    db.commit()


def seed_data(db: Session):
    # Always make sure default policies exist, even on an already-seeded
    # RBAC database (this is a new table added after initial release).
    seed_policies(db)

    if db.query(Role).first():
        return

    admin_role = Role(name="admin")
    manager_role = Role(name="Manager")
    guest_role = Role(name="Guest")

    db.add_all([admin_role, manager_role, guest_role])
    db.commit()

    db.refresh(admin_role)
    db.refresh(manager_role)
    db.refresh(guest_role)

    permissions = [
        Permission(name="get_employees"),
        Permission(name="get_employee_by_id"),
        Permission(name="update_salary"),
        Permission(name="delete_employee"),
        Permission(name="add_employee"),
    ]
    db.add_all(permissions)
    db.commit()

    for permission in permissions:
        db.refresh(permission)

    role_permissions = [
        RolePermission(role_id=admin_role.id, permission_id=permissions[0].id),
        RolePermission(role_id=admin_role.id, permission_id=permissions[1].id),
        RolePermission(role_id=admin_role.id, permission_id=permissions[2].id),
        RolePermission(role_id=admin_role.id, permission_id=permissions[3].id),
        RolePermission(role_id=admin_role.id, permission_id=permissions[4].id),

        RolePermission(role_id=manager_role.id, permission_id=permissions[0].id),
        RolePermission(role_id=manager_role.id, permission_id=permissions[1].id),
        RolePermission(role_id=manager_role.id, permission_id=permissions[2].id),
        RolePermission(role_id=manager_role.id, permission_id=permissions[4].id),

        RolePermission(role_id=guest_role.id, permission_id=permissions[0].id),
        RolePermission(role_id=guest_role.id, permission_id=permissions[1].id),
    ]
    db.add_all(role_permissions)

    users = [
        User(username="admin_user", role_id=admin_role.id),
        User(username="manager_user", role_id=manager_role.id),
        User(username="guest_user", role_id=guest_role.id),
    ]
    db.add_all(users)

    employees = [
        Employee(name="Ali Hasan", department="IT", salary=7000),
        Employee(name="Sara Khalil", department="HR", salary=6500),
        Employee(name="Omar Nasser", department="Finance", salary=8000),
    ]
    db.add_all(employees)

    db.commit()