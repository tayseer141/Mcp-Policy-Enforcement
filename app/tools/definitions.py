TOOLS = [
    {
        "type": "function",
        "name": "get_employees",
        "description": "Get the full list of employees.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "get_employee_by_id",
        "description": "Get one employee by employee ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "integer",
                    "description": "The employee ID"
                }
            },
            "required": ["employee_id"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "update_salary",
        "description": "Update the salary of an employee.",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "integer",
                    "description": "The employee ID"
                },
                "new_salary": {
                    "type": "integer",
                    "description": "The new salary"
                }
            },
            "required": ["employee_id", "new_salary"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "delete_employee",
        "description": "Delete an employee by employee ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "integer",
                    "description": "The employee ID"
                }
            },
            "required": ["employee_id"],
            "additionalProperties": False
        }
    }
]
