from typing import Any, Dict
from sqlalchemy.orm import Session

from app.policy.models import AuthorizationDecision
from app.policy.bindings import iter_handlers_for_tool
from app.policy.intent import check_intent_alignment
from app.models.rbac_models import User


# Reserved key used to smuggle the original user prompt into the argument
# bag so the policy engine can run the intent alignment stage. This key is
# stripped from the LLM's visible tool schema, so the model never sees it.
RAW_PROMPT_ARG_KEY = "__raw_prompt__"


def check_rbac(
    db: Session, user: User, required_permission: str
) -> AuthorizationDecision:
    """
    Stage 1: Role-Based Access Control.
    Checks if the user's role has the required permission assigned.
    """
    role = user.role
    if not role:
        return AuthorizationDecision(
            allowed=False,
            stage="rbac",
            reason="User has no assigned role.",
        )

    permissions = {perm.name for perm in role.permissions}

    if required_permission not in permissions:
        return AuthorizationDecision(
            allowed=False,
            stage="rbac",
            reason=f"Role '{role.name}' lacks permission '{required_permission}'.",
        )

    return AuthorizationDecision(
        allowed=True,
        stage="rbac",
        reason=f"RBAC check passed for permission '{required_permission}'.",
    )


def check_intent(
    tool_name: str, arguments: Dict[str, Any]
) -> AuthorizationDecision:
    """
    Stage 2: Intent Alignment.
    Only enforced when a raw_prompt is present in the arguments. Direct API
    calls (no natural language in the loop) skip this check.
    """
    raw_prompt = arguments.get(RAW_PROMPT_ARG_KEY)
    if not raw_prompt:
        return AuthorizationDecision(
            allowed=True,
            stage="intent",
            reason="No raw prompt provided; intent alignment skipped.",
        )

    aligned, reason, _extracted, _tool_tags = check_intent_alignment(
        tool_name, raw_prompt
    )

    return AuthorizationDecision(
        allowed=aligned,
        stage="intent",
        reason=reason,
        matched_policy="intent_alignment",
    )


def evaluate_policies(
    db,
    user: User,
    tool_name: str,
    arguments: Dict[str, Any],
) -> AuthorizationDecision:
    """
    Stage 3: Business-logic Policy Evaluation.
    Contextual checks based on tool arguments.

    Dispatch is fully declarative: the policy catalog says which policy
    types guard this tool, and app.policy.bindings supplies one handler
    per type. Adding a new guarded tool therefore requires a catalog
    entry and a handler -- this engine never changes.

    Thresholds are not hardcoded -- each handler reads the active value
    from the policies table via app.policy.store on every request, so
    admin changes (dashboard / NL authoring flow) take effect
    immediately. A policy an admin has disabled is simply not enforced.
    The first denying handler wins (fail-closed ordering).
    """
    for _policy_type, handler in iter_handlers_for_tool(tool_name):
        decision = handler(db, arguments)
        if not decision.allowed:
            return decision

    return AuthorizationDecision(
        allowed=True,
        stage="policy",
        reason="No policy blocked the request.",
    )


def authorize_tool_request(
    db: Session,
    user: User,
    tool_name: str,
    required_permission: str,
    arguments: Dict[str, Any],
) -> AuthorizationDecision:
    """
    Policy Decision Point.
    Runs the three stages in order: RBAC -> Intent -> Policy.

    Every final decision (allow or deny, any stage) is persisted to the
    audit log so the admin dashboard can reconstruct the security story.
    """
    decision = _decide(db, user, tool_name, required_permission, arguments)

    # Best-effort audit logging. Imported locally to avoid any circular
    # import risk between the engine and the audit service.
    try:
        from app.services.audit_service import record_decision

        record_decision(
            db=db,
            username=user.username,
            tool_name=tool_name,
            arguments=arguments,
            decision=decision,
            raw_prompt=arguments.get(RAW_PROMPT_ARG_KEY),
        )
    except Exception:  # pragma: no cover - never let audit failures block auth
        pass

    return decision


def _decide(
    db: Session,
    user: User,
    tool_name: str,
    required_permission: str,
    arguments: Dict[str, Any],
) -> AuthorizationDecision:
    """Pure decision pipeline, separated so the audit wrapper stays tidy."""
    rbac_decision = check_rbac(db, user, required_permission)
    if not rbac_decision.allowed:
        return rbac_decision

    intent_decision = check_intent(tool_name, arguments)
    if not intent_decision.allowed:
        return intent_decision

    policy_decision = evaluate_policies(db, user, tool_name, arguments)
    if not policy_decision.allowed:
        return policy_decision

    return AuthorizationDecision(
        allowed=True,
        stage="policy",
        reason="Authorization passed: RBAC, intent and policy checks succeeded.",
    )