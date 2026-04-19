from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class MCPContext(BaseModel):
    username: str
    raw_prompt: str
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    required_permission: str
    category: str = "general"
    risk_level: str = "medium"


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    context: MCPContext


class AuthorizationDecision(BaseModel):
    allowed: bool
    stage: Literal["rbac", "policy", "validation"]
    reason: str
    matched_policy: Optional[str] = None

class ToolCallResponse(BaseModel):
    success: bool
    tool_name: str
    result: Any = None
    error: Optional[str] = None
    authorization: AuthorizationDecision