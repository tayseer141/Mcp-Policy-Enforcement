from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.employee_model import Employee
from app.policy.engine import check_permission

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("/")
def get_employees(username: str, db: Session = Depends(get_db)):
    allowed = check_permission(db, username, "get_employees")
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

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


@router.get("/{employee_id}")
def get_employee_by_id(employee_id: int, username: str, db: Session = Depends(get_db)):
    allowed = check_permission(db, username, "get_employee_by_id")
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    return {
        "id": employee.id,
        "name": employee.name,
        "department": employee.department,
        "salary": employee.salary,
    }


@router.put("/{employee_id}/salary")
def update_salary(employee_id: int, username: str, new_salary: int, db: Session = Depends(get_db)):
    allowed = check_permission(db, username, "update_salary")
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

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
    allowed = check_permission(db, username, "delete_employee")
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.delete(employee)
    db.commit()

    return {
        "message": f"Employee with id {employee_id} deleted successfully"
    }
