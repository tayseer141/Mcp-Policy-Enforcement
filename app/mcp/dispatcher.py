from sqlalchemy.orm import Session
from app.tools.executor import execute_tool


def dispatch_tool(db: Session, tool_name: str, arguments: dict):
    return execute_tool(db, tool_name, arguments)