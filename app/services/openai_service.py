import json
from openai import OpenAI

from app.core.config import settings
from app.tools.definitions import TOOLS

client = OpenAI(api_key=settings.OPENAI_API_KEY)


SYSTEM_PROMPT = """
You are a tool-selection assistant for a secure enterprise database system.

Your job is ONLY to choose the most appropriate function tool for the user's request.
Do not invent new tools.
Do not explain the answer in natural language if a tool is appropriate.
Prefer the safest and most specific tool.
"""


def select_tool_from_prompt(user_prompt: str):
    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tools=TOOLS,
    )

    function_calls = [item for item in response.output if item.type == "function_call"]

    if not function_calls:
        return {
            "tool_name": None,
            "arguments": {},
            "raw_output_text": getattr(response, "output_text", "")
        }

    call = function_calls[0]

    return {
        "tool_name": call.name,
        "arguments": json.loads(call.arguments) if call.arguments else {},
        "raw_output_text": getattr(response, "output_text", "")
    }
