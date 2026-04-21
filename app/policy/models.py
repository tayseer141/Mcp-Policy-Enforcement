from typing import Optional, Literal
from pydantic import BaseModel


class AuthorizationDecision(BaseModel):
    """
    The core security model for the project.
    Determines if a tool execution is permitted based on
    RBAC and Business Logic (Policy) checks.
    """
    allowed: bool
    stage: Literal["rbac", "policy", "validation"]
    reason: str
    matched_policy: Optional[str] = None