"""
Live smoke test against a running MCP server (docker compose up).

Not run by pytest in CI -- it needs the server on localhost:8001. It also
demonstrates the gateway authentication: without the x-mcp-gateway-key
header the server answers 401 and no session can be established.
"""

import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = "http://localhost:8001/mcp"
GATEWAY_HEADERS = {
    "x-mcp-gateway-key": os.getenv("MCP_GATEWAY_KEY", "dev-gateway-key-change-me")
}


async def main():
    async with streamablehttp_client(MCP_URL, headers=GATEWAY_HEADERS) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:")
            for tool in tools.tools:
                print("-", tool.name)

            result = await session.call_tool(
                "health_check",
                {"username": "admin_user"},
            )
            print("\nHEALTH_CHECK RESULT:")
            print(result)


if __name__ == "__main__":
    asyncio.run(main())