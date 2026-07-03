"""
Pure policy-evaluation helpers.

These functions only *enforce* a limit — they never decide what the limit
is. The threshold is always supplied by the caller (the policy engine,
which resolves it from the admin-managed `policies` table via
app.policy.store). There are deliberately no default thresholds here:
the old hardcoded 1-delete / 20%-raise constants now live as editable
rows in the database, authored from the admin dashboard (including in
natural language), not baked into this module.
"""

from typing import Any, Dict, Optional, Tuple


def extract_delete_count(tool_name: str, arguments: Dict[str, Any]) -> Optional[int]:
    """
    Try to determine how many customer records are being targeted by a delete request.
    """
    if tool_name != "delete_customer":
        return None

    # Case 1: explicit list of ids
    customer_ids = arguments.get("customer_ids")
    if isinstance(customer_ids, list):
        return len(customer_ids)

    # Case 2: single customer id
    customer_id = arguments.get("customer_id")
    if customer_id is not None:
        return 1

    # Case 3: delete all / broad delete flag
    if arguments.get("delete_all") is True:
        return 999999

    # Unknown scope
    return None


def evaluate_delete_limit_policy(
    tool_name: str,
    arguments: Dict[str, Any],
    max_delete_count: int,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforce a maximum delete count. `max_delete_count` is supplied by the
    caller from the active policy — this function does not invent a limit.

    Returns:
        (allowed, reason, matched_policy_name)
    """
    if tool_name != "delete_customer":
        return True, "No delete-limit policy applies.", None

    count = extract_delete_count(tool_name, arguments)

    if count is None:
        return False, "Delete request denied because delete scope is unclear.", "max_delete_count"

    if count > max_delete_count:
        return (
            False,
            f"Delete request exceeds the allowed maximum of {max_delete_count} customer(s).",
            "max_delete_count",
        )

    return True, "Delete request is within policy limit.", "max_delete_count"


def evaluate_credit_limit_raise_policy(
    current_credit_limit: float,
    requested_credit_limit: float,
    max_raise_percent: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforce a maximum credit-limit-raise percentage. `max_raise_percent` is
    supplied by the caller from the active policy — this function does not
    invent a limit.

    Returns:
        (allowed, reason, matched_policy_name)
    """
    if current_credit_limit <= 0:
        return (
            False,
            "Credit limit update denied because current credit limit is invalid for policy evaluation.",
            "max_credit_limit_raise_percent",
        )

    if requested_credit_limit < 0:
        return (
            False,
            "Credit limit update denied because requested credit limit cannot be negative.",
            "max_credit_limit_raise_percent",
        )

    if requested_credit_limit <= current_credit_limit:
        return (
            True,
            "Credit limit update is within policy limit.",
            "max_credit_limit_raise_percent",
        )

    increase_percent = (
        (requested_credit_limit - current_credit_limit) / current_credit_limit
    ) * 100

    if increase_percent > max_raise_percent:
        return (
            False,
            f"Credit limit update exceeds the allowed maximum raise of {max_raise_percent:.0f}%.",
            "max_credit_limit_raise_percent",
        )

    return (
        True,
        "Credit limit update is within policy limit.",
        "max_credit_limit_raise_percent",
    )


def evaluate_starting_credit_limit_policy(
    requested_credit_limit: float,
    max_starting_credit_limit: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforce a maximum starting credit limit for a newly created customer.
    `max_starting_credit_limit` is supplied by the caller from the active policy.

    Returns:
        (allowed, reason, matched_policy_name)
    """
    if requested_credit_limit < 0:
        return (
            False,
            "Add customer denied because the starting credit limit cannot be negative.",
            "max_starting_credit_limit",
        )

    if requested_credit_limit > max_starting_credit_limit:
        return (
            False,
            f"Starting credit limit exceeds the allowed maximum of {max_starting_credit_limit:.0f}.",
            "max_starting_credit_limit",
        )

    return (
        True,
        "Starting credit limit is within policy limit.",
        "max_starting_credit_limit",
    )