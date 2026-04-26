import json
from openai import OpenAI

from app.core.config import settings
from app.mcp.server import mcp

client = OpenAI(api_key=settings.OPENAI_API_KEY)

# Parameters that are injected by the server/gateway and must never be
# exposed to the LLM or accepted from it. `username` comes from the
# authenticated session; `raw_prompt` is injected by the web gateway to
# feed the intent-alignment stage in the policy engine.
RESERVED_PARAMS: tuple[str, ...] = ("username", "raw_prompt")

SYSTEM_PROMPT = """
You are a tool-selection assistant for a secure enterprise database system.

Your job is ONLY to choose the single most appropriate function tool for the user's request.
Do not invent new tools.
Do not explain the answer in natural language if a tool is appropriate.
Prefer the safest and most specific tool.
If no tool is appropriate, do not call any tool.

IMPORTANT: Never provide a value for the `username` or `raw_prompt`
parameters. Both are injected by the server from the authenticated
session and the original request. Focus only on the operational
parameters (employee_id, new_salary, etc.).
"""


def _extract_tool_parameters(tool) -> dict:
    """
    Extract a JSON-schema parameters object from a FastMCP tool across
    SDK shape differences.
    """
    for attr in ("parameters", "input_schema", "inputSchema"):
        value = getattr(tool, attr, None)
        if isinstance(value, dict):
            return value

    if hasattr(tool, "model_dump"):
        dumped = tool.model_dump(by_alias=True)
        for key in ("parameters", "input_schema", "inputSchema"):
            value = dumped.get(key)
            if isinstance(value, dict):
                return value

    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def _strip_reserved_params_from_schema(schema: dict) -> dict:
    """
    Hide server-injected parameters from the LLM's tool schema.

    - `username`: identity is established by the authenticated session.
    - `raw_prompt`: the original natural-language request, injected by
       the web gateway to drive the intent-alignment policy stage. The
       model must never see or invent a value for it.
    """
    if not isinstance(schema, dict):
        return schema

    clean = dict(schema)
    props = dict(clean.get("properties", {}))
    for reserved in RESERVED_PARAMS:
        props.pop(reserved, None)
    clean["properties"] = props

    required = [r for r in clean.get("required", []) if r not in RESERVED_PARAMS]
    clean["required"] = required

    return clean


def build_openai_tools_from_mcp():
    """
    Convert registered MCP tools into the format expected by OpenAI.
    Uses the currently registered FastMCP tools.
    """
    tools = []

    for tool in mcp._tool_manager._tools.values():
        parameters = _extract_tool_parameters(tool)
        parameters = _strip_reserved_params_from_schema(parameters)

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": parameters,
                },
            }
        )

    return tools


def select_tool_from_prompt(prompt: str):
    """
    Send the user prompt to OpenAI and extract the selected tool and arguments.
    """
    tools = build_openai_tools_from_mcp()

    if not tools:
        return {
            "tool_name": None,
            "arguments": {},
            "raw_output_text": "No tools available from MCP registry.",
        }

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=tools,
            tool_choice="auto",
        )

        selected_tool_name = None
        selected_arguments = {}

        message = response.choices[0].message

        if message.tool_calls:
            tool_call = message.tool_calls[0]
            selected_tool_name = tool_call.function.name

            try:
                selected_arguments = (
                    json.loads(tool_call.function.arguments)
                    if tool_call.function.arguments
                    else {}
                )
            except json.JSONDecodeError:
                selected_arguments = {}

            # Defensive: drop any reserved params the LLM slipped in
            # despite the schema filtering and the system prompt.
            for reserved in RESERVED_PARAMS:
                selected_arguments.pop(reserved, None)

        return {
            "tool_name": selected_tool_name,
            "arguments": selected_arguments,
            "raw_output_text": message.content if message.content else "",
        }

    except Exception as e:
        return {
            "tool_name": None,
            "arguments": {},
            "raw_output_text": f"OpenAI error: {str(e)}",
        }


# ---------------------------------------------------------------------
# Natural-language response layer (functional req #4)
# ---------------------------------------------------------------------
# After a tool call succeeds, the raw tool output is almost always JSON.
# For a demo / for end users, a plain-language summary of that JSON is
# far more readable. This function asks the LLM to restate the result
# in the same language the user wrote the prompt in.
#
# Fail-safe: if the LLM call errors for any reason, we return None and
# the caller should just fall back to the raw JSON. We never let a
# summarization failure break the response path.

SUMMARY_SYSTEM_PROMPT = """
You are a response formatter for a secure enterprise database assistant.

You will be given:
- The user's original natural-language request.
- The name of the tool that was executed.
- The structured (JSON) result returned by that tool.

Your job is to restate the result for the user in clear, natural prose.

Rules:
- Reply in the SAME LANGUAGE the user used in their request (Hebrew if
  they wrote in Hebrew, English if they wrote in English, etc.).
- Be concise. 1-3 sentences is usually enough. For lists of records,
  a short summary plus a small list is fine.
- Do not invent data that is not in the JSON result. Do not speculate.
- Do not describe the tool or the system. Speak as if you are directly
  answering the user.
- If the JSON is empty, say so plainly.
- Do not wrap the answer in code blocks or JSON. Plain text only.
""".strip()


def summarize_tool_result(
    prompt: str,
    tool_name: str,
    result: object,
) -> str | None:
    """
    Produce a human-readable, same-language summary of a tool result.

    Returns None on any error so the caller can fall back to raw JSON.
    """
    try:
        if isinstance(result, (dict, list)):
            result_text = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            result_text = str(result)

        # Keep payload bounded — very large results would blow up the
        # context and cost. Truncate defensively.
        if len(result_text) > 6000:
            result_text = result_text[:6000] + "\n...[truncated]"

        user_msg = (
            f"User request:\n{prompt}\n\n"
            f"Tool executed: {tool_name}\n\n"
            f"Tool result (JSON):\n{result_text}\n\n"
            f"Now write a short, natural-language answer to the user."
        )

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        content = content.strip()
        return content or None

    except Exception:
        # Summarization is a nice-to-have. Never let it break the
        # request — the caller will fall back to the raw JSON.
        return None