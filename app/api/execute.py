"""
Tool execution API.

This is the platform's primary public endpoint. The HTML console at
/demo, the planned admin tools, automated tests, and any future
external client all speak to the system through here. The endpoint
returns pure JSON — no HTML, no templates, no rendering concerns.

Pipeline:
    1. LLM picks a tool that matches the user's natural-language prompt.
    2. The request is routed through the secure tool service into the
       MCP server, where the policy engine runs RBAC -> Intent -> Policy.
    3. On ALLOW, the structured tool result is summarized into prose by
       the LLM (functional req #4) and both forms are returned.
    4. On DENY/ERROR, the verbatim policy-engine reason is returned
       (never paraphrased — see ARCHITECTURE.md "LLM isolation").
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.schemas.execute import ExecuteRequest, ExecuteResponse
from app.services.openai_service import (
    select_tool_from_prompt,
    summarize_tool_result,
)
from app.services.tool_service import run_tool_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["execute"])


def _classify_denial_stage(reason: str) -> str:
    """
    Map a policy-engine PermissionError message to its originating stage.
    Stage tags are part of the public response contract, so they should
    stay stable.
    """
    reason_lower = reason.lower()
    if "intent" in reason_lower:
        return "intent"
    if "lacks permission" in reason_lower or "no assigned role" in reason_lower:
        return "rbac"
    return "policy"


@router.post("/execute", response_model=ExecuteResponse)
def execute_tool(
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
) -> ExecuteResponse:
    """
    Run one natural-language request through the secure pipeline.

    Always returns 200 with a structured ExecuteResponse — clients
    branch on `policy_decision` to know whether the call was allowed.
    """
    # --- Stage 1: LLM tool selection -----------------------------------
    selection = select_tool_from_prompt(payload.prompt)
    tool_name = selection.get("tool_name")
    arguments = selection.get("arguments") or {}

    logger.info(
        "execute request user=%s prompt=%r llm_tool=%s args=%s",
        payload.username,
        payload.prompt,
        tool_name,
        arguments,
    )

    if not tool_name:
        return ExecuteResponse(
            username=payload.username,
            prompt=payload.prompt,
            policy_decision="DENY",
            authorization_stage="tool-selection",
            error_message=(
                "The model could not map your request to an available secure tool."
            ),
        )

    # --- Stage 2: Secure execution -------------------------------------
    try:
        tool_result = run_tool_for_user(
            db=db,
            username=payload.username,
            tool_name=tool_name,
            required_permission=tool_name,
            arguments=arguments,
            raw_prompt=payload.prompt,  # enables intent alignment
        )

    except PermissionError as e:
        reason = str(e)
        stage = _classify_denial_stage(reason)
        logger.info(
            "execute denied user=%s tool=%s stage=%s reason=%s",
            payload.username,
            tool_name,
            stage,
            reason,
        )
        return ExecuteResponse(
            username=payload.username,
            prompt=payload.prompt,
            tool_name=tool_name,
            arguments=arguments,
            policy_decision="DENY",
            authorization_stage=stage,
            error_message=reason,
        )

    except Exception as e:
        logger.exception(
            "execute system error user=%s tool=%s",
            payload.username,
            tool_name,
        )
        return ExecuteResponse(
            username=payload.username,
            prompt=payload.prompt,
            tool_name=tool_name,
            arguments=arguments,
            policy_decision="ERROR",
            authorization_stage="system",
            error_message=f"Execution failed: {e}",
        )

    # --- Stage 3: Natural-language summary on success ------------------
    human_summary = summarize_tool_result(
        prompt=payload.prompt,
        tool_name=tool_name,
        result=tool_result,
    )

    logger.info(
        "execute allowed user=%s tool=%s summary_chars=%s",
        payload.username,
        tool_name,
        len(human_summary) if human_summary else 0,
    )

    return ExecuteResponse(
        username=payload.username,
        prompt=payload.prompt,
        tool_name=tool_name,
        arguments=arguments,
        policy_decision="ALLOW",
        authorization_stage="success",
        tool_output=tool_result,
        human_summary=human_summary,
    )