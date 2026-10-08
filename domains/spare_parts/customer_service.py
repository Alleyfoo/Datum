"""The customer-service role for spare parts: the tools for one customer call, registered for MCP.

    search(text, status?)   find a customer, machine or part (one match opens, several are listed,
                            none is reported), or tickets by status: open, in_progress, closed

Ported from Parts-Service-Desk desk/mcp_server.py at 46c859a (origin in docs/provenance.md) and
rewritten on this repository's company data, ticket store and approval queue. The lab's menu tools
(list_countries, list_companies, show_plant, show_machine) become one search with the 0/1/many rule
of docs/interaction.md: the plant view and the machine card are what a match opens.

Every tool is a plain function with a typed signature that returns text, and acts as the one named
user the role is built for (there is no authentication, build-plan G4). No tool calls a model, reads
a clock or draws a random number: the same record and arguments give the same text.
"""

from __future__ import annotations

from typing import List, Literal, NamedTuple, Optional

from babel.mcp import Registry, ToolError
from babel.record import consultations
from babel.record.store import Store

from .data import WAREHOUSES, ServiceData, demo
from .tools import due_date
from .views import MARK, machine_card, machine_status, plant_view
from .world import AS_OF

INSTRUCTIONS = """\
You are the consultant at an industrial spare parts service desk. The data is synthetic.

Start with search. One match opens its card; several are listed for the person to choose, and you
never choose for them; none is reported. Show cards exactly as returned, in a code block.
"""

Status = Literal["open", "in_progress", "closed"]


class Thing(NamedTuple):
    """Something a person can search for: a customer, a machine or a part."""

    kind: str
    key: str
    name: str
    #: whose it is (a machine's customer) or where it is (a customer's site); empty for a part
    owner: str
    #: a machine's spare-part status mark; empty for the others
    mark: str
    #: the words searched: id, name or description, and a customer's site
    words: str


def things(data: ServiceData) -> List[Thing]:
    """Customers, machines and parts, each in the company's order."""
    out = [Thing("customer", c.customer_id, c.name, c.site, "", f"{c.customer_id} {c.name} {c.site}".lower())
           for c in data.customers.values()]
    out += [Thing("machine", m.machine_id, m.name, data.customers[m.customer_id].name,
                  MARK[machine_status(data, m.machine_id)], f"{m.machine_id} {m.name}".lower())
            for m in data.machines.values()]
    out += [Thing("part", p.part_no, p.description, "", "", f"{p.part_no} {p.description}".lower())
            for p in data.parts.values()]
    return out


def matches(data: ServiceData, text: str) -> List[Thing]:
    """What a search finds. An id typed exactly is one match by definition; otherwise every word of
    the text must appear in a thing's id, name, description or site, in any case."""
    query = text.strip().lower()
    exact = [t for t in things(data) if t.key.lower() == query]
    if exact:
        return exact
    words = query.split()
    return [t for t in things(data) if words and all(w in t.words for w in words)]


def _row(n: int, thing: Thing) -> str:
    """One match in a list: kind, id, name, owner and status, so matches can be told apart. A name
    is cut only where a column follows it; a part's description is the end of its line, kept whole."""
    if not (thing.owner or thing.mark):
        return f"{n:>2}  {thing.kind:<9}{thing.key:<9}{thing.name}"
    name = thing.name if len(thing.name) <= 26 else thing.name[:25] + "…"
    return f"{n:>2}  {thing.kind:<9}{thing.key:<9}{name:<27}{thing.owner:<23}{thing.mark}".rstrip()


