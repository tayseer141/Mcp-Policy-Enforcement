from sqlalchemy.orm import Session

from app.models.rbac_models import User
from app.services.mcp_client_service import call_mcp_tool


def get_user_or_raise(db: Session, username: str) -> User:
    """
    Identity resolver for the web/API side.
    Ensures the user exists locally before forwarding to the MCP server
    (fast fail + clearer error than going over the wire).
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError(f"User '{username}' not found")
    return user


def run_tool_for_user(
    db: Session,
    username: str,
    tool_name: str,
    required_permission: str,  # kept for backward-compat; MCP server decides
    arguments: dict,
    raw_prompt: str = "",
):
    """
    Web-side orchestration path.

    Flow:
    1. Verify the user exists locally.
    2. Inject username (identity) and raw_prompt (intent signal) into
       the tool arguments.
    3. Forward the request to the real MCP server.
    4. The MCP server runs RBAC + intent + policy enforcement and execution.

    Raises:
        ValueError:      unknown user (local check).
        PermissionError: MCP server denied the call (RBAC / intent / policy).
        RuntimeError:    any other execution error reported by the server.
    """
    get_user_or_raise(db, username)

    mcp_arguments = dict(arguments)
    mcp_arguments["username"] = username
    if raw_prompt:
        mcp_arguments["raw_prompt"] = raw_prompt

    return call_mcp_tool(tool_name, mcp_arguments)