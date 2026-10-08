"""The MCP surface: each role's tools, as plain typed functions that return text."""

from .registry import Registry, Tool, ToolError

__all__ = ["Registry", "Tool", "ToolError"]