def part_card(data: ServiceData, part_no: str) -> str:
    """A part: lead time and interval, stock per warehouse, orders on the way, substitutes, and the
    machines that use it with their due dates (as the machine card states them)."""
    p = data.parts[part_no]
    every = f"replaced every {p.service_interval_months} months" if p.service_interval_months else "replaced on failure"
    orders = [o for o in data.incoming if o.part_no == part_no and o.due >= AS_OF]
    lines = [f"{p.part_no} {p.description} · {p.category.lower()} · lead time {p.lead_time_days} days · {every}", "",
             "On hand      " + "   ".join(f"{w} {data.on_hand(part_no, w)}" for w in WAREHOUSES),
             "On order     " + ("; ".join(f"{o.po}: {o.qty} to {o.warehouse}, due {o.due.isoformat()}"
                                          for o in orders) or "nothing"),
             "Substitutes  " + (", ".join(p.substitutes) or "none approved"),
             "", f"{'#':>2}  {'MACHINE':<9}{'CUSTOMER':<22}{'INST':>4}  DUE"]
    used = [b for b in data.bom if b.part_no == part_no]
    for i, b in enumerate(used, 1):
        when = due_date(data, b)
        note = ("" if when is None else f"overdue since {when.isoformat()}" if when < AS_OF
                else f"due {when.isoformat()}" if (when - AS_OF).days <= 90 else "")
        customer = data.customers[data.machines[b.machine_id].customer_id].name
        lines.append(f"{i:>2}  {b.machine_id:<9}{customer:<22}{b.qty_installed:>4}  {note}".rstrip())
    if not used:
        lines.append("    no machine has this part on its parts list")
    return "\n".join(lines)


def card(data: ServiceData, thing: Thing) -> str:
    """What one match opens: a customer's plant, a machine's card, a part's card."""
    if thing.kind == "customer":
        return (plant_view(data, thing.key) + "\n\n"
                + f'To start the call: open_consultation("{thing.key}", machine), with a machine of the plant.')
    if thing.kind == "machine":
        m = data.machines[thing.key]
        return (machine_card(data, thing.key) + "\n\n"
                + f"Customer: {thing.owner} ({m.customer_id}). To start the call: "
                f'open_consultation("{m.customer_id}", "{m.machine_id}", part) with a part of the card, '
                "or without a part for the service demand of the whole machine.")
    return part_card(data, thing.key)


def search_things(data: ServiceData, text: str) -> str:
    label = f'search "{text}"'
    found = matches(data, text)
    if not found:
        return (f"{label}: no match among customers, machines and parts. Nothing is opened; "
                "ask the person for an id or other words.")
    if len(found) == 1:
        return f"{label}: 1 match, opened.\n\n" + card(data, found[0])
    return "\n".join([f"{label}: {len(found)} matches. Which one?", ""]
                     + [_row(n, t) for n, t in enumerate(found, 1)]
                     + ["", "The person picks one; search its id to open it."])


def search_tickets(store: Store, text: str, status: str) -> str:
    if status not in consultations.STATUSES:
        raise ToolError(f"status must be one of {', '.join(consultations.STATUSES)}, not {status!r}")
    words = text.lower().split()
    found = [t for t in consultations.tickets(store, status) if all(w in t["title"].lower() for w in words)]
    label = f'search "{text}" with status {status}' if words else f"search status {status}"
    if not found:
        return f"{label}: no ticket."
    if len(found) == 1:
        return f"{label}: 1 ticket, shown; viewing it changes nothing.\n\n" + consultations.ticket_card(store, found[0])
    return "\n".join([f"{label}: {len(found)} tickets. Which one?", ""]
                     + [f"{n:>2}  {consultations.ticket_line(t)}" for n, t in enumerate(found, 1)])


def build(store: Store, data: Optional[ServiceData] = None, *, actor: str) -> Registry:
    """The role's tools, acting as ``actor``: a user of the record (a worker, or an approver who works)."""
    data = data or demo()
    store.user(actor)
    role = Registry("spare-parts customer service", INSTRUCTIONS)

    @role.register
    def search(text: str = "", status: Optional[Status] = None) -> str:
        """Find a customer, machine or part by id, name or description. One match opens its card,
        several are listed for the person to choose (never choose for them), none is reported. With
        status (open, in_progress or closed), list tickets of that status instead, narrowed by text
        if given: "what is waiting" is search(status="open"). Writes nothing."""
        if status is not None:
            return search_tickets(store, text, status)
        if not text.strip():
            raise ToolError("search needs words or an id, or a status to list tickets")
        return search_things(data, text)

    return role
