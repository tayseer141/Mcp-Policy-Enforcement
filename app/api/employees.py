from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.db.deps import get_db
from app.models.employee_model import Employee
from app.models.rbac_models import User
from app.policy.engine import authorize_tool_request

router = APIRouter(prefix="/employees", tags=["employees"])

def get_user_or_404(db: Session, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    return user

@router.get("/")
def get_employees(username: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)
    
    # Check authorization using the Policy Engine
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="get_employees",
        required_permission="get_employees",
        arguments={}
    )
    
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

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

@router.put("/{employee_id}/salary")
def update_salary(employee_id: int, username: str, new_salary: int, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)
    args = {"employee_id": employee_id, "new_salary": new_salary}
    
    # 🛡️ THE SECURITY HEART: This calls the 20% raise check
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="update_salary",
        required_permission="update_salary",
        arguments=args
    )
    
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

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

@router.delete("/{employee_id}")
def delete_employee(employee_id: int, username: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, username)
    args = {"employee_id": employee_id}
    
    # 🛡️ This calls the "Mass Deletion" check
    decision = authorize_tool_request(
        db=db,
        user=user,
        tool_name="delete_employee",
        required_permission="delete_employee",
        arguments=args
    )
    
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.delete(employee)
    db.commit()

    return {"message": f"Employee {employee_id} deleted successfully"}