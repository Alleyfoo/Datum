"""Serve MCP on loopback with CORS limited to the local reference host.

The CLI's default HTTP endpoint has no browser CORS headers. This entry point
is only for the local basic-host experiment on port 8080.
"""
import uvicorn
from starlette.middleware.cors import CORSMiddleware

from server import mcp


app = CORSMiddleware(
    mcp.streamable_http_app(),
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Mcp-Session-Id", "Mcp-Protocol-Version", "Last-Event-ID"],
    expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
