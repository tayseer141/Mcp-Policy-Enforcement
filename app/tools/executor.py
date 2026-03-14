from sqlalchemy.orm import Session
from app.models.employee_model import Employee


def execute_tool(db: Session, tool_name: str, arguments: dict):
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

    if tool_name == "delete_employee":
        employee_id = arguments.get("employee_id")
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {"error": "Employee not found"}

        db.delete(employee)
        db.commit()
        return {"message": f"Employee with id {employee_id} deleted successfully"}

    return {"error": f"Unknown tool: {tool_name}"}
