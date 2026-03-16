from sqlalchemy.orm import Session

from app.mcp.models import (
    ToolCallRequest,
    ToolCallResponse,
    AuthorizationDecision,
)
from app.mcp.registry import registry
from app.mcp.dispatcher import dispatch_tool
from app.policy.engine import check_permission


class MCPServer:
    def list_tools(self):
        return registry.list_tools()

    def call_tool(self, db: Session, request: ToolCallRequest) -> ToolCallResponse:
        tool = registry.get_tool(request.tool_name)

        if not tool:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error=f"Unknown tool: {request.tool_name}",
                authorization=AuthorizationDecision(
                    allowed=False,
                    reason="Tool is not registered in MCP registry.",
                ),
            )

        allowed = check_permission(
            db,
            request.context.username,
            tool.required_permission,
        )

        if not allowed:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error="Access denied",
                authorization=AuthorizationDecision(
                    allowed=False,
                    reason=f"User '{request.context.username}' is not allowed to execute '{request.tool_name}'.",
                ),
            )

        try:
            result = dispatch_tool(db, request.tool_name, request.arguments)
            return ToolCallResponse(
                success=True,
                tool_name=request.tool_name,
                result=result,
                authorization=AuthorizationDecision(
                    allowed=True,
                    reason="Permission check passed.",
                ),
            )
        except Exception as e:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error=str(e),
                authorization=AuthorizationDecision(
                    allowed=True,
                    reason="Permission check passed, but execution failed.",
                ),
            )


mcp_server = MCPServer()