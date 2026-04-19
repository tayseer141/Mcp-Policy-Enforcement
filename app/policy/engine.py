from typing import Any, Dict
from sqlalchemy.orm import Session

from app.mcp.models import AuthorizationDecision
from app.models.employee_model import Employee
from app.policy.rules import evaluate_delete_limit_policy, evaluate_salary_raise_policy
from app.models.rbac_models import User

def check_rbac(db: Session, user: User, required_permission: str) -> AuthorizationDecision:
    """
    Stage 1: Role-Based Access Control.
    Checks if the user's role has the required permission assigned.
    """
    role = user.role
    if not role:
        return AuthorizationDecision(
            allowed=False,
            stage="rbac",
            reason="User has no assigned role."
        )

    # Assumes a relationship exists on the Role model named 'permissions'
    permissions = {perm.name for perm in role.permissions}
    
    if required_permission not in permissions:
        return AuthorizationDecision(
            allowed=False,
            stage="rbac",
            reason=f"Role '{role.name}' lacks permission '{required_permission}'."
        )

    return AuthorizationDecision(
        allowed=True,
        stage="rbac",
        reason=f"RBAC check passed for permission '{required_permission}'."
    )


def evaluate_policies(
    db,
    user: User,
    tool_name: str,
    arguments: Dict[str, Any],
) -> AuthorizationDecision:
    """
    Stage 2: Policy Evaluation layer.
    Performs contextual checks based on tool arguments and business logic.
    """

    # Policy: Mass Deletion Restriction
    # Even if RBAC allows deletion, we enforce a limit on the number of records.
    if tool_name == "delete_employee":
        allowed, reason, matched_policy = evaluate_delete_limit_policy(
            tool_name=tool_name,
            arguments=arguments,
            max_delete_count=1,  # Strict limit for the demo
        )

        return AuthorizationDecision(
            allowed=allowed,
            stage="policy",
            reason=reason,
            matched_policy=matched_policy
        )
    #########################
    if tool_name == "update_salary":
        employee_id = arguments.get("employee_id")
        requested_salary = arguments.get("new_salary")

        if employee_id is None or requested_salary is None:
            return AuthorizationDecision(
                allowed=False,
                stage="validation",
                reason="Salary update denied because employee_id or new_salary is missing.",
                matched_policy="max_salary_raise_percent",
            )

        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return AuthorizationDecision(
                allowed=False,
                stage="validation",
                reason="Salary update denied because the target employee was not found.",
                matched_policy="max_salary_raise_percent",
            )

        allowed, reason, matched_policy = evaluate_salary_raise_policy(
            current_salary=float(employee.salary),
            requested_salary=float(requested_salary),
            max_raise_percent=20.0,
        )

        return AuthorizationDecision(
            allowed=allowed,
            stage="policy",
            reason=reason,
            matched_policy=matched_policy,
        )
    # Add more policy evaluations here (e.g., salary thresholds, time-of-day checks)

    return AuthorizationDecision(
        allowed=True,
        stage="policy",
        reason="No policy blocked the request."
    )


def authorize_tool_request(
    db: Session,
    user: User,
    tool_name: str,
    required_permission: str,
    arguments: Dict[str, Any],
) -> AuthorizationDecision:
    """
    The main Entry Point (Policy Decision Point).
    Orchestrates the RBAC and Policy stages in sequence.
    """
    # 1. Run RBAC Check
    rbac_decision = check_rbac(db, user, required_permission)
    if not rbac_decision.allowed:
        return rbac_decision

    # 2. Run Policy Evaluation
    policy_decision = evaluate_policies(db, user, tool_name, arguments)
    if not policy_decision.allowed:
        return policy_decision

    # 3. Final Approval
    return AuthorizationDecision(
        allowed=True,
        stage="policy",
        reason="Authorization passed: RBAC and policy checks succeeded."
    )