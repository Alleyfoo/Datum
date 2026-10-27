import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client('http://127.0.0.1:8000/mcp') as transport:
        async with ClientSession(transport[0], transport[1]) as session:
            await session.initialize()
            print('TOOLS', [(t.name, t.meta) for t in (await session.list_tools()).tools])
            print('RESOURCES', [(r.uri, r.mime_type) for r in (await session.list_resources()).resources])
            for scenario in ('baseline', 'delivery', 'quarantine'):
                result = await session.call_tool('datum_visualize', {'scenario': scenario})
                print(scenario, 'isError', result.is_error, 'counts', result.structured_content.get('counts'), 'content', len(result.content))
            result = await session.read_resource('ui://datum/visual-lab')
            print('RESOURCE_BYTES', len(result.contents[0].text))

anyio.run(main)

