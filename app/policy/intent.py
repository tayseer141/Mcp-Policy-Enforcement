"""
Intent Alignment Policy.

A guardrail beyond RBAC and argument-based rules: even if the LLM picks a
tool the user is authorized to call, we verify that the tool actually matches
what the user *asked for* in natural language.

This closes the gap highlighted in the alpha report: an LLM can translate a
prompt into a syntactically valid Tool Call that is RBAC-allowed but is
semantically a different action than the user intended.

Approach:
1. A small independent LLM classifier reads the raw prompt and emits one or
   more canonical intent tags: read, update, delete, admin, unknown.
2. Each tool declares which intent tags it legitimately serves.
3. A request is aligned iff the classifier's tags intersect with the tool's
   declared tags. Otherwise the call is blocked at stage="intent".

Fails closed: on classifier error or unrecognizable prompt, deny.
"""

import json
import logging
from typing import Tuple

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger("intent-policy")


# Map each registered MCP tool to the intent tags it legitimately serves.
# Keep this tight -- a loose mapping defeats the purpose.
TOOL_INTENT_MAP: dict[str, set[str]] = {
    "health_check":       {"read", "admin"},
    "get_employees":      {"read"},
    "get_employee_by_id": {"read"},
    "update_salary":      {"update"},
    "delete_employee":    {"delete"},
    "add_employee":       {"create"},
}

ALLOWED_INTENT_TAGS = {"read", "create", "update", "delete", "admin", "unknown"}


_client: OpenAI | None = None


def _openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


_CLASSIFIER_SYSTEM_PROMPT = (
    "You classify a short user request into one or more INTENT TAGS. "
    "Allowed tags: read, create, update, delete, admin, unknown. "
    "Rules:\n"
    "- 'read' = retrieve/show/list/find information, no mutation.\n"
    "- 'create' = add/insert a NEW record (e.g. add/hire a new employee).\n"
    "- 'update' = modify an existing record's field (salary, etc.).\n"
    "- 'delete' = remove one or more records.\n"
    "- 'admin' = manage roles, users, or permissions.\n"
    "- 'unknown' = greeting, chit-chat, empty, or not actionable.\n"
    "Pick the MINIMAL set of tags that truly fit. "
    'Respond with strict JSON: {"intents": ["tag", ...]}.'
)


def classify_intent(prompt: str) -> set[str]:
    """
    Ask the LLM to tag the user's natural-language request.

    Returns a set of intent tags from ALLOWED_INTENT_TAGS. On failure
    returns {'unknown'} so the alignment check fails closed.
    """
    if not prompt or not prompt.strip():
        return {"unknown"}

    try:
        resp = _openai_client().chat.completions.create(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        tags = {str(t).lower() for t in (data.get("intents") or [])}
        tags &= ALLOWED_INTENT_TAGS
        return tags or {"unknown"}
    except Exception as e:
        logger.warning("Intent classifier failed: %s", e)
        return {"unknown"}


def check_intent_alignment(
    tool_name: str, raw_prompt: str
) -> Tuple[bool, str, set[str], set[str]]:
    """
    Returns:
        (aligned, reason, extracted_tags, tool_tags)
    """
    tool_tags = TOOL_INTENT_MAP.get(tool_name, set())
    if not tool_tags:
        return (
            False,
            f"No intent mapping configured for tool '{tool_name}'. "
            "Request blocked by intent alignment (fail-closed).",
            set(),
            set(),
        )

    extracted = classify_intent(raw_prompt)

    if extracted == {"unknown"}:
        return (
            False,
            "Intent alignment failed: could not classify the user's intent "
            f"from the prompt. Expected one of {sorted(tool_tags)} for tool "
            f"'{tool_name}'. Please rephrase the request.",
            extracted,
            tool_tags,
        )

    if extracted & tool_tags:
        return (
            True,
            f"Intent aligned: user intent {sorted(extracted)} matches tool "
            f"'{tool_name}' {sorted(tool_tags)}.",
            extracted,
            tool_tags,
        )

    return (
        False,
        f"Intent mismatch: your prompt looks like a {sorted(extracted)} "
        f"request, but the LLM selected tool '{tool_name}' which serves "
        f"{sorted(tool_tags)}. Please rephrase your request more clearly.",
        extracted,
        tool_tags,
    )