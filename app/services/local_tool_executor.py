from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.customer_model import Customer
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

    if tool_name == "get_customers":
        customers = db.query(Customer).all()
        return [
            {
                "id": cust.id,
                "name": cust.name,
                "company": cust.company,
                "credit_limit": cust.credit_limit,
            }
            for cust in customers
        ]

    if tool_name == "get_customer_by_id":
        customer_id = arguments.get("customer_id")
        if customer_id is None:
            raise ValueError("customer_id is required")

        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise ValueError("Customer not found")

        return {
            "id": customer.id,
            "name": customer.name,
            "company": customer.company,
            "credit_limit": customer.credit_limit,
        }

    if tool_name == "update_credit_limit":
        customer_id = arguments.get("customer_id")
        new_credit_limit = arguments.get("new_credit_limit")

        if customer_id is None or new_credit_limit is None:
            raise ValueError("customer_id and new_credit_limit are required")

        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise ValueError("Customer not found")

        customer.credit_limit = new_credit_limit
        db.commit()
        db.refresh(customer)

        return {
            "message": "Credit limit updated successfully",
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "company": customer.company,
                "credit_limit": customer.credit_limit,
            },
        }

    if tool_name == "add_customer":
        name = arguments.get("name")
        company = arguments.get("company")
        credit_limit = arguments.get("credit_limit")

        if not name or not company or credit_limit is None:
            raise ValueError("name, company and credit_limit are required")

        customer = Customer(name=name, company=company, credit_limit=credit_limit)
        db.add(customer)
        db.commit()
        db.refresh(customer)

        return {
            "message": "Customer added successfully",
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "company": customer.company,
                "credit_limit": customer.credit_limit,
            },
        }

    if tool_name == "delete_customer":
        customer_ids = arguments.get("customer_ids")
        customer_id = arguments.get("customer_id")

        if isinstance(customer_ids, list) and customer_ids:
            deleted_count = 0
            for cust_id in customer_ids:
                customer = db.query(Customer).filter(Customer.id == cust_id).first()
                if customer:
                    db.delete(customer)
                    deleted_count += 1
            db.commit()
            return {
                "message": "Bulk delete successful",
                "deleted_count": deleted_count,
            }

        if customer_id is not None:
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                raise ValueError("Customer not found")

            db.delete(customer)
            db.commit()
            return {
                "message": f"Customer {customer_id} deleted successfully",
                "deleted_count": 1,
            }

        raise ValueError("Missing customer_id or customer_ids")

    raise ValueError(f"Unknown tool '{tool_name}'")