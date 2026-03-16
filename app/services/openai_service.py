import json
from openai import OpenAI

from app.core.config import settings
from app.mcp.server import mcp_server

client = OpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are a tool-selection assistant for a secure enterprise database system.

Your job is ONLY to choose the single most appropriate function tool for the user's request.
Do not invent new tools.
Do not explain the answer in natural language if a tool is appropriate.
Prefer the safest and most specific tool.
If no tool is appropriate, do not call any tool.
"""


def build_openai_tools_from_mcp():
    """
    Convert registered MCP tools into the format expected by OpenAI chat.completions.
    """
    tools = []

    for tool in mcp_server.list_tools():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
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
            "raw_output_text": "No tools available from MCP registry."
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

        return {
            "tool_name": selected_tool_name,
            "arguments": selected_arguments,
            "raw_output_text": message.content if message.content else ""
        }

    except Exception as e:
        return {
            "tool_name": None,
            "arguments": {},
            "raw_output_text": f"OpenAI error: {str(e)}"
        }