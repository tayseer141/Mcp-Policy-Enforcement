"""
Pydantic request/response models for the tool-execution API.

These define the public contract of POST /api/v1/execute. Any client
(the HTML console, a CLI, automated tests, a future React frontend,
another service) speaks JSON to this endpoint and receives structured
data back. There is no HTML in the API path.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """A natural-language request to run against the policy-enforced MCP layer."""

    username: str = Field(
        ...,
        description="Identity of the caller. Comes from the authenticated session in the UI; in tests it is supplied directly.",
        min_length=1,
    )
    prompt: str = Field(
        ...,
        description="The user's natural-language request. Used by the LLM for tool selection and again by the policy engine for intent alignment.",
        min_length=1,
    )


class ExecuteResponse(BaseModel):
    """
    The full structured outcome of one execute call.

    Always returned with HTTP 200 (the request was processed). The
    `policy_decision` field carries the actual access-control verdict
    so clients can branch on it without inspecting status codes.
    """

    # --- Echo of the request (handy for logging clients) ---
    username: str
    prompt: str

    # --- LLM tool selection stage ---
    tool_name: Optional[str] = Field(
        default=None,
        description="The tool the LLM chose. None if no tool matched the prompt.",
    )
    arguments: dict = Field(
        default_factory=dict,
        description="Arguments the LLM extracted for the chosen tool. Reserved params (username, raw_prompt) are stripped.",
    )

    # --- Policy engine outcome ---
    policy_decision: Literal["ALLOW", "DENY", "ERROR"]
    authorization_stage: str = Field(
        ...,
        description="Which pipeline stage produced the verdict: tool-selection | rbac | intent | policy | success | system.",
    )
    matched_policy: Optional[str] = Field(
        default=None,
        description="Name of the matched policy rule, when the policy stage produced the verdict.",
    )

    # --- On ALLOW ---
    tool_output: Optional[Any] = Field(
        default=None,
        description="Raw structured result from the tool (dict, list, or scalar). Only populated when policy_decision is ALLOW.",
    )
    human_summary: Optional[str] = Field(
        default=None,
        description="LLM-generated natural-language restatement of tool_output, in the user's language. None if summarization failed or was skipped.",
    )

    # --- On DENY / ERROR ---
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable reason the request was denied or failed. Comes verbatim from the policy engine on DENY (never paraphrased by an LLM, by design).",
    )