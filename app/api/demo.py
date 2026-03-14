from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates

from app.db.deps import get_db
from app.policy.engine import check_permission
from app.services.openai_service import select_tool_from_prompt
from app.tools.executor import execute_tool

import json


router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request):
    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "title": "MCP Secure Demo",
            "result": None,
        },
    )


@router.post("/demo", response_class=HTMLResponse)
def run_demo(
    request: Request,
    username: str = Form(...),
    prompt: str = Form(...),
    db: Session = Depends(get_db),
):
    selection = select_tool_from_prompt(prompt)
    tool_name = selection["tool_name"]
    arguments = selection["arguments"]

    print("\n--- SECURITY LOG ---")
    print(f"User: {username}")
    print(f"Prompt: {prompt}")
    print(f"Tool selected: {tool_name}")
    print(f"Arguments: {arguments}")
    print("--------------------\n")

    if not tool_name:
        result = {
            "username": username,
            "prompt": prompt,
            "tool_name": None,
            "arguments": {},
            "policy_decision": "DENY",
            "final_output": "No valid tool was selected by the model.",
        }
        return templates.TemplateResponse(
            "demo.html",
            {"request": request, "title": "MCP Secure Demo", "result": result},
        )

    allowed = check_permission(db, username, tool_name)

    print(f"Policy decision: {'ALLOW' if allowed else 'DENY'}")
    print("--------------------\n")

    if not allowed:
        result = {
            "username": username,
            "prompt": prompt,
            "tool_name": tool_name,
            "arguments": arguments,
            "policy_decision": "DENY",
            "final_output": f"Access denied: user '{username}' is not allowed to execute '{tool_name}'.",
        }
        return templates.TemplateResponse(
            "demo.html",
            {"request": request, "title": "MCP Secure Demo", "result": result},
        )

    execution_result = execute_tool(db, tool_name, arguments)
    execution_result = json.dumps(execution_result, indent=2)

    result = {
        "username": username,
        "prompt": prompt,
        "tool_name": tool_name,
        "arguments": arguments,
        "policy_decision": "ALLOW",
        "final_output": execution_result,
    }

    return templates.TemplateResponse(
        "demo.html",
        {"request": request, "title": "MCP Secure Demo", "result": result},
    )
