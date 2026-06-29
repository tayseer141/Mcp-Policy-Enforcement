from typing import Any, Dict
from sqlalchemy.orm import Session

from app.policy.models import AuthorizationDecision
from app.policy.rules import (
    evaluate_delete_limit_policy,
    evaluate_salary_raise_policy,
    evaluate_starting_salary_policy,
)
from app.policy.intent import check_intent_alignment
from app.policy.store import resolve_active_policy
from app.models.customer_model import Customer
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

    Thresholds are no longer hardcoded — they are read from the policies
    table via app.policy.store on every request, so admin changes (made
    through the dashboard / NL authoring flow) take effect immediately.
    A policy that an admin has disabled is simply not enforced here.
    """
    if tool_name == "delete_customer":
        active = resolve_active_policy(db, "max_delete_count", "delete_customer")
        if not active.enforce:
            return AuthorizationDecision(
                allowed=True,
                stage="policy",
                reason="No active delete-limit policy; request allowed.",
            )

        allowed, reason, matched_policy = evaluate_delete_limit_policy(
            tool_name=tool_name,
            arguments=arguments,
            max_delete_count=int(active.threshold),
        )
        return AuthorizationDecision(
            allowed=allowed,
            stage="policy",
            reason=reason,
            matched_policy=active.name or matched_policy,
        )

    if tool_name == "update_credit_limit":
        customer_id = arguments.get("customer_id")
        requested_credit_limit = arguments.get("new_credit_limit")

        if customer_id is None or requested_credit_limit is None:
            return AuthorizationDecision(
                allowed=False,
                stage="validation",
                reason="Credit limit update denied because customer_id or new_credit_limit is missing.",
                matched_policy="max_credit_limit_raise_percent",
            )

        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return AuthorizationDecision(
                allowed=False,
                stage="validation",
                reason="Credit limit update denied because the target customer was not found.",
                matched_policy="max_credit_limit_raise_percent",
            )

        active = resolve_active_policy(
            db, "max_credit_limit_raise_percent", "update_credit_limit"
        )
        if not active.enforce:
            return AuthorizationDecision(
                allowed=True,
                stage="policy",
                reason="No active credit-limit-raise policy; request allowed.",
            )

        allowed, reason, matched_policy = evaluate_salary_raise_policy(
            current_salary=float(customer.credit_limit),
            requested_salary=float(requested_credit_limit),
            max_raise_percent=float(active.threshold),
        )

        return AuthorizationDecision(
            allowed=allowed,
            stage="policy",
            reason=reason,
            matched_policy=active.name or matched_policy,
        )

    if tool_name == "add_customer":
        requested_credit_limit = arguments.get("credit_limit")

        if requested_credit_limit is None:
            return AuthorizationDecision(
                allowed=False,
                stage="validation",
                reason="Add customer denied because the starting credit limit is missing.",
                matched_policy="max_starting_credit_limit",
            )

        active = resolve_active_policy(db, "max_starting_credit_limit", "add_customer")
        if not active.enforce:
            return AuthorizationDecision(
                allowed=True,
                stage="policy",
                reason="No active starting-credit-limit policy; request allowed.",
            )

        allowed, reason, matched_policy = evaluate_starting_salary_policy(
            requested_salary=float(requested_credit_limit),
            max_starting_credit_limit=float(active.threshold),
        )
        return AuthorizationDecision(
            allowed=allowed,
            stage="policy",
            reason=reason,
            matched_policy=active.name or matched_policy,
        )

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