import logging
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.db.seed import seed_data
from app.services.local_tool_executor import execute_tool_locally

# Force SQLAlchemy to register all model classes on the Base metadata
# so create_all() sees every table.
import app.models.rbac_models  # noqa: F401
import app.models.employee_model  # noqa: F401
import app.models.audit_model  # noqa: F401  (admin dashboard audit trail)
import app.models.policy_model  # noqa: F401  (admin-managed business policies)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mcp-server")


# --- Bootstrap DB schema + seed (idempotent) ---
logger.info("Bootstrapping database (create_all + seed)...")
Base.metadata.create_all(bind=engine)
_db = SessionLocal()
try:
    seed_data(_db)
finally:
    _db.close()
logger.info("Database bootstrap complete.")


# --- MCP server definition ---
mcp = FastMCP("policy-enforcement-mcp", json_response=True)


# NOTE on the `raw_prompt` parameter:
# Every tool accepts an optional `raw_prompt` string. It's the original
# natural-language request the user typed, injected by the web gateway so
# the policy engine can run the intent-alignment stage server-side. This
# parameter is stripped from the tool schema exposed to the LLM, so the
# model never sees it or invents a value.


@mcp.tool()
def health_check(username: str, raw_prompt: str = "") -> dict:
    """Check if the MCP server and DB are responsive."""
    return {
        "status": "ok",
        "server": "policy-enforcement-mcp",
        "username": username,
    }


@mcp.tool()
def get_employees(username: str, raw_prompt: str = "") -> list[dict]:
    """Retrieve all employee records (Requires 'get_employees' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_employees",
            required_permission="get_employees",
            arguments={},
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def get_employee_by_id(
    username: str, employee_id: int, raw_prompt: str = ""
) -> dict:
    """Retrieve a single employee by ID (Requires 'get_employee_by_id' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_employee_by_id",
            required_permission="get_employee_by_id",
            arguments={"employee_id": employee_id},
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def update_salary(
    username: str,
    employee_id: int,
    new_salary: int,
    raw_prompt: str = "",
) -> dict:
    """Update an employee's salary. Enforces RBAC, intent alignment, and the admin-configurable max salary-raise policy."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="update_salary",
            required_permission="update_salary",
            arguments={
                "employee_id": employee_id,
                "new_salary": new_salary,
            },
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def delete_employee(
    username: str,
    employee_id: Optional[int] = None,
    employee_ids: Optional[list[int]] = None,
    delete_all: bool = False,
    raw_prompt: str = "",
) -> dict:
    """
    Delete one or more employee records.
    Enforces RBAC, intent alignment, and the mass-deletion policy.

    Provide exactly one of: employee_id (single), employee_ids (list),
    or delete_all=True (will be blocked by the policy engine).
    """
    arguments: dict = {}
    if employee_id is not None:
        arguments["employee_id"] = employee_id
    if employee_ids is not None:
        arguments["employee_ids"] = employee_ids
    if delete_all:
        arguments["delete_all"] = True

    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="delete_employee",
            required_permission="delete_employee",
            arguments=arguments,
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def add_employee(
    username: str,
    name: str,
    department: str,
    salary: int,
    raw_prompt: str = "",
) -> dict:
    """Create a new employee record. Enforces RBAC, intent alignment, and the admin-configurable max starting-salary policy."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="add_employee",
            required_permission="add_employee",
            arguments={
                "name": name,
                "department": department,
                "salary": salary,
            },
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


# --- Auto-sync permissions from registered tools -----------------------
# Permissions in this system are a property of tools, not something an
# admin invents. Every @mcp.tool()-registered function should have a
# matching Permission row so the RBAC engine can grant it to a role.
# We scan the registry on boot and upsert anything missing. Safe to run
# on every start: idempotent, cheap, and self-healing if a permission
# gets deleted.

def _sync_permissions_from_tools(db, tool_names) -> int:
    from app.models.rbac_models import Permission

    existing = {p.name for p in db.query(Permission).all()}
    created = 0
    for name in tool_names:
        if name in existing:
            continue
        db.add(Permission(name=name))
        created += 1
    if created:
        db.commit()
    return created


logger.info("Auto-syncing permissions from registered MCP tools...")
_db = SessionLocal()
try:
    tool_names = list(mcp._tool_manager._tools.keys())
    added = _sync_permissions_from_tools(_db, tool_names)
    if added:
        logger.info(f"Created {added} missing permission row(s): {tool_names}")
    else:
        logger.info(f"All {len(tool_names)} tool permissions already present.")
finally:
    _db.close()


# Expose the ASGI app. FastMCP serves the MCP endpoint at /mcp by default.
app = mcp.streamable_http_app()