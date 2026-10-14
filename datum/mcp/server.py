"""The MCP protocol server: one role's registered tools, served to an MCP client over stdio.

    python -m datum.mcp.server --store PATH [--role customer-service] [--actor NAME]

Wiring only. The tools are the role's registry (registry.py): each is listed with the name, the
description and the input schema the registry reads from its function, and a call goes to the
registry, which checks the arguments against that schema, runs the plain function and returns its
text. The text goes back unchanged. A refusal (a ToolError from the registry or the role, a
RecordError from the record) goes back as a tool error with its reason, so the assistant can read
it and correct the call. No rule, check, text or state is made here.

A tool's annotations follow the registry's `writes` flag (the tiers of the earlier servers, declared
in the protocol so a client can see them without trusting a name): a tool that writes nothing is
read-only; one that writes to the record (a ticket, a journal entry, a check, a proposal) is not
read-only, and is additive only, since every write is a journal entry and nothing is deleted. No
tool reaches an open world: the record and the synthetic company are the whole of it.

The server calls no model and sends nothing outside the process: it reads requests from stdin and
writes replies to stdout, the pipe of the client that started it. There is no network transport,
and the SDK's OpenTelemetry middleware is dropped, so no span leaves the process even where an
exporter is configured. Who the tools act as is one user of the record, `--actor`: there is no
authentication (build-plan G4), and a role's tool list is its policy (G5).

Origin: Parts-Service-Desk desk/mcp_server.py (its READ and QUEUE annotations) and
Shopflow-furniture src/shopflow/mcp_server.py (tiers declared in the protocol, R13), both built on
the MCP Python SDK 2.2.0, read and not copied (docs/provenance.md). Both declare each tool with the
SDK's decorator, which reads its own schema from the function; here the SDK's low-level server
lists the registry's tools as they are, so the schema a client is shown is the one each call is
checked against.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from importlib import metadata
from pathlib import Path
from typing import Callable, List, Optional

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from datum.record.store import RecordError, Store

from .registry import Registry, ToolError

NAME = "datum"
#: the roles this server serves: a role's name, and where the function that builds its registry is,
#: build(store, *, actor) -> Registry. The core imports no domain pack; the entry point names them here
ROLES = {"customer-service": "domains.spare_parts.customer_service:build"}
ROLE = "customer-service"
#: who the tools act as when no --actor is given: the assistant on the other side of the connection,
#: an agent with the worker role, added to the record the first time it is used
ACTOR = "mcp-consultant"
#: the refusals a tool gives for the assistant to correct; anything else is an error of the server
REFUSALS = (ToolError, RecordError)

READS = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITES = types.ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                               open_world_hint=False)


def _version() -> str:
    try:
        return metadata.version(NAME)
    except metadata.PackageNotFoundError:  # run from a checkout that is not installed
        return ""


def tools(registry: Registry) -> List[types.Tool]:
    """The registry's tools as an MCP client lists them, in the order they were registered."""
    return [types.Tool(name=tool.name, description=tool.description, input_schema=tool.schema,
                       annotations=WRITES if tool.writes else READS)
            for tool in registry.tools()]


def _text(text: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def refusal(error: Exception) -> str:
    """A refusal as the assistant reads it: the record's code when it has one, then the reason."""
    code = getattr(error, "code", None)
    return f"{code}: {error}" if code else str(error)


def server(registry: Registry) -> Server:
    """The MCP server of one role: its registry's tools, each call answered by the registry."""
    listed = tools(registry)

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[tool.model_copy(deep=True) for tool in listed])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        # in the event loop, so the calls of a connection run one at a time, in the order they came
        try:
            return _text(registry.call(params.name, params.arguments or {}))
        except REFUSALS as error:
            return _text(refusal(error), error=True)

    app = Server(NAME, version=_version(), title=f"Datum: {registry.name}",
                 instructions=registry.instructions or None, on_list_tools=list_tools, on_call_tool=call_tool)
    app.middleware = []  # no OpenTelemetry span: nothing leaves the process
    return app


def builder(role: str) -> Callable[..., Registry]:
    """The function that builds a role's registry."""
    module, _, function = ROLES[role].partition(":")
    return getattr(importlib.import_module(module), function)


def open_role(store_path, role: str = ROLE, actor: Optional[str] = None) -> Registry:
    """A role's registry on the store at `store_path` (created when new), acting as `actor`. Without
    an actor the tools act as ACTOR, added to the store when it is not there yet; a named actor must
    already be a user of the store, since a command line never adds a person to the record."""
    store = Store(store_path)
    if actor is None:
        actor = ACTOR
        try:
            store.user(ACTOR)
        except RecordError:
            store.add_user(ACTOR, ["worker"], kind="agent")
    return builder(role)(store, actor=actor)


async def serve(registry: Registry) -> None:
    """Serve one role over this process's stdin and stdout until the client closes the pipe."""
    app = server(registry)
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def main(argv: Optional[List[str]] = None) -> int:
    """Serve the role the command line names; return the exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m datum.mcp.server",
        description="Serve one role's tools to an MCP client over stdio. Synthetic data only; no model is called.")
    parser.add_argument("--store", required=True, type=Path,
                        help="the ticket store, a SQLite file; a new one is created if there is none")
    parser.add_argument("--role", default=ROLE, choices=sorted(ROLES), help=f"the role whose tools are served (default {ROLE})")
    parser.add_argument("--actor", default=None,
                        help=f"the user of the record the tools act as; default {ACTOR}, an agent with the worker role")
    args = parser.parse_args(argv)  # wrong arguments: the usage and the error on stderr, exit code 2
    new = not args.store.exists()
    try:
        registry = open_role(args.store, args.role, args.actor)
    except RecordError as error:
        print(f"{parser.prog}: {refusal(error)}", file=sys.stderr)
        return 2
    print(f"{NAME}: the {args.role} tools ({', '.join(registry.names())}) act as {args.actor or ACTOR} on "
          f"{'a new store at ' if new else ''}{args.store}, over stdio", file=sys.stderr)
    anyio.run(serve, registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
