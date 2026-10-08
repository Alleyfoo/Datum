"""A role's tools: plain typed functions that return text, described and called by name."""

from typing import Literal, Optional

import pytest

from babel.mcp import Registry, ToolError


def _role():
    role = Registry("example role", instructions="Use the tools.")

    @role.register
    def look(text: str, status: Optional[Literal["open", "closed"]] = None) -> str:
        """Find things."""
        return f"looked for {text!r} {status or 'any'}"

    @role.register(writes=True)
    def note(ticket: int, body: str) -> str:
        """Write a note on a ticket."""
        return f"#{ticket}: {body}"

    return role


def test_a_tool_is_described_from_its_signature_and_docstring():
    role = _role()
    assert role.names() == ["look", "note"]
    assert role.describe()[0] == {
        "name": "look", "description": "Find things.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {
            "text": {"type": "string"}, "status": {"type": "string", "enum": ["open", "closed"]}}},
    }
    assert role.describe()[1]["inputSchema"]["properties"] == {"ticket": {"type": "integer"},
                                                               "body": {"type": "string"}}
    assert [t.writes for t in role.tools()] == [False, True]


def test_a_tool_is_called_by_name_with_its_arguments_checked():
    role = _role()
    assert role.call("look", {"text": "screw"}) == "looked for 'screw' any"
    assert role.call("look", {"text": "screw", "status": None}) == "looked for 'screw' any"
    assert role.call("note", {"ticket": 3, "body": "called back"}) == "#3: called back"
    for name, arguments, message in [
        ("look", {}, "missing argument text"),
        ("look", {"text": "x", "colour": "red"}, "unknown argument colour"),
        ("look", {"text": 5}, "text must be string"),
        ("look", {"text": "x", "status": "waiting"}, "status must be one of open, closed"),
        ("note", {"ticket": "3", "body": "x"}, "ticket must be integer"),
        ("note", {"ticket": True, "body": "x"}, "ticket must be integer"),
        ("send", {}, "has no tool 'send'"),
    ]:
        with pytest.raises(ToolError, match=message):
            role.call(name, arguments)


def test_only_typed_documented_functions_that_return_text_are_tools():
    role = Registry("strict")

    def untyped(text) -> str:
        """Untyped."""
        return text

    def no_text(text: str) -> int:
        """Returns a number."""
        return 1

    def undocumented(text: str) -> str:
        return text

    def floats(amount: float) -> str:
        """A float."""
        return ""

    for function in (untyped, no_text, undocumented, floats):
        with pytest.raises(TypeError):
            role.register(function)
    assert role.names() == []


def test_a_role_has_each_tool_once():
    role = _role()

    def look(text: str) -> str:
        """Again."""
        return text

    with pytest.raises(ValueError, match="already has a tool look"):
        role.register(look)
