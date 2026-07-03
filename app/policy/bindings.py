"""
Declarative policy-to-tool bindings.

The catalog (app.policy.catalog) declares WHICH policy type guards WHICH
tool. This module declares HOW each policy type is checked, by binding
every catalog `policy_type` to a handler function. The engine dispatches
generically through `iter_handlers_for_tool`, so adding a new guarded
tool means: add a catalog entry + write one handler here. The engine
itself never changes.

Each handler owns the full check for its policy type:
  1. argument validation (deny with stage="validation" on bad input),
  2. resolving the active threshold from the admin-managed policies
     table (via app.policy.store),
  3. delegating the pure numeric comparison to app.policy.rules.

Fail-closed: if the catalog declares a policy type for a tool but no
handler is registered here, the request is denied rather than silently
skipped.
"""

from typing import Any, Callable, Dict, Iterator, Tuple

from sqlalchemy.orm import Session

from app.models.customer_model import Customer
from app.policy.catalog import POLICY_TYPES
from app.policy.models import AuthorizationDecision
from app.policy.rules import (
    evaluate_credit_limit_raise_policy,
    evaluate_delete_limit_policy,
    evaluate_starting_credit_limit_policy,
)
from app.policy.store import resolve_active_policy


PolicyHandler = Callable[[Session, Dict[str, Any]], AuthorizationDecision]


def _allow(reason: str) -> AuthorizationDecision:
    return AuthorizationDecision(allowed=True, stage="policy", reason=reason)


# ---------------------------------------------------------------------
# One handler per catalog policy type
# ---------------------------------------------------------------------

def _check_max_delete_count(
    db: Session, arguments: Dict[str, Any]
) -> AuthorizationDecision:
    active = resolve_active_policy(db, "max_delete_count", "delete_customer")
    if not active.enforce:
        return _allow("No active delete-limit policy; request allowed.")

    allowed, reason, matched_policy = evaluate_delete_limit_policy(
        tool_name="delete_customer",
        arguments=arguments,
        max_delete_count=int(active.threshold),
    )
    return AuthorizationDecision(
        allowed=allowed,
        stage="policy",
        reason=reason,
        matched_policy=active.name or matched_policy,
    )


def _check_max_credit_limit_raise_percent(
    db: Session, arguments: Dict[str, Any]
) -> AuthorizationDecision:
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
        return _allow("No active credit-limit-raise policy; request allowed.")

    allowed, reason, matched_policy = evaluate_credit_limit_raise_policy(
        current_credit_limit=float(customer.credit_limit),
        requested_credit_limit=float(requested_credit_limit),
        max_raise_percent=float(active.threshold),
    )
    return AuthorizationDecision(
        allowed=allowed,
        stage="policy",
        reason=reason,
        matched_policy=active.name or matched_policy,
    )


def _check_max_starting_credit_limit(
    db: Session, arguments: Dict[str, Any]
) -> AuthorizationDecision:
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
        return _allow("No active starting-credit-limit policy; request allowed.")

    allowed, reason, matched_policy = evaluate_starting_credit_limit_policy(
        requested_credit_limit=float(requested_credit_limit),
        max_starting_credit_limit=float(active.threshold),
    )
    return AuthorizationDecision(
        allowed=allowed,
        stage="policy",
        reason=reason,
        matched_policy=active.name or matched_policy,
    )


# ---------------------------------------------------------------------
# Registry + generic dispatch
# ---------------------------------------------------------------------

POLICY_HANDLERS: Dict[str, PolicyHandler] = {
    "max_delete_count": _check_max_delete_count,
    "max_credit_limit_raise_percent": _check_max_credit_limit_raise_percent,
    "max_starting_credit_limit": _check_max_starting_credit_limit,
}


def iter_handlers_for_tool(
    tool_name: str,
) -> Iterator[Tuple[str, PolicyHandler]]:
    """
    Yield (policy_type, handler) for every catalog policy that guards
    `tool_name`. If the catalog declares a type with no registered
    handler, yield a fail-closed handler instead of skipping it — a
    declared-but-unenforceable policy must never be silently ignored.
    """
    for policy_type, spec in POLICY_TYPES.items():
        if spec["tool_name"] != tool_name:
            continue

        handler = POLICY_HANDLERS.get(policy_type)
        if handler is None:
            def _fail_closed(
                db: Session,
                arguments: Dict[str, Any],
                _ptype: str = policy_type,
            ) -> AuthorizationDecision:
                return AuthorizationDecision(
                    allowed=False,
                    stage="policy",
                    reason=(
                        f"Policy type '{_ptype}' is declared in the catalog "
                        "but has no registered handler. Request blocked "
                        "(fail-closed)."
                    ),
                    matched_policy=_ptype,
                )
            yield policy_type, _fail_closed
        else:
            yield policy_type, handler