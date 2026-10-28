"""Call one tool through local MCP for the reference-host integration test."""
import json
import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    name, args = sys.argv[1], json.loads(sys.argv[2])
    async with streamable_http_client('http://127.0.0.1:8000/mcp') as transport:
        async with ClientSession(transport[0], transport[1]) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
            if result.is_error:
                raise RuntimeError(str(result.content))
            print(json.dumps(result.structured_content, ensure_ascii=False))


anyio.run(main)
