from sqlalchemy.orm import Session
from app.models.rbac_models import User
from app.mcp.models import (
    ToolCallRequest,
    ToolCallResponse,
    AuthorizationDecision,
)
from app.mcp.registry import registry
from app.mcp.dispatcher import dispatch_tool
from app.policy.engine import authorize_tool_request


class MCPServer:
    def list_tools(self):
        return registry.list_tools()

    def call_tool(self, db: Session, request: ToolCallRequest) -> ToolCallResponse:
        # 1. Resolve the tool from the registry
        tool = registry.get_tool(request.tool_name)

        if not tool:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error=f"Unknown tool: {request.tool_name}",
                authorization=AuthorizationDecision(
                    allowed=False,
                    stage="validation",
                    reason="Tool is not registered in MCP registry.",
                ),
            )

        # 2. Fetch the user object from the DB
        user = db.query(User).filter(User.username == request.context.username).first()
        if not user:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error="User not found",
                authorization=AuthorizationDecision(
                    allowed=False,
                    stage="rbac",
                    reason=f"User '{request.context.username}' does not exist.",
                ),
            )

        # 3. Perform Multi-Layer Authorization (RBAC + Policy)
        authorization = authorize_tool_request(
            db=db,
            user=user,
            tool_name=request.tool_name,
            required_permission=tool.required_permission,
            arguments=request.arguments,
        )

        if not authorization.allowed:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                result=None,
                error=f"Access denied: {authorization.reason}",
                authorization=authorization,
            )
        # 4. Dispatch Execution
        try:
            result = dispatch_tool(db, request.tool_name, request.arguments)
            return ToolCallResponse(
                success=True,
                tool_name=request.tool_name,
                result=result,
                authorization=authorization,
            )
        except Exception as e:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                error=str(e),
                authorization=authorization, # Still includes the reason it was allowed
            )


mcp_server = MCPServer()