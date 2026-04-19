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
    max_delete_count: int = 1,
) -> Tuple[bool, str, Optional[str]]:
    """
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
    max_raise_percent: float = 20.0,
) -> Tuple[bool, str, Optional[str]]:
    """
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