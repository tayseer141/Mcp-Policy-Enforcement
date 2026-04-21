import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://localhost:8001/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:")
            for tool in tools.tools:
                print("-", tool.name)

            result = await session.call_tool(
                "health_check",
                {"username": "admin"},
            )
            print("\nHEALTH_CHECK RESULT:")
            print(result)


if __name__ == "__main__":
    asyncio.run(main())