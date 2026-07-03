"""
Customer REST API.

A thin JSON surface over the customer dataset that runs every mutation
through the same policy engine the MCP tools use. (The module filename is
historical — it now serves the /customers routes.)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.db.deps import get_db
from app.models.customer_model import Customer
from app.models.rbac_models import User
from app.policy.engine import authorize_tool_request

router = APIRouter(prefix="/customers", tags=["customers"])

def get_user_or_404(db: Session, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    return user

@router.get("/")
def get_customers(username: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)

    # Check authorization using the Policy Engine
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="get_customers",
        required_permission="get_customers",
        arguments={}
    )

    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

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

@router.put("/{customer_id}/credit-limit")
def update_credit_limit(customer_id: int, username: str, new_credit_limit: int, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)
    args = {"customer_id": customer_id, "new_credit_limit": new_credit_limit}

    # 🛡️ THE SECURITY HEART: runs the engine's RBAC + intent + admin-configured credit-limit-raise policy
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="update_credit_limit",
        required_permission="update_credit_limit",
        arguments=args
    )

    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

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

@router.delete("/{customer_id}")
def delete_customer(customer_id: int, username: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)
    args = {"customer_id": customer_id}

    # 🛡️ This calls the "Mass Deletion" check
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="delete_customer",
        required_permission="delete_customer",
        arguments=args
    )

    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    db.delete(customer)
    db.commit()

    return {"message": f"Customer {customer_id} deleted successfully"}