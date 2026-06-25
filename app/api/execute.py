"""
Tool execution API.

This is the platform's primary public endpoint. The HTML console at
/console, the planned admin tools, automated tests, and any future
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

Two surfaces share this pipeline:
    * POST /api/v1/execute         — single JSON response (the contract).
    * POST /api/v1/execute/stream  — Server-Sent Events that narrate each
      stage live, so the console can animate the pipeline in real time.
"""

import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
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

# Visual pacing (seconds) between the policy sub-stages that the engine
# actually evaluates as one unit. The genuinely slow stages (LLM tool
# selection and answer summarization) gate the stream on their own, so
# these small delays only space out the fast RBAC/Intent/Policy reveal
# enough for the operator's eye to follow the live pipeline.
_STAGE_PACING_S = 0.18

# The four gates evaluated inside run_tool_for_user, in order. (Stage 1,
# LLM tool-selection, happens before this list.)
_SECURITY_GATES = ["rbac", "intent", "policy", "execution"]


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


def _sse(event: dict) -> str:
    """Serialize one event as a Server-Sent Events frame."""
    return f"data: {json.dumps(event)}\n\n"


def _stage(key: str, status: str) -> str:
    """SSE frame announcing a pipeline stage transition."""
    return _sse({"type": "stage", "key": key, "status": status})


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


@router.post("/execute/stream")
def execute_tool_stream(
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Streaming twin of POST /execute.

    Runs the exact same secure pipeline, but emits a Server-Sent Event
    as the server reaches each stage so the console can light up the
    pipeline live instead of revealing the whole verdict at once. The
    final `result` event carries the same payload shape as the JSON
    ExecuteResponse, so clients render it identically.
    """

    def event_stream():
        base = {"username": payload.username, "prompt": payload.prompt}

        # ----- Stage 1: LLM tool selection (real latency) -------------
        yield _stage("tool-selection", "running")
        selection = select_tool_from_prompt(payload.prompt)
        tool_name = selection.get("tool_name")
        arguments = selection.get("arguments") or {}

        logger.info(
            "stream request user=%s prompt=%r llm_tool=%s args=%s",
            payload.username, payload.prompt, tool_name, arguments,
        )

        if not tool_name:
            yield _stage("tool-selection", "fail")
            yield _sse({
                "type": "result", **base,
                "policy_decision": "DENY",
                "authorization_stage": "tool-selection",
                "error_message": (
                    "The model could not map your request to an "
                    "available secure tool."
                ),
            })
            return
        yield _stage("tool-selection", "ok")
        time.sleep(_STAGE_PACING_S)

        # ----- Stages 2-5: RBAC -> Intent -> Policy -> Execution ------
        # The engine evaluates these as one unit. We pulse the first gate
        # while the real work runs, then reveal each gate's true outcome.
        yield _stage("rbac", "running")
        try:
            tool_result = run_tool_for_user(
                db=db,
                username=payload.username,
                tool_name=tool_name,
                required_permission=tool_name,
                arguments=arguments,
                raw_prompt=payload.prompt,
            )
        except PermissionError as e:
            reason = str(e)
            stage = _classify_denial_stage(reason)
            fail_idx = (
                _SECURITY_GATES.index(stage)
                if stage in _SECURITY_GATES else 0
            )
            logger.info(
                "stream denied user=%s tool=%s stage=%s",
                payload.username, tool_name, stage,
            )
            for i, gate in enumerate(_SECURITY_GATES):
                if i < fail_idx:
                    yield _stage(gate, "ok")
                    time.sleep(_STAGE_PACING_S)
                elif i == fail_idx:
                    yield _stage(gate, "fail")
                    break
            yield _sse({
                "type": "result", **base,
                "tool_name": tool_name, "arguments": arguments,
                "policy_decision": "DENY",
                "authorization_stage": stage,
                "error_message": reason,
            })
            return
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "stream system error user=%s tool=%s",
                payload.username, tool_name,
            )
            for gate in ("rbac", "intent", "policy"):
                yield _stage(gate, "ok")
                time.sleep(_STAGE_PACING_S)
            yield _stage("execution", "fail")
            yield _sse({
                "type": "result", **base,
                "tool_name": tool_name, "arguments": arguments,
                "policy_decision": "ERROR",
                "authorization_stage": "system",
                "error_message": f"Execution failed: {e}",
            })
            return

        # Allowed: reveal each passed gate, then run the summary.
        for gate in ("rbac", "intent", "policy"):
            yield _stage(gate, "ok")
            time.sleep(_STAGE_PACING_S)

        # ----- Answer summarization (real latency) --------------------
        yield _stage("execution", "running")
        human_summary = summarize_tool_result(
            prompt=payload.prompt,
            tool_name=tool_name,
            result=tool_result,
        )
        yield _stage("execution", "ok")

        logger.info(
            "stream allowed user=%s tool=%s summary_chars=%s",
            payload.username, tool_name,
            len(human_summary) if human_summary else 0,
        )

        yield _sse({
            "type": "result", **base,
            "tool_name": tool_name, "arguments": arguments,
            "policy_decision": "ALLOW",
            "authorization_stage": "success",
            "tool_output": tool_result,
            "human_summary": human_summary,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # don't let a proxy buffer the stream
        },
    )