from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.mcp.server import mcp_server
from app.mcp.models import ToolCallRequest

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/tools")
def list_mcp_tools():
    return {
        "tools": [tool.model_dump() for tool in mcp_server.list_tools()]
    }


@router.post("/call")
def call_mcp_tool(
    payload: ToolCallRequest,
    db: Session = Depends(get_db),
):
    response = mcp_server.call_tool(db, payload)
    return response.model_dump()