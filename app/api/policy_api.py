"""
Policy admin JSON API.

The control-plane surface for business-logic policies. Mirrors
app/api/admin_api.py exactly: every endpoint is guarded by `require_admin`
(cookie session), GETs return resource models, mutations return
ActionResponse, and failures raise the {"code","message"} envelope.

Natural-language flow (two explicit steps, never one):
    1. POST /policies/draft  -> interpret NL into a *structured draft*.
                                 Nothing is saved. The admin reviews it.
    2. POST /policies        -> confirm: persist the structured policy.

Endpoints
---------
GET    /api/v1/admin/policies              list policies
GET    /api/v1/admin/policy-types          catalog of enforceable types
POST   /api/v1/admin/policies/draft        NL text -> structured draft
POST   /api/v1/admin/policies              create from confirmed draft
PATCH  /api/v1/admin/policies/{id}         edit threshold / enabled / desc
DELETE /api/v1/admin/policies/{id}         delete a policy
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.admin import require_admin
from app.db.deps import get_db
from app.models.policy_model import Policy
from app.models.rbac_models import User
from app.policy.catalog import (
    POLICY_TYPES,
    coerce_threshold,
    is_known_type,
    tool_for_type,
)
from app.schemas.admin import ActionResponse
from app.schemas.policy import (
    CreatePolicyRequest,
    DraftRequest,
    PolicyDraftResponse,
    PolicyPublic,
    PolicyTypePublic,
    UpdatePolicyRequest,
)
from app.services.policy_authoring_service import draft_policy_from_text


router = APIRouter(prefix="/api/v1/admin", tags=["policy-api"])


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _serialize_policy(p: Policy) -> PolicyPublic:
    return PolicyPublic(
        id=p.id,
        name=p.name,
        policy_type=p.policy_type,
        tool_name=p.tool_name,
        threshold=p.threshold,
        enabled=p.enabled,
        description=p.description or "",
        created_by=p.created_by or "",
        origin=p.origin or "manual",
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


# =====================================================================
# Catalog
# =====================================================================

@router.get("/policy-types", response_model=list[PolicyTypePublic])
def list_policy_types(
    _admin: User = Depends(require_admin),
) -> list[PolicyTypePublic]:
    return [
        PolicyTypePublic(
            policy_type=ptype,
            tool_name=spec["tool_name"],
            label=spec["label"],
            unit=spec["unit"],
            value_kind=spec["value_kind"],
            default=float(spec["default"]),
            help=spec["help"],
        )
        for ptype, spec in POLICY_TYPES.items()
    ]


# =====================================================================
# List
# =====================================================================

@router.get("/policies", response_model=list[PolicyPublic])
def list_policies(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[PolicyPublic]:
    rows = db.query(Policy).order_by(Policy.tool_name.asc(), Policy.name.asc()).all()
    return [_serialize_policy(p) for p in rows]


# =====================================================================
# Step 1: NL -> structured draft (no persistence)
# =====================================================================

@router.post("/policies/draft", response_model=PolicyDraftResponse)
def draft_policy(
    payload: DraftRequest,
    _admin: User = Depends(require_admin),
) -> PolicyDraftResponse:
    draft = draft_policy_from_text(payload.text)
    return PolicyDraftResponse(**draft.to_dict())


# =====================================================================
# Step 2: confirm -> create
# =====================================================================

@router.post(
    "/policies",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_policy(
    payload: CreatePolicyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ActionResponse:
    policy_type = payload.policy_type.strip()

    if not is_known_type(policy_type):
        raise _api_error(
            400,
            "unknown_policy_type",
            "That policy type is not one the engine can enforce.",
        )

    try:
        threshold = coerce_threshold(policy_type, payload.threshold)
    except ValueError as e:
        raise _api_error(400, "invalid_threshold", str(e))

    name = (payload.name or policy_type).strip()
    origin = payload.origin if payload.origin in ("manual", "nl", "seed") else "manual"

    # We keep one definition per policy type so the engine is unambiguous.
    # But that means confirming a policy whose type already exists (e.g.
    # changing the seeded delete-limit from 1 to 3) is an UPDATE, not an
    # error. Upsert by type so the natural-language path "just works"
    # instead of dead-ending on a 409.
    existing_same_type = (
        db.query(Policy).filter(Policy.policy_type == policy_type).first()
    )
    if existing_same_type:
        old = existing_same_type.threshold
        existing_same_type.threshold = threshold
        existing_same_type.enabled = bool(payload.enabled)
        if payload.description:
            existing_same_type.description = payload.description.strip()
        existing_same_type.origin = origin
        existing_same_type.created_by = admin.username
        db.commit()
        return ActionResponse(
            code="policy_updated",
            message=(
                f"Updated the existing “{existing_same_type.name}” policy "
                f"(was {old:g}, now {threshold:g})."
            ),
        )

    if db.query(Policy).filter(Policy.name == name).first():
        raise _api_error(
            409,
            "policy_name_exists",
            "A policy with that name already exists.",
        )

    policy = Policy(
        name=name,
        policy_type=policy_type,
        tool_name=tool_for_type(policy_type),
        threshold=threshold,
        enabled=bool(payload.enabled),
        description=(payload.description or "").strip(),
        created_by=admin.username,
        origin=origin,
    )
    db.add(policy)
    db.commit()
    return ActionResponse(code="policy_created", message="Policy created and active.")


# =====================================================================
# Edit
# =====================================================================

@router.patch("/policies/{policy_id}", response_model=ActionResponse)
def update_policy(
    policy_id: int,
    payload: UpdatePolicyRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise _api_error(404, "policy_not_found", "That policy was not found.")

    if payload.threshold is not None:
        try:
            policy.threshold = coerce_threshold(policy.policy_type, payload.threshold)
        except ValueError as e:
            raise _api_error(400, "invalid_threshold", str(e))

    if payload.enabled is not None:
        policy.enabled = bool(payload.enabled)

    if payload.description is not None:
        policy.description = payload.description.strip()

    db.commit()
    return ActionResponse(code="policy_updated", message="Policy updated.")


# =====================================================================
# Delete
# =====================================================================

@router.delete("/policies/{policy_id}", response_model=ActionResponse)
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActionResponse:
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise _api_error(404, "policy_not_found", "That policy was not found.")

    db.delete(policy)
    db.commit()
    return ActionResponse(code="policy_deleted", message="Policy deleted.")