"""
Pydantic models for the policy admin API (/api/v1/admin/policies/*).

Mirrors the conventions in app/schemas/admin.py: GET endpoints return
resource models, the NL endpoint returns a draft, mutations return
ActionResponse, and errors use the {"code", "message"} envelope.
"""

from typing import Optional

from pydantic import BaseModel, Field


# =====================================================================
# Resource representation
# =====================================================================

class PolicyPublic(BaseModel):
    id: int
    name: str
    policy_type: str
    tool_name: str
    threshold: float
    enabled: bool
    description: str = ""
    created_by: str = ""
    origin: str = "manual"
    created_at: Optional[str] = None


class PolicyTypePublic(BaseModel):
    """A policy type from the catalog, surfaced so the UI can render the
    manual form and validate selections."""

    policy_type: str
    tool_name: str
    label: str
    unit: str
    value_kind: str
    default: float
    help: str


# =====================================================================
# Natural-language draft
# =====================================================================

class DraftRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Plain-language policy instruction.")


class PolicyDraftResponse(BaseModel):
    valid: bool
    source: str
    explanation: str
    policy_type: Optional[str] = None
    tool_name: Optional[str] = None
    threshold: Optional[float] = None
    name: Optional[str] = None
    description: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


# =====================================================================
# Mutations
# =====================================================================

class CreatePolicyRequest(BaseModel):
    """The confirmed, structured policy. This is what the admin submits
    after reviewing a draft (or fills in manually)."""

    policy_type: str = Field(..., min_length=1)
    threshold: float
    name: Optional[str] = None
    description: Optional[str] = ""
    enabled: bool = True
    origin: str = Field(
        default="manual",
        description="Provenance tag: 'manual' or 'nl'.",
    )


class UpdatePolicyRequest(BaseModel):
    threshold: Optional[float] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None