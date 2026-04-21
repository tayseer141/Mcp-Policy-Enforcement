import asyncio
import json
import os
from typing import Any, Tuple

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# Allow override via env so the same code runs locally and in docker-compose.
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000/mcp")

# Must match the sentinel in app/services/local_tool_executor.py
POLICY_DENIED_KEY = "__policy_denied__"

# Status tags returned by _call_mcp_tool_async. We decide the exception type
# OUTSIDE the MCP/async context to avoid TaskGroup exception-wrapping.
STATUS_OK = "ok"
STATUS_DENIED = "denied"
STATUS_ERROR = "error"


def _extract_text(result) -> str:
    """Concatenate all text blocks from a CallToolResult into one string."""
    parts: list[str] = []
    for block in (result.content or []):
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def _parse_result(result) -> Any:
    """Return the most useful Python object from a CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP sometimes wraps non-object results under a "result" key.
        if (
            isinstance(structured, dict)
            and set(structured.keys()) == {"result"}
        ):
            return structured["result"]
        return structured

    text = _extract_text(result)
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _is_policy_denial(payload: Any) -> bool:
    """True if the tool returned a structured policy-denial record."""
    return isinstance(payload, dict) and payload.get(POLICY_DENIED_KEY) is True


async def _call_mcp_tool_async(
    tool_name: str, arguments: dict[str, Any]
) -> Tuple[str, Any]:
    """
    Open an MCP session, call the tool, and return a (status, payload) tuple.

    We deliberately DO NOT raise from inside the async context. The MCP client
    wraps its stream in an anyio TaskGroup, and any exception raised inside
    that group gets re-packaged as a BaseExceptionGroup on its way out, which
    hides the real type (PermissionError becomes "unhandled errors in a
    TaskGroup"). Returning a tagged tuple and letting the synchronous wrapper
    decide how to raise keeps the exception type intact.
    """
    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            if result.isError:
                return STATUS_ERROR, _extract_text(result) or "MCP tool call failed"

            payload = _parse_result(result)

            if _is_policy_denial(payload):
                reason = payload.get("reason", "Policy denied the request.")
                return STATUS_DENIED, reason

            return STATUS_OK, payload


def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """
    Synchronous wrapper for calling the MCP server from the rest of the app.

    Raises:
        PermissionError: server reported a policy/RBAC denial.
        RuntimeError:    any other tool execution error.
    """
    status, data = asyncio.run(_call_mcp_tool_async(tool_name, arguments))

    if status == STATUS_DENIED:
        raise PermissionError(data)
    if status == STATUS_ERROR:
        raise RuntimeError(data)
    return data