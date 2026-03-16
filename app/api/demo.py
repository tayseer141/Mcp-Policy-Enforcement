from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
import json

from app.db.deps import get_db
from app.services.openai_service import select_tool_from_prompt

from app.mcp.server import mcp_server
from app.mcp.models import ToolCallRequest
from app.mcp.context import build_mcp_context


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

    context = build_mcp_context(username=username, raw_prompt=prompt)

    mcp_request = ToolCallRequest(
        tool_name=tool_name,
        arguments=arguments,
        context=context,
    )

    mcp_response = mcp_server.call_tool(db, mcp_request)

    policy_decision = "DENY"
    if getattr(mcp_response, 'authorization', None) and mcp_response.authorization.allowed:
        policy_decision = "ALLOW"
    elif not getattr(mcp_response, 'authorization', None) and mcp_response.success:
        policy_decision = "ALLOW"

    final_output = mcp_response.result if mcp_response.success else mcp_response.error
    
    if isinstance(final_output, (dict, list)):
        final_output = json.dumps(final_output, indent=2, ensure_ascii=False)

    result = {
        "username": username,
        "prompt": prompt,
        "tool_name": tool_name,
        "arguments": arguments,
        "policy_decision": policy_decision,
        "final_output": str(final_output),
    }

    return templates.TemplateResponse(
        "demo.html",
        {"request": request, "title": "MCP Secure Demo", "result": result},
    )