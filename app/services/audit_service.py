"""
Audit service.

Thin layer around the AuditLog model. Keeping the persistence / query
logic out of the policy engine means the engine stays focused on
decision-making and can be unit-tested without a DB if needed.
"""

import json
import logging
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.audit_model import AuditLog
from app.policy.engine import RAW_PROMPT_ARG_KEY
from app.policy.models import AuthorizationDecision


logger = logging.getLogger("audit")


def _scrub_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove reserved / server-injected keys before persisting."""
    clean = dict(arguments or {})
    clean.pop(RAW_PROMPT_ARG_KEY, None)
    clean.pop("username", None)
    clean.pop("raw_prompt", None)
    return clean


def record_decision(
    db: Session,
    *,
    username: str,
    tool_name: str,
    arguments: dict[str, Any],
    decision: AuthorizationDecision,
    raw_prompt: Optional[str] = None,
) -> None:
    """
    Persist a single authorization decision.

    This is called from the policy engine at the end of every authorize
    call, regardless of whether the decision was allow or deny. Failures
    here are logged but never propagated — losing an audit row should
    not take down a user-facing request.
    """
    try:
        scrubbed = _scrub_arguments(arguments)
        row = AuditLog(
            username=username,
            tool_name=tool_name,
            allowed=decision.allowed,
            stage=decision.stage,
            reason=decision.reason,
            matched_policy=decision.matched_policy,
            arguments_json=json.dumps(scrubbed, ensure_ascii=False),
            raw_prompt=raw_prompt,
        )
        db.add(row)
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to persist audit row: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


# --- Query helpers used by the admin dashboard -------------------------


def list_decisions(
    db: Session,
    *,
    username: Optional[str] = None,
    tool_name: Optional[str] = None,
    stage: Optional[str] = None,
    decision: Optional[str] = None,  # "allow" | "deny" | None
    limit: int = 100,
) -> list[AuditLog]:
    """Return the most recent audit rows matching the given filters."""
    query = db.query(AuditLog)

    if username:
        query = query.filter(AuditLog.username == username)
    if tool_name:
        query = query.filter(AuditLog.tool_name == tool_name)
    if stage:
        query = query.filter(AuditLog.stage == stage)
    if decision == "allow":
        query = query.filter(AuditLog.allowed.is_(True))
    elif decision == "deny":
        query = query.filter(AuditLog.allowed.is_(False))

    return (
        query.order_by(AuditLog.timestamp.desc()).limit(max(1, limit)).all()
    )


def decision_counters(db: Session) -> dict[str, Any]:
    """
    Aggregate counts used by the dashboard overview card.
    Returns total allow/deny plus a breakdown of denies per stage.
    """
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    allows = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.allowed.is_(True))
        .scalar()
        or 0
    )
    denies = total - allows

    stage_rows = (
        db.query(AuditLog.stage, func.count(AuditLog.id))
        .filter(AuditLog.allowed.is_(False))
        .group_by(AuditLog.stage)
        .all()
    )
    deny_by_stage = {stage: count for stage, count in stage_rows}

    return {
        "total": total,
        "allows": allows,
        "denies": denies,
        "deny_by_stage": deny_by_stage,
    }


def distinct_usernames(db: Session) -> list[str]:
    rows = db.query(AuditLog.username).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def distinct_tools(db: Session) -> list[str]:
    rows = db.query(AuditLog.tool_name).distinct().all()
    return sorted({r[0] for r in rows if r[0]})