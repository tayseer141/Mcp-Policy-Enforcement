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
    Try to determine how many employee records are being targeted by a delete request.
    """
    if tool_name != "delete_employee":
        return None

    # Case 1: explicit list of ids
    employee_ids = arguments.get("employee_ids")
    if isinstance(employee_ids, list):
        return len(employee_ids)

    # Case 2: single employee id
    employee_id = arguments.get("employee_id")
    if employee_id is not None:
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
    if tool_name != "delete_employee":
        return True, "No delete-limit policy applies.", None

    count = extract_delete_count(tool_name, arguments)

    if count is None:
        return False, "Delete request denied because delete scope is unclear.", "max_delete_count"

    if count > max_delete_count:
        return (
            False,
            f"Delete request exceeds the allowed maximum of {max_delete_count} employee(s).",
            "max_delete_count",
        )

    return True, "Delete request is within policy limit.", "max_delete_count"

    
def evaluate_salary_raise_policy(
    current_salary: float,
    requested_salary: float,
    max_raise_percent: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforce a maximum salary-raise percentage. `max_raise_percent` is
    supplied by the caller from the active policy — this function does not
    invent a limit.

    Returns:
        (allowed, reason, matched_policy_name)
    """
    if current_salary <= 0:
        return (
            False,
            "Salary update denied because current salary is invalid for policy evaluation.",
            "max_salary_raise_percent",
        )

    if requested_salary < 0:
        return (
            False,
            "Salary update denied because requested salary cannot be negative.",
            "max_salary_raise_percent",
        )

    if requested_salary <= current_salary:
        return (
            True,
            "Salary update is within policy limit.",
            "max_salary_raise_percent",
        )

    increase_percent = ((requested_salary - current_salary) / current_salary) * 100

    if increase_percent > max_raise_percent:
        return (
            False,
            f"Salary update exceeds the allowed maximum raise of {max_raise_percent:.0f}%.",
            "max_salary_raise_percent",
        )

    return (
        True,
        "Salary update is within policy limit.",
        "max_salary_raise_percent",
    )


def evaluate_starting_salary_policy(
    requested_salary: float,
    max_starting_salary: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforce a maximum starting salary for a newly created employee.
    `max_starting_salary` is supplied by the caller from the active policy.

    Returns:
        (allowed, reason, matched_policy_name)
    """
    if requested_salary < 0:
        return (
            False,
            "Add employee denied because the starting salary cannot be negative.",
            "max_starting_salary",
        )

    if requested_salary > max_starting_salary:
        return (
            False,
            f"Starting salary exceeds the allowed maximum of {max_starting_salary:.0f}.",
            "max_starting_salary",
        )

    return (
        True,
        "Starting salary is within policy limit.",
        "max_starting_salary",
    )