"""A role's tools: plain functions with typed signatures that return text, described for MCP.

The tool surface of Parts-Service-Desk desk/mcp_server.py (at 46c859a) was built on the MCP SDK.
The registry itself needs no dependency: it holds one role's tools, describes each for a client
(its name, its description and an input schema read from the signature) and calls a tool by name
with JSON arguments. The protocol server (server.py) serves a registry to an MCP client over stdio,
with the SDK. Which tools a role has is its registry, so a role's tool list is a policy, not a
separate process (build-plan G5).

No model is called inside a tool. Tools compute and record; the assistant on the other side of
the connection explains, and a person decides.
"""

from __future__ import annotations

import inspect
import types
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Union, get_args, get_origin, get_type_hints


class ToolError(ValueError):
    """A tool refused its input: the text says why, and what to do instead."""


_TYPES = {str: "string", int: "integer", bool: "boolean"}


def _schema(hint: Any) -> dict:
    """The JSON schema of one parameter's type: text, whole numbers, yes or no, one of a list."""
    if get_origin(hint) in (Union, types.UnionType):
        kinds = [a for a in get_args(hint) if a is not type(None)]
        if len(kinds) == 1:
            return _schema(kinds[0])
    if get_origin(hint) is Literal:
        values = list(get_args(hint))
        return {"type": _TYPES[type(values[0])], "enum": values}
    if hint in _TYPES:
        return {"type": _TYPES[hint]}
    raise TypeError(f"a tool parameter must be str, int, bool, a Literal or Optional of one, not {hint!r}")


@dataclass(frozen=True)
class Tool:
    name: str
    function: Callable[..., str]
    description: str
    #: whether the tool writes to the record; a reading tool changes nothing
    writes: bool
    schema: dict

    def describe(self) -> dict:
        """The tool as an MCP client lists it."""
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


def tool_of(function: Callable[..., str], *, name: Optional[str] = None, writes: bool = False) -> Tool:
    """Read a tool from a function: every parameter typed, text returned, a docstring as its description."""
    hints = get_type_hints(function)
    if hints.get("return") is not str:
        raise TypeError(f"{function.__name__} must be annotated to return str")
    properties, required = {}, []
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind not in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY):
            raise TypeError(f"{function.__name__}: *args and **kwargs are not tool parameters")
        if parameter.name not in hints:
            raise TypeError(f"{function.__name__}: parameter {parameter.name} has no type")
        properties[parameter.name] = _schema(hints[parameter.name])
        if parameter.default is parameter.empty:
            required.append(parameter.name)
    description = inspect.cleandoc(function.__doc__ or "")
    if not description:
        raise TypeError(f"{function.__name__} needs a docstring: it is the tool's description")
    schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
    return Tool(name or function.__name__, function, description, writes, schema)


class Registry:
    """One role's tools, in the order they were registered."""

    def __init__(self, name: str, instructions: str = ""):
        self.name = name
        self.instructions = instructions
        self._tools: Dict[str, Tool] = {}

    def register(self, function: Optional[Callable[..., str]] = None, *, name: Optional[str] = None,
                 writes: bool = False):
        """Add a tool; usable as ``@registry.register`` or ``@registry.register(writes=True)``."""
        def add(fn: Callable[..., str]) -> Callable[..., str]:
            tool = tool_of(fn, name=name, writes=writes)
            if tool.name in self._tools:
                raise ValueError(f"{self.name} already has a tool {tool.name}")
            self._tools[tool.name] = tool
            return fn
        return add(function) if function is not None else add

    def names(self) -> List[str]:
        return list(self._tools)

    def tools(self) -> List[Tool]:
        return list(self._tools.values())

    def __getitem__(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"{self.name} has no tool {name!r}; its tools are {', '.join(self._tools)}")
        return self._tools[name]

    def describe(self) -> List[dict]:
        return [tool.describe() for tool in self._tools.values()]

    def call(self, name: str, arguments: Optional[dict] = None) -> str:
        """Call a tool with JSON arguments, checked against its schema first."""
        tool = self[name]
        arguments = dict(arguments or {})
        properties, required = tool.schema["properties"], tool.schema["required"]
        unknown = sorted(set(arguments) - set(properties))
        missing = [p for p in required if p not in arguments]
        if unknown or missing:
            raise ToolError(f"{name}: " + "; ".join(
                ([f"unknown argument {', '.join(unknown)}"] if unknown else [])
                + ([f"missing argument {', '.join(missing)}"] if missing else [])))
        for key, value in arguments.items():
            wanted = properties[key]
            if value is None and key not in required:
                continue
            kind = {"string": str, "integer": int, "boolean": bool}[wanted["type"]]
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                raise ToolError(f"{name}: {key} must be {wanted['type']}, not {value!r}")
            if "enum" in wanted and value not in wanted["enum"]:
                raise ToolError(f"{name}: {key} must be one of {', '.join(map(str, wanted['enum']))}")
        text = tool.function(**arguments)
        if not isinstance(text, str):
            raise TypeError(f"{name} returned {type(text).__name__}, not text")
        return text
