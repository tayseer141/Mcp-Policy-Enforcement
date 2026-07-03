import json
import logging
import secrets as _secrets
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.db.seed import seed_data
from app.services.local_tool_executor import execute_tool_locally

# Force SQLAlchemy to register all model classes on the Base metadata
# so create_all() sees every table.
import app.models.rbac_models  # noqa: F401
import app.models.customer_model  # noqa: F401
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
def get_customers(username: str, raw_prompt: str = "") -> list[dict]:
    """Retrieve all customer records (Requires 'get_customers' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_customers",
            required_permission="get_customers",
            arguments={},
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def get_customer_by_id(
    username: str, customer_id: int, raw_prompt: str = ""
) -> dict:
    """Retrieve a single customer by ID (Requires 'get_customer_by_id' permission)."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="get_customer_by_id",
            required_permission="get_customer_by_id",
            arguments={"customer_id": customer_id},
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def update_credit_limit(
    username: str,
    customer_id: int,
    new_credit_limit: int,
    raw_prompt: str = "",
) -> dict:
    """Update a customer's credit limit. Enforces RBAC, intent alignment, and the admin-configurable max credit-limit-raise policy."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="update_credit_limit",
            required_permission="update_credit_limit",
            arguments={
                "customer_id": customer_id,
                "new_credit_limit": new_credit_limit,
            },
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def delete_customer(
    username: str,
    customer_id: Optional[int] = None,
    customer_ids: Optional[list[int]] = None,
    delete_all: bool = False,
    raw_prompt: str = "",
) -> dict:
    """
    Delete one or more customer records.
    Enforces RBAC, intent alignment, and the mass-deletion policy.

    Provide exactly one of: customer_id (single), customer_ids (list),
    or delete_all=True (will be blocked by the policy engine).
    """
    arguments: dict = {}
    if customer_id is not None:
        arguments["customer_id"] = customer_id
    if customer_ids is not None:
        arguments["customer_ids"] = customer_ids
    if delete_all:
        arguments["delete_all"] = True

    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="delete_customer",
            required_permission="delete_customer",
            arguments=arguments,
            raw_prompt=raw_prompt,
        )
    finally:
        db.close()


@mcp.tool()
def add_customer(
    username: str,
    name: str,
    company: str,
    credit_limit: int,
    raw_prompt: str = "",
) -> dict:
    """Create a new customer record. Enforces RBAC, intent alignment, and the admin-configurable max starting-credit-limit policy."""
    db = SessionLocal()
    try:
        return execute_tool_locally(
            db=db,
            username=username,
            tool_name="add_customer",
            required_permission="add_customer",
            arguments={
                "name": name,
                "company": company,
                "credit_limit": credit_limit,
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


# --- Gateway authentication --------------------------------------------
# The MCP server is the enforcement point, so it must not be callable by
# anyone who can reach its port. Every request must present the shared
# gateway secret; only the web gateway holds it. Comparison is
# constant-time. Fail-closed: no header, wrong header -> 401, no tool
# call, no session.

class GatewayAuthMiddleware:
    """ASGI middleware: reject any HTTP request without the gateway key."""

    HEADER = b"x-mcp-gateway-key"

    def __init__(self, inner_app, expected_key: str):
        self.inner_app = inner_app
        self.expected_key = expected_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            presented = headers.get(self.HEADER, b"").decode("utf-8", "ignore")
            if not _secrets.compare_digest(presented, self.expected_key):
                body = json.dumps(
                    {"error": "unauthorized", "detail": "Missing or invalid gateway key."}
                ).encode()
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.inner_app(scope, receive, send)


# Expose the ASGI app. FastMCP serves the MCP endpoint at /mcp by default;
# the auth wrapper guards every request that reaches it.
app = GatewayAuthMiddleware(mcp.streamable_http_app(), settings.MCP_GATEWAY_KEY)