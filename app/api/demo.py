from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
import json

from app.db.deps import get_db
from app.models.rbac_models import User
from app.services.openai_service import select_tool_from_prompt, summarize_tool_result
from app.services.tool_service import run_tool_for_user

router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory="app/templates")


def _load_users(db: Session) -> list[dict]:
    """
    Return the current user list from the DB so the demo dropdown is
    always in sync with whatever the admin dashboard has created. Kept
    as a plain list of dicts so the template doesn't rely on the ORM
    object lifecycle.
    """
    rows = db.query(User).order_by(User.username.asc()).all()
    return [
        {
            "username": u.username,
            "role": u.role.name if u.role else None,
        }
        for u in rows
    ]


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request, db: Session = Depends(get_db)):
    """Renders the secure MCP demo interface."""
    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "title": "MCP Secure Demo",
            "result": None,
            "users": _load_users(db),
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
    2. Request is routed through the Secure Tool Service (MCP client).
    3. Policy Engine on the MCP server runs RBAC -> Intent -> Policy stages.
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
            "authorization_stage": "tool-selection",
            "human_summary": None,
        }
        return templates.TemplateResponse(
            "demo.html",
            {
                "request": request,
                "title": "MCP Secure Demo",
                "result": result,
                "users": _load_users(db),
            },
        )

    # Step 2: Secure Execution Path (web -> MCP server -> policy engine -> DB)
    policy_decision = "DENY"
    final_output: object = ""
    auth_stage = "N/A"

    try:
        execution_result = run_tool_for_user(
            db=db,
            username=username,
            tool_name=tool_name,
            required_permission=tool_name,
            arguments=arguments,
            raw_prompt=prompt,  # enables the intent-alignment stage
        )
        policy_decision = "ALLOW"
        final_output = execution_result
        auth_stage = "success"

    except PermissionError as e:
        # RBAC / Intent / Policy denial reported by the MCP server.
        policy_decision = "DENY"
        final_output = f"Access Blocked: {str(e)}"
        reason_lower = str(e).lower()
        if "intent" in reason_lower:
            auth_stage = "intent"
        elif "lacks permission" in reason_lower or "no assigned role" in reason_lower:
            auth_stage = "rbac"
        else:
            auth_stage = "policy"

    except Exception as e:
        policy_decision = "ERROR"
        final_output = f"Execution failed: {str(e)}"
        auth_stage = "system"

    # Step 3: Natural-language response layer (functional req #4).
    # Only summarize when the call was actually ALLOWed and succeeded.
    # For denials and errors the message is already human-readable and
    # security-relevant, so we leave it verbatim.
    human_summary: str | None = None
    if policy_decision == "ALLOW":
        human_summary = summarize_tool_result(
            prompt=prompt,
            tool_name=tool_name,
            result=final_output,
        )

    # Step 4: Formatting for UI Display
    if isinstance(final_output, (dict, list)):
        final_output = json.dumps(final_output, indent=2, ensure_ascii=False)

    result = {
        "username": username,
        "prompt": prompt,
        "tool_name": tool_name,
        "arguments": arguments,
        "policy_decision": policy_decision,
        "final_output": str(final_output),
        "authorization_stage": auth_stage,
        "human_summary": human_summary,
    }

    print(f"Final Decision: {policy_decision} (stage={auth_stage})")
    print("--------------------\n")

    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "title": "MCP Secure Demo",
            "result": result,
            "users": _load_users(db),
        },
    )