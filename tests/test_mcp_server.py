"""The MCP protocol server: a role's registered tools, listed and called through the protocol.

The server is built in this process and reached with the MCP SDK's own client: in memory in both
protocol eras (the initialize handshake of today's stdio clients, and the 2026-07-28 requests that
carry their own envelope), and once over stdio as `python -m babel.mcp.server` in a child process.
No live assistant and no model take part.
"""

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

import babel.mcp.server
from babel.mcp.server import ACTOR, main, open_role, server
from babel.record.store import RecordError, Store
from cs_briefs import REPLY
from domains.spare_parts.customer_service import INSTRUCTIONS, build
from domains.spare_parts.data import demo

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
DATA = demo()
#: both protocol eras an in-process client can open
MODES = ["legacy", "auto"]
#: the tools the brief names as writing to the record (`check` writes too: it keeps its result on the ticket)
WRITERS = ["open_consultation", "ask", "stopped", "propose_reply", "close", "release", "resume"]
#: one call, tool by tool, as the golden scenario makes it (tests/cs_scenario.py)
CALL = [
    ("search", {"text": "reclaim screw"}),
    ("open_consultation", {"customer": "C-300", "machine": "CH-02", "part": "SP-1601"}),
    ("ask", {"consultation": 1, "question": "Availability"}),
    ("stopped", {"consultation": 1, "state": "stopped"}),
    ("ask", {"consultation": 1, "question": "Availability"}),
    ("check", {"consultation": 1, "answer": REPLY}),
    ("propose_reply", {"consultation": 1, "answer": REPLY}),
    ("search", {"status": "in_progress"}),
]


def _role(path: Path, actor: str = "ville"):
    store = Store(path, clock=lambda: AT)
    store.add_user(actor, ["worker"])
    return store, build(store, DATA, actor=actor)


def _through(app, steps, mode: str = "legacy"):
    """Run `steps(client)` against the server in this process, through the SDK's in-memory client."""
    async def go():
        async with Client(app, mode=mode) as client:
            return await steps(client)
    return anyio.run(go)


@pytest.mark.parametrize("mode", MODES)
def test_every_registered_tool_is_listed_with_its_name_description_and_input_schema(tmp_path, mode):
    _, role = _role(tmp_path / "record.sqlite")

    async def steps(client):
        return (await client.list_tools()).tools, client.server_info, client.instructions

    listed, info, instructions = _through(server(role), steps, mode)
    assert [t.name for t in listed] == role.names()
    for tool, registered in zip(listed, role.tools()):
        assert (tool.name, tool.description, tool.input_schema) == (
            registered.name, registered.description, registered.schema), tool.name
    assert info.name == "datum"
    assert instructions == INSTRUCTIONS  # the role's instructions reach the assistant


def test_a_tool_that_writes_nothing_is_read_only_and_a_tool_that_writes_is_not(tmp_path):
    _, role = _role(tmp_path / "record.sqlite")

    async def steps(client):
        return {t.name: t.annotations for t in (await client.list_tools()).tools}

    annotations = _through(server(role), steps)
    assert [name for name, a in annotations.items() if a.read_only_hint] == ["search"]
    for name in WRITERS + ["check"]:
        assert annotations[name].read_only_hint is False, name
    assert {name: a.read_only_hint for name, a in annotations.items()} == {t.name: not t.writes for t in role.tools()}
    # every write is a journal entry and nothing is deleted; the record is the tools' whole world
    assert all(a.destructive_hint is False and a.open_world_hint is False for a in annotations.values())


@pytest.mark.parametrize("mode", MODES)
def test_a_call_through_the_server_gives_the_text_of_the_function_called_directly(tmp_path, mode):
    # two records alike: one is reached through the protocol, the other by calling each plain function
    _, served = _role(tmp_path / "served" / "record.sqlite")
    store, direct = _role(tmp_path / "direct" / "record.sqlite")

    async def steps(client):
        out = []
        for name, arguments in CALL:
            result = await client.call_tool(name, arguments)
            out.append((result.is_error, [c.type for c in result.content], result.content[0].text))
        return out

    results = _through(server(served), steps, mode)
    for (name, arguments), (error, kinds, text) in zip(CALL, results):
        assert (error, kinds) == (False, ["text"]), name
        assert text == direct[name].function(**arguments), name
    assert store.get(1)["status"] == "needs_input"  # the direct record took the same steps


def test_a_refusal_comes_back_as_a_tool_error_with_its_reason_and_changes_nothing(tmp_path):
    store, role = _role(tmp_path / "record.sqlite")

    async def steps(client):
        out = {}
        for label, name, arguments in [
            ("unknown customer", "open_consultation", {"customer": "Nobody"}),
            ("wrong type", "open_consultation", {"customer": 5}),
            ("no reason", "release", {"consultation": 1}),
            ("no such ticket", "resume", {"consultation": 99}),
            ("no such tool", "send", {}),
        ]:
            result = await client.call_tool(name, arguments)
            out[label] = (result.is_error, result.content[0].text)
        return out

    refused = _through(server(role), steps)
    assert refused == {
        "unknown customer": (True, "no customer 'Nobody': search for it, then use its id"),
        "wrong type": (True, "open_consultation: customer must be string, not 5"),
        "no reason": (True, "release: missing argument reason"),
        "no such ticket": (True, "unknown_item: no item #99"),
        "no such tool": (True, f"{role.name} has no tool 'send'; its tools are {', '.join(role.names())}"),
    }
    assert store.items() == []


def test_without_an_actor_the_tools_act_as_an_agent_added_once_and_a_named_actor_must_exist(tmp_path, capsys):
    path = tmp_path / "new" / "record.sqlite"
    first = open_role(path)
    assert first["open_consultation"].function("C-300", "CH-02").startswith(
        f"Consultation #1 opened: in_progress, with {ACTOR}.")
    store = Store(path)
    assert (store.user(ACTOR)["kind"], store.user(ACTOR)["roles"]) == ("agent", ("worker",))
    open_role(path)  # the agent is there already: nothing is added again
    assert [e["details"]["name"] for e in store.journal() if e["action"] == "user_added"] == [ACTOR]
    with pytest.raises(RecordError, match="unknown user 'anna'") as unknown:
        open_role(path, actor="anna")
    assert unknown.value.code == "unknown_user"
    assert main(["--store", str(path), "--actor", "anna"]) == 2
    assert "unknown_user: unknown user 'anna'" in capsys.readouterr().err
    store.add_user("anna", ["worker"])
    assert "with anna" in open_role(path, actor="anna")["open_consultation"].function("C-300", "CH-02")
    with pytest.raises(SystemExit) as wrong:
        main(["--store", str(path), "--role", "analyst"])
    assert wrong.value.code == 2


def test_python_m_babel_mcp_server_serves_the_role_over_stdio(tmp_path):
    path = tmp_path / "record.sqlite"
    process = StdioServerParameters(command=sys.executable, cwd=str(ROOT),
                                    args=["-m", "babel.mcp.server", "--store", str(path)])

    async def go():
        async with Client(process, mode="legacy") as client:
            names = [t.name for t in (await client.list_tools()).tools]
            opened = await client.call_tool("open_consultation", {"customer": "C-300", "machine": "CH-02"})
            return names, opened.content[0].text

    names, text = anyio.run(go)
    assert names == _role(tmp_path / "other.sqlite")[1].names()
    assert text.startswith(f"Consultation #1 opened: in_progress, with {ACTOR}.")
    assert Store(path).get(1)["created_by"] == ACTOR  # the call wrote to the store the command named


#: what the server module may import from the SDK: the low-level server, the stdio transport, the wire types
SDK = {"mcp_types", "mcp.server.lowlevel", "mcp.server.stdio"}
FORBIDDEN = {"urllib", "http", "socket", "ssl", "requests", "httpx", "httpx2", "subprocess", "multiprocessing",
             "uvicorn", "starlette", "anthropic", "openai", "ollama"}


def test_the_server_reaches_no_model_no_network_and_no_transport_but_stdio(tmp_path):
    tree = ast.parse(Path(babel.mcp.server.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module)
    assert {name for name in imported if name.split(".")[0] in ("mcp", "mcp_types")} == SDK
    assert not {name.split(".")[0] for name in imported} & FORBIDDEN
    _, role = _role(tmp_path / "record.sqlite")
    assert server(role).middleware == []  # the SDK's OpenTelemetry middleware is dropped
