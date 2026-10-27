"""MCP Apps wrapper for the Datum Visual Lab.

Requires the official MCP Python SDK v2 (``pip install 'mcp>=2,<3'``).
The browser-only visualizer works without this dependency.

Run from this directory:
    mcp run server.py --transport streamable-http

Then test with an MCP Apps-compatible host using tool ``datum_visualize``.
"""
from pathlib import Path
from typing import Literal

from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from datum_engine import evaluate, summarize

APP_URI = "ui://datum/visual-lab"
HTML_PATH = Path(__file__).with_name("app.template.html")

apps = Apps()


@apps.tool(
    name="datum_visualize",
    resource_uri=APP_URI,
    description=("Open Datum's read-only interactive spare-parts analysis with a searchable "
                 "inventory, graph, conflicting claims, decision receipts, and scenario simulator. "
                 "All data is synthetic; no ERP write-back."),
)
def datum_visualize(
    scenario: Literal["baseline", "delivery", "quarantine"] = "baseline",
) -> CallToolResult:
    """Return a plain-language assessment plus structured data for the embedded App."""
    data = evaluate(scenario)
    return CallToolResult(
        content=[TextContent(type="text", text=summarize(data))],
        structured_content=data,
    )


apps.add_html_resource(
    APP_URI,
    HTML_PATH.read_text(encoding="utf-8").replace("__DATA_JSON__", "{}"),
    title="DATUM — Visual Lab",
    prefers_border=True,
)

mcp = MCPServer("datum-visual-lab", extensions=[apps])

