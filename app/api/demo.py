from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
import json

from app.db.deps import get_db
from app.services.openai_service import select_tool_from_prompt
from app.services.tool_service import run_tool_for_user

router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request):
    """Renders the secure MCP demo interface."""
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
    """
    Main demo execution flow:
    1. Model selects tool via OpenAI Service.
    2. Request is routed through the Secure Tool Service.
    3. Policy Engine evaluates RBAC and Business Logic.
    4. Result is returned to the UI.
    """
    # Step 1: AI Analysis
    selection = select_tool_from_prompt(prompt)
    tool_name = selection["tool_name"]
    arguments = selection["arguments"]

    print("\n--- SECURITY LOG ---")
    print(f"User Identification: {username}")
    print(f"User Prompt: {prompt}")
    print(f"LLM Tool Selection: {tool_name}")
    print(f"Extracted Arguments: {arguments}")

    if not tool_name:
        result = {
            "username": username,
            "prompt": prompt,
            "tool_name": None,
            "arguments": {},
            "policy_decision": "DENY",
            "final_output": "The model could not map your request to an available secure tool.",
        }
        return templates.TemplateResponse(
            "demo.html",
            {"request": request, "title": "MCP Secure Demo", "result": result},
        )

    # Step 2: Secure Execution Path
    policy_decision = "DENY"
    final_output = ""
    auth_stage = "N/A"

    try:
        # Every request goes through the unified policy path
        execution_result = run_tool_for_user(
            db=db,
            username=username,
            tool_name=tool_name,
            required_permission=tool_name, # Mapping tool to permission
            arguments=arguments
        )
        policy_decision = "ALLOW"
        final_output = execution_result
        auth_stage = "Success"

    except PermissionError as e:
        # This catches Policy violations (like the 20% rule) or RBAC failures
        policy_decision = "DENY"
        final_output = f"Access Blocked: {str(e)}"
        auth_stage = "Policy/RBAC Enforcement"
        
    except Exception as e:
        # General system error handling
        policy_decision = "ERROR"
        final_output = f"Execution failed: {str(e)}"
        auth_stage = "System"

    # Step 3: Formatting for UI Display
    if isinstance(final_output, (dict, list)):
        final_output = json.dumps(final_output, indent=2, ensure_ascii=False)

    result = {
        "username": username,
        "prompt": prompt,
        "tool_name": tool_name,
        "arguments": arguments,
        "policy_decision": policy_decision,
        "final_output": str(final_output),
        "authorization_stage": auth_stage
    }

    print(f"Final Decision: {policy_decision}")
    print("--------------------\n")

    return templates.TemplateResponse(
        "demo.html",
        {"request": request, "title": "MCP Secure Demo", "result": result},
    )