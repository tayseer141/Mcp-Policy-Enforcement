from typing import Optional, Literal
from pydantic import BaseModel


class AuthorizationDecision(BaseModel):
    """
    The core security model for the project.
    Determines if a tool execution is permitted based on:
      - RBAC (role has the permission)
      - Intent alignment (tool matches what the user asked for)
      - Business-logic policies (argument-level rules)
    """
    allowed: bool
    stage: Literal["rbac", "intent", "policy", "validation"]
    reason: str
    matched_policy: Optional[str] = None