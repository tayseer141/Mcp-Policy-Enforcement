from app.mcp.models import ToolDefinition


class MCPToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register_tool(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get_tool(self, tool_name: str):
        return self._tools.get(tool_name)

    def list_tools(self):
        return list(self._tools.values())


registry = MCPToolRegistry()


def register_default_tools():
    registry.register_tool(
        ToolDefinition(
            name="get_employees",
            description="Get the full list of employees.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            required_permission="get_employees",
            category="employees",
            risk_level="low",
        )
    )

    registry.register_tool(
        ToolDefinition(
            name="get_employee_by_id",
            description="Get one employee by employee ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "employee_id": {"type": "integer", "description": "The employee ID"}
                },
                "required": ["employee_id"],
                "additionalProperties": False,
            },
            required_permission="get_employee_by_id",
            category="employees",
            risk_level="low",
        )
    )

    registry.register_tool(
        ToolDefinition(
            name="update_salary",
            description="Update the salary of an employee.",
            input_schema={
                "type": "object",
                "properties": {
                    "employee_id": {"type": "integer", "description": "The employee ID"},
                    "new_salary": {"type": "integer", "description": "The new salary"},
                },
                "required": ["employee_id", "new_salary"],
                "additionalProperties": False,
            },
            required_permission="update_salary",
            category="employees",
            risk_level="high",
        )
    )

    registry.register_tool(
        ToolDefinition(
            name="delete_employee",
            description="Delete an employee by employee ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "employee_id": {"type": "integer", "description": "The employee ID"}
                },
                "required": ["employee_id"],
                "additionalProperties": False,
            },
            required_permission="delete_employee",
            category="employees",
            risk_level="critical",
        )
    )