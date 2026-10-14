"""The MCP surface: each role's tools, as plain typed functions that return text (registry.py), and
the protocol server that serves a role's tools to an MCP client over stdio (server.py). The server is
imported on its own, as datum.mcp.server, so a tool never loads the SDK."""

from .registry import Registry, Tool, ToolError

__all__ = ["Registry", "Tool", "ToolError"]
