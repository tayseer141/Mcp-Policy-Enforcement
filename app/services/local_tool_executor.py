from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.employee_model import Employee
from app.models.rbac_models import User
from app.policy.engine import authorize_tool_request, RAW_PROMPT_ARG_KEY


# Sentinel key used to mark a result as a policy/RBAC/intent denial.
# The MCP client watches for this and re-raises PermissionError on the web
# side so the console UI can cleanly distinguish "DENY" from "ERROR".
POLICY_DENIED_KEY = "__policy_denied__"


def _denied(decision) -> dict:
    """Build the structured denial payload returned by tools on deny."""
    return {
        POLICY_DENIED_KEY: True,
        "allowed": False,
        "reason": decision.reason,
        "stage": decision.stage,
        "matched_policy": decision.matched_policy,
    }


def get_user_or_raise(db: Session, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError(f"User '{username}' not found")
    return user


def execute_tool_locally(
    db: Session,
    username: str,
    tool_name: str,
    required_permission: str,
    arguments: dict[str, Any],
    raw_prompt: Optional[str] = None,
) -> Any:
    """
    Local secure execution path for the real MCP server.

    Flow:
    1. Resolve user from local RBAC database.
    2. Run authorization: RBAC -> Intent -> Policy stages.
       - On DENY: return a structured denial payload (NOT an exception),
         so FastMCP treats this as a successful call whose body is the
         denial record. The web-side client translates it into a
         PermissionError for clean UI handling.
    3. Execute the requested tool against the DB.
    4. Return plain Python data on success.

    `raw_prompt` (if provided) is routed into the policy engine's argument
    bag under the reserved key so the intent-alignment stage can run.
    It is NOT passed to the executor logic itself.
    """
    user = get_user_or_raise(db, username)

    auth_arguments = dict(arguments)
    if raw_prompt:
        auth_arguments[RAW_PROMPT_ARG_KEY] = raw_prompt

    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name=tool_name,
        required_permission=required_permission,
        arguments=auth_arguments,
    )

    if not decision.allowed:
        return _denied(decision)

    if tool_name == "health_check":
        return {
            "status": "ok",
            "server": "policy-enforcement-mcp",
        }

    if tool_name == "get_employees":
        employees = db.query(Employee).all()
        return [
            {
                "id": emp.id,
                "name": emp.name,
                "department": emp.department,
                "salary": emp.salary,
            }
            for emp in employees
        ]

    if tool_name == "get_employee_by_id":
        employee_id = arguments.get("employee_id")
        if employee_id is None:
            raise ValueError("employee_id is required")

        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Employee not found")

        return {
            "id": employee.id,
            "name": employee.name,
            "department": employee.department,
            "salary": employee.salary,
        }

    if tool_name == "update_salary":
        employee_id = arguments.get("employee_id")
        new_salary = arguments.get("new_salary")

        if employee_id is None or new_salary is None:
            raise ValueError("employee_id and new_salary are required")

        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Employee not found")

        employee.salary = new_salary
        db.commit()
        db.refresh(employee)

        return {
            "message": "Salary updated successfully",
            "employee": {
                "id": employee.id,
                "name": employee.name,
                "department": employee.department,
                "salary": employee.salary,
            },
        }

    if tool_name == "add_employee":
        name = arguments.get("name")
        department = arguments.get("department")
        salary = arguments.get("salary")

        if not name or not department or salary is None:
            raise ValueError("name, department and salary are required")

        employee = Employee(name=name, department=department, salary=salary)
        db.add(employee)
        db.commit()
        db.refresh(employee)

        return {
            "message": "Employee added successfully",
            "employee": {
                "id": employee.id,
                "name": employee.name,
                "department": employee.department,
                "salary": employee.salary,
            },
        }

    if tool_name == "delete_employee":
        employee_ids = arguments.get("employee_ids")
        employee_id = arguments.get("employee_id")

        if isinstance(employee_ids, list) and employee_ids:
            deleted_count = 0
            for emp_id in employee_ids:
                employee = db.query(Employee).filter(Employee.id == emp_id).first()
                if employee:
                    db.delete(employee)
                    deleted_count += 1
            db.commit()
            return {
                "message": "Bulk delete successful",
                "deleted_count": deleted_count,
            }

        if employee_id is not None:
            employee = db.query(Employee).filter(Employee.id == employee_id).first()
            if not employee:
                raise ValueError("Employee not found")

            db.delete(employee)
            db.commit()
            return {
                "message": f"Employee {employee_id} deleted successfully",
                "deleted_count": 1,
            }

        raise ValueError("Missing employee_id or employee_ids")

    raise ValueError(f"Unknown tool '{tool_name}'")