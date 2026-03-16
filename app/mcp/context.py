from app.mcp.models import MCPContext


def build_mcp_context(username: str, raw_prompt: str, request_id: str | None = None):
    return MCPContext(
        username=username,
        raw_prompt=raw_prompt,
        request_id=request_id,
        metadata={}
    )