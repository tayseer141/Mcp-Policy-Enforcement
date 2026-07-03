from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.models.rbac_models import Role, User, Permission, RolePermission
from app.models.customer_model import Customer
from app.models.policy_model import Policy
from app.policy.catalog import POLICY_TYPES


# Demo credentials for the seeded users. Documented in the README --
# real deployments must change these (and SECRET_KEY) via the admin API.
SEED_PASSWORDS = {
    "admin_user": "admin123",
    "manager_user": "manager123",
    "employee": "employee123",
}

# Fallback for users created before password support existed.
DEFAULT_MIGRATION_PASSWORD = "changeme123"


def _ensure_password_column(db: Session):
    """
    In-place, idempotent migration: add users.password_hash if the table
    predates password support (works on both SQLite and Postgres), then
    backfill any user that has no hash yet with a known demo password.
    """
    bind = db.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("users")}
    if "password_hash" not in columns:
        db.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
        db.commit()

    for user in db.query(User).filter(User.password_hash.is_(None)).all():
        plain = SEED_PASSWORDS.get(user.username, DEFAULT_MIGRATION_PASSWORD)
        user.password_hash = hash_password(plain)
    db.commit()


def seed_policies(db: Session):
    """
    Seed one policy per catalog type using the built-in defaults, so a
    fresh database enforces exactly what the old hardcoded constants did
    (delete limit = 1, credit-limit raise cap = 20%). Idempotent.
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

    # Same for password support: migrate + backfill existing databases.
    _ensure_password_column(db)

    if db.query(Role).first():
        return

    admin_role = Role(name="admin")
    manager_role = Role(name="Manager")
    employee_role = Role(name="Employee")

    db.add_all([admin_role, manager_role, employee_role])
    db.commit()

    db.refresh(admin_role)
    db.refresh(manager_role)
    db.refresh(employee_role)

    permissions = [
        Permission(name="get_customers"),
        Permission(name="get_customer_by_id"),
        Permission(name="update_credit_limit"),
        Permission(name="delete_customer"),
        Permission(name="add_customer"),
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

        # The Employee role is read-only over customers (replaces the old Guest role).
        RolePermission(role_id=employee_role.id, permission_id=permissions[0].id),
        RolePermission(role_id=employee_role.id, permission_id=permissions[1].id),
    ]
    db.add_all(role_permissions)

    users = [
        User(
            username="admin_user",
            role_id=admin_role.id,
            password_hash=hash_password(SEED_PASSWORDS["admin_user"]),
        ),
        User(
            username="manager_user",
            role_id=manager_role.id,
            password_hash=hash_password(SEED_PASSWORDS["manager_user"]),
        ),
        User(
            username="employee",
            role_id=employee_role.id,
            password_hash=hash_password(SEED_PASSWORDS["employee"]),
        ),
    ]
    db.add_all(users)

    customers = [
        Customer(name="Ali Hasan", company="Acme Corp", credit_limit=7000),
        Customer(name="Sara Khalil", company="Globex", credit_limit=6500),
        Customer(name="Omar Nasser", company="Initech", credit_limit=8000),
    ]
    db.add_all(customers)

    db.commit()