from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.mcp.server import mcp  # Changed from mcp_server
from app.services.tool_service import run_tool_for_user

router = APIRouter(prefix="/mcp", tags=["mcp"])

@router.get("/tools")
def list_mcp_tools():
    """
    Lists tools directly from the official MCP server instance.
    """
    # FastMCP tools are accessed via the .tools dictionary or list_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters  # FastMCP uses .parameters for the JSON schema
            } 
            for t in mcp.list_tools()
        ]
    }

@router.post("/call")
def call_mcp_tool(
    username: str,           # Identity must be passed or extracted from a token
    tool_name: str,
    arguments: dict,
    db: Session = Depends(get_db),
):
    """
    The secure entry point for the Web UI to call MCP tools.
    It routes through the tool_service to enforce policies.
    """
    try:
        # We find the required permission by matching the tool name
        # In a more advanced version, this mapping could be dynamic
        result = run_tool_for_user(
            db=db,
            username=username,
            tool_name=tool_name,
            required_permission=tool_name, 
            arguments=arguments
        )
        return {"success": True, "result": result}
    
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")