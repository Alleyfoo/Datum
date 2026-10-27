"""Independent, read-only browser rendering probe for the local MCP Apps host."""
from pathlib import Path
from mcp.types import CallToolResult, TextContent

URI = "ui://datum/rendering-probe"


def register(apps):
    @apps.tool(name="datum_rendering_probe", resource_uri=URI,
               description="Open a synthetic rendering capability test; no business decisions or writes.")
    def rendering_probe() -> CallToolResult:
        rows = [{"id": i, "label": f"Synthetic row {i:04d}", "value": (i * 37) % 101}
                for i in range(1, 2001)]
        return CallToolResult(
            content=[TextContent(type="text", text="Synthetic rendering probe with 2,000 rows.")],
            structured_content={"rows": rows, "series": [12, 35, 23, 48, 31, 42, 18, 54]},
        )

    apps.add_html_resource(URI, Path(__file__).with_name("rendering_probe.html").read_text(encoding="utf-8"),
                           title="Datum — Rendering probe", prefers_border=True)
