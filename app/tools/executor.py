from sqlalchemy.orm import Session
from app.models.employee_model import Employee

def execute_tool(db: Session, tool_name: str, arguments: dict):
    # --- Read Operations ---
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
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {"error": "Employee not found"}

        return {
            "id": employee.id,
            "name": employee.name,
            "department": employee.department,
            "salary": employee.salary,
        }

    # --- Update Operations ---
    if tool_name == "update_salary":
        employee_id = arguments.get("employee_id")
        new_salary = arguments.get("new_salary")

        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {"error": "Employee not found"}

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

    # --- Delete Operations (Updated for Policy Support) ---
    if tool_name == "delete_employee":
        employee_ids = arguments.get("employee_ids")
        employee_id = arguments.get("employee_id")

        # Case 1: Bulk Delete (List of IDs)
        if employee_ids and isinstance(employee_ids, list):
            deleted_count = 0
            for emp_id in employee_ids:
                employee = db.query(Employee).filter(Employee.id == emp_id).first()
                if employee:
                    db.delete(employee)
                    deleted_count += 1
            db.commit()
            return {"message": f"Bulk delete successful", "deleted_count": deleted_count}

        # Case 2: Single Delete
        if employee_id is not None:
            employee = db.query(Employee).filter(Employee.id == employee_id).first()
            if not employee:
                return {"error": "Employee not found"}
            
            db.delete(employee)
            db.commit()
            return {"message": f"Employee {employee_id} deleted successfully", "deleted_count": 1}

        return {"error": "Missing employee_id or employee_ids"}

    return {"error": f"Unknown tool: {tool_name}"}