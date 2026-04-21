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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mcp-server")


# --- Bootstrap DB schema + seed (idempotent) ---
# Runs at module load in whichever container imports this module.
# seed_data() guards against re-seeding, so this is safe to run twice.
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


@mcp.tool()
def health_check(username: str) -> dict:
    """Check if the MCP server and DB are responsive."""
    return {
        "status": "ok",
        "server": "policy-enforcement-mcp",
        "username": username,
    }


@mcp.tool()
def get_employees(username: str) -> list[dict]:
    """Retrieve all employee records (Requires 'get_employees' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_employees",
            required_permission="get_employees",
            arguments={},
        )
    finally:
        db.close()


@mcp.tool()
def get_employee_by_id(username: str, employee_id: int) -> dict:
    """Retrieve a single employee by ID (Requires 'get_employee_by_id' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_employee_by_id",
            required_permission="get_employee_by_id",
            arguments={"employee_id": employee_id},
        )
    finally:
        db.close()


@mcp.tool()
def update_salary(username: str, employee_id: int, new_salary: int) -> dict:
    """Update an employee's salary. Enforces RBAC and the 20% max raise policy."""
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
        )
    finally:
        db.close()


@mcp.tool()
def delete_employee(
    username: str,
    employee_id: Optional[int] = None,
    employee_ids: Optional[list[int]] = None,
    delete_all: bool = False,
) -> dict:
    """
    Delete one or more employee records.
    Enforces RBAC and the mass-deletion policy (max 1 record by default).

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
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Expose the ASGI app.
#
# FastMCP's streamable_http_app() already serves the MCP endpoint at /mcp
# (its default `settings.streamable_http_path`). It also installs its own
# lifespan that runs `session_manager.run()`, which is required for the
# Streamable HTTP transport to work.
#
# DO NOT wrap this in `Starlette(routes=[Mount("/mcp", app=...)])` -- that
# strips the /mcp prefix and ends up serving the real endpoint at /mcp/mcp,
# which was the "404 Not Found" bug you saw in the logs.
# ---------------------------------------------------------------------------
app = mcp.streamable_http_app()