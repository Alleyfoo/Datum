"""The customer-service role for spare parts: the tools for one customer call, registered for MCP.

    search(text, status?)          find a customer, machine or part (one match opens, several are
                                   listed, none is reported), or tickets by status
    open_consultation(customer, machine?, part?)
                                   start the call's consultation: its own ticket, in_progress
    ask(consultation, question)    Availability, Lead time or Service demand: the facts the tools
                                   produce, the rule that decides, and the receipt
    stopped(consultation, state)   the person's answer, stopped or planned; never guessed, and
                                   required before an availability answer
    check(consultation, answer)    the answer checks on a draft, kept on the ticket
    propose_reply(consultation, answer)
                                   the reply queued for an approver; nothing is sent
    release(consultation, reason)  hand the call back without a decision: open again, everything
                                   on it kept, and the reason required
    resume(consultation)           take up an open call (or one whose lease ran out) as it was
                                   left; a closed one is not resumed

Ported from Parts-Service-Desk desk/mcp_server.py at 46c859a (origin in docs/provenance.md) and
rewritten on this repository's company data, ticket store and approval queue. The lab's menu tools
(list_countries, list_companies, show_plant, show_machine) become one search with the 0/1/many rule
of docs/interaction.md: the plant view and the machine card are what a match opens. ask_question
becomes ask and stopped, check_answer becomes check, and propose_customer_reply becomes
propose_reply, which uses the approval queue instead of the lab's proposals file. release and
resume are new: the owner's answer to P26 (build-plan section 25).

Every tool is a plain function with a typed signature that returns text, and acts as the one named
user the role is built for (there is no authentication, build-plan G4). No tool calls a model, reads
a clock or draws a random number: the same record and arguments give the same text.
"""

from __future__ import annotations

from typing import List, Literal, NamedTuple, Optional

from babel.checks import check_answer, customer_part, describe
from babel.mcp import Registry, ToolError
from babel.record import consultations
from babel.record.store import Store

from . import tools
from .data import WAREHOUSES, ServiceData, demo
from .tools import due_date
from .views import MARK, machine_card, machine_status, plant_view
from .world import AS_OF

INSTRUCTIONS = """\
You are the consultant at an industrial spare parts service desk. The data is synthetic.

Start with search. One match opens its card; several are listed for the person to choose, and you
never choose for them; none is reported. Show cards exactly as returned, in a code block.

open_consultation starts the call's ticket. ask returns FACTS and a receipt. Availability needs the
person's answer first: ask the person whether the machine has stopped, record it with stopped, and
never guess it, even when the call already said so.

Explain the FACTS in three parts: CUSTOMER ANSWER (2-3 sentences for the customer), SITUATION and
RECOMMENDATION. Use only the FACTS, copy dates and quantities exactly as written, follow the
RECOMMENDED PLAN, and never name other customers or internal stock problems in the CUSTOMER ANSWER.
Run check on your draft and fix what it flags, then propose_reply.

If the call cannot be finished now, release it with the reason (for example, the customer will call
back); nothing on it is lost. When the call is taken up again, resume it by its number: it comes
back as it was left, with who released it and why. A closed consultation is not resumed.

You cannot send anything to a customer and cannot approve anything: a named approver decides on the
reply outside this chat.
"""

Status = Literal["open", "in_progress", "closed", "finished"]
Question = Literal["Availability", "Lead time", "Service demand"]
State = Literal["stopped", "planned"]

#: the person's answer to "Has the machine stopped?": the situation it means, and how it is recorded
STATES = {
    "stopped": ("breakdown", "machine stopped: yes (breakdown)"),
    "planned": ("planned", "machine stopped: no (planned service)"),
}


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
    query, every = text.strip().lower(), things(data)
    exact = [t for t in every if t.key.lower() == query]
    if exact:
        return exact
    words = query.split()
    return [t for t in every if words and all(w in t.words for w in words)]


def _row(n: int, thing: Thing) -> str:
    """One match in a list: kind, id, name, owner and status, so matches can be told apart. A name
    is cut only where a column follows it; a part's description is the end of its line, kept whole."""
    if not (thing.owner or thing.mark):
        return f"{n:>2}  {thing.kind:<9}{thing.key:<9}{thing.name}"
    name = thing.name if len(thing.name) <= 26 else thing.name[:25] + "…"
    return f"{n:>2}  {thing.kind:<9}{thing.key:<9}{name:<27}{thing.owner:<23}{thing.mark}".rstrip()


def _due_note(data: ServiceData, line) -> str:
    """A line's due date as the machine card states it: overdue, due within the horizon, or nothing."""
    when = due_date(data, line)
    if when is None:
        return ""
    if when < AS_OF:
        return f"overdue since {when.isoformat()}"
    return f"due {when.isoformat()}" if (when - AS_OF).days <= tools.HORIZON_DAYS else ""


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
        customer = data.customers[data.machines[b.machine_id].customer_id].name
        lines.append(f"{i:>2}  {b.machine_id:<9}{customer:<22}{b.qty_installed:>4}  {_due_note(data, b)}".rstrip())
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


def _customer(data: ServiceData, customer: str) -> str:
    """A customer's id from its id or its name, in any case."""
    wanted = customer.strip().lower()
    for c in data.customers.values():
        if wanted in (c.customer_id.lower(), c.name.lower()):
            return c.customer_id
    raise ToolError(f"no customer {customer!r}: search for it, then use its id")


def _subject(data: ServiceData, customer: str, machine: Optional[str], part: Optional[str]) -> dict:
    """The call's subject, checked against the company: the machine is the customer's, the part is
    on the machine's parts list."""
    cid = _customer(data, customer)
    if part and not machine:
        raise ToolError("a part needs its machine: open_consultation(customer, machine, part)")
    if machine:
        m = data.machines.get(machine)
        if m is None or m.customer_id != cid:
            raise ToolError(f"{data.customers[cid].name} has no machine {machine!r}: search the customer to see its plant")
        if part and part not in [b.part_no for b in data.bom_of(machine)]:
            raise ToolError(f"{part!r} is not on the parts list of {machine}: search {machine} to see its card")
    return {"customer": cid, "machine": machine or None, "part": part or None}


def _title(data: ServiceData, subject: dict) -> str:
    parts = [data.customers[subject["customer"]].name]
    if subject["machine"]:
        parts.append(f"{subject['machine']} {data.machines[subject['machine']].name}")
    if subject["part"]:
        parts.append(f"{subject['part']} {data.parts[subject['part']].description}")
    return "Consultation: " + " · ".join(parts)


def _questions(number: int, subject: dict) -> str:
    """The questions that apply to the call's subject, and what each needs first."""
    machine, part = subject["machine"], subject["part"]
    if not machine:
        return "Questions are about a machine: open a consultation with one of the plant's machines."
    if not part:
        return (f'Ask: ask({number}, "Service demand") for the whole of {machine}. Availability and Lead time '
                "need a part: open a consultation with one.")
    return (f'Ask: ask({number}, "Availability"), ask({number}, "Lead time") or ask({number}, "Service demand"). '
            f"Availability needs the person's answer first: ask them whether {machine} has stopped and record it "
            f'with stopped({number}, "stopped") or stopped({number}, "planned"). Never guess it.')


def _ask_person(number: int, entry_n: int, title: str, machine: str) -> str:
    """The question for the person, returned in place of an answer."""
    return "\n".join([
        f"#{number} question {entry_n}: {title} waits for the person. No answer is given without it.",
        "",
        f"Has {machine} stopped? Ask the person; do not guess it, even if the call already said so.",
        "  stopped   yes: it has stopped and waits for this part (a breakdown)",
        "  planned   no: the part is for planned service, and the machine runs",
        "",
        f'Record the answer with stopped({number}, "stopped") or stopped({number}, "planned"), '
        f'then ask({number}, "Availability") again.',
    ])


def build(store: Store, data: Optional[ServiceData] = None, *, actor: str) -> Registry:
    """The role's tools, acting as ``actor``: a user of the record (a worker, or an approver who works)."""
    data = data or demo()
    store.user(actor)
    role = Registry("spare-parts customer service", INSTRUCTIONS)

    def latest(item: dict) -> dict:
        entry = consultations.latest_answer(item)
        if entry is None:
            raise ToolError(f"#{item['number']} has no answer yet: ask a question first; its facts are what "
                            "an answer is checked against")
        return entry

    @role.register
    def search(text: str = "", status: Optional[Status] = None) -> str:
        """Find a customer, machine or part by id, name or description. One match opens its card,
        several are listed for the person to choose (never choose for them), none is reported. With
        status (open, in_progress, closed or finished), list tickets of that status instead, narrowed
        by text if given: "what is waiting" is search(status="open"); in_progress also lists the
        tickets whose reply waits for an approver, marked so; closed ones could not be finished, and
        finished ones are done, with an approver's decision. Writes nothing."""
        if status is not None:
            return search_tickets(store, text, status)
        if not text.strip():
            raise ToolError("search needs words or an id, or a status to list tickets")
        return search_things(data, text)

    @role.register(writes=True)
    def open_consultation(customer: str, machine: Optional[str] = None, part: Optional[str] = None) -> str:
        """Start the call's consultation: its own ticket, opened to you (in_progress). customer is an
        id or a name; machine must be the customer's and part must be on the machine's parts list.
        Returns the ticket number, the card and the questions that apply."""
        subject = _subject(data, customer, machine, part)
        title = _title(data, subject)
        item = consultations.start(store, actor, title, subject=subject,
                                   body=f"A customer call, opened by {actor}.")
        number = item["number"]
        lines = [f"Consultation #{number} opened: in_progress, with {actor}. It is this call's ticket.", title, ""]
        if subject["machine"]:
            lines += [machine_card(data, subject["machine"]), ""]
        else:
            lines += [plant_view(data, subject["customer"]), ""]
        lines.append(_questions(number, subject))
        return "\n".join(lines)

    @role.register(writes=True)
    def stopped(consultation: int, state: State) -> str:
        """Record the person's answer to "Has the machine stopped?": stopped (a breakdown: it waits
        for the part) or planned (planned service: it runs). Only the person knows it: ask them and
        never guess it. Required before an availability answer."""
        if state not in STATES:
            raise ToolError(f"state must be stopped or planned, not {state!r}")
        item = consultations.get(store, consultation)
        machine = item["data"]["subject"]["machine"]
        if not machine:
            raise ToolError(f"#{consultation} has no machine to have stopped")
        situation, text = STATES[state]
        consultations.person_fact(store, consultation, actor, "stopped", state, text)
        said = ("has stopped and waits for the part (breakdown)" if state == "stopped"
                else "runs; the part is for planned service")
        return (f"Recorded on #{consultation}: {machine} {said}, as {actor} reports from the person. "
                f'The {situation} rule applies to ask({consultation}, "Availability").')

    @role.register(writes=True)
    def ask(consultation: int, question: Question) -> str:
        """Answer one question with the facts the tools produce and the rule that decides:
        Availability or Lead time of the consultation's part, or Service demand for its machine.
        Availability needs the person's answer (stopped) first; without it the question for the
        person comes back instead of an answer, and waits on the ticket. Returns the FACTS to
        explain and the answer's receipt."""
        name = {q.lower(): q for q in tools.QUESTIONS}.get(str(question).strip().lower())
        if name is None:
            raise ToolError(f"question must be one of {', '.join(tools.QUESTIONS)}, not {question!r}")
        item = consultations.get(store, consultation)
        subject = item["data"]["subject"]
        machine, part = subject["machine"], subject["part"]
        if not machine:
            raise ToolError(f"#{consultation} has no machine: questions are about a machine; "
                            "open a consultation with one")
        needs_part = tools.QUESTIONS[name][1]
        if needs_part and not part:
            raise ToolError(f"{name} needs a part, and #{consultation} is about the whole of {machine}: "
                            f'ask({consultation}, "Service demand"), or open a consultation with a part')
        title = f"{name} of {part} for {machine}" if needs_part else f"Service demand for {machine}"
        uses: List[str] = []
        if name == "Availability":
            fact = item["data"]["person"].get("stopped")
            if fact is None:
                item = consultations.ask_person(store, consultation, actor, name, title, waiting_for="stopped",
                                                ask=f"Has {machine} stopped?")
                waiting = next(q for q in item["data"]["questions"] if q["status"] == "open" and q["question"] == name)
                return _ask_person(consultation, waiting["n"], title, machine)
            brief = tools.availability(data, machine, part, STATES[fact["value"]][0])
            uses = ["stopped"]
        elif name == "Lead time":
            brief = tools.lead_time_question(data, machine, part)
        else:
            brief = tools.service_demand(data, machine)
        item = consultations.answer(store, consultation, actor, name, title, facts=brief.render(),
                                    tools_run=brief.tools_run, rule=brief.rule, not_known=brief.not_known, uses=uses)
        entry = consultations.latest_answer(item)
        return "\n".join([
            f"#{consultation} question {entry['n']}: {title}", "", brief.render(), "",
            consultations.receipt_text(item, entry), "",
            "Explain these FACTS as CUSTOMER ANSWER / SITUATION / RECOMMENDATION. Run "
            f"check({consultation}, answer) on your draft, then propose_reply({consultation}, answer).",
        ])

    @role.register(writes=True)
    def check(consultation: int, answer: str) -> str:
        """Run the answer checks on a draft, against the facts of the consultation's latest answer:
        every number and date must be in the facts (a date is compared whole), and the CUSTOMER
        ANSWER must not name another customer or their machines. The result is kept on the ticket."""
        item = consultations.get(store, consultation)
        entry = latest(item)
        found = check_answer(answer, entry["facts"], tools.confidential(data, item["data"]["subject"]["customer"]))
        consultations.record_check(store, consultation, actor, entry["n"], answer, found)
        lines = [f"checks on #{consultation} against question {entry['n']} ({entry['title']}): "
                 + ("pass" if found.ok else "fail"), consultations.lines_text(describe(found))]
        if not found.ok:
            lines += ["", "Fix what is flagged before propose_reply: copy numbers and dates as the facts write "
                          "them, and keep other customers out of the CUSTOMER ANSWER."]
        return "\n".join(lines)

    @role.register(writes=True)
    def propose_reply(consultation: int, answer: str) -> str:
        """Queue the reply for an approver. Nothing is sent: the CUSTOMER ANSWER part is what would go
        to the customer once a named person with the approver role approves it, with a reason. The
        checks run again on the reply and go with it; the consultation waits in the approval queue."""
        item = consultations.get(store, consultation)
        entry = latest(item)
        subject = item["data"]["subject"]
        found = check_answer(answer, entry["facts"], tools.confidential(data, subject["customer"]))
        said = customer_part(answer).strip()
        reason = (f"Reply to {data.customers[subject['customer']].name} on question {entry['n']} "
                  f"({entry['title']}); checks {'pass' if found.ok else 'fail'}")
        item = consultations.propose_reply(store, consultation, actor, answer_text=answer, customer_answer=said,
                                           against=entry["n"], check=found, reason=reason)
        return "\n".join([
            f"Reply proposed on #{consultation}: it waits for an approver. Nothing has been sent.", "",
            "CUSTOMER ANSWER, as it would go to the customer once approved:", said, "",
            consultations.receipt_text(item, entry),
        ])

    @role.register(writes=True)
    def release(consultation: int, reason: str) -> str:
        """Hand the consultation back without a decision, when the call cannot be finished now (for
        example, the customer will call back). It goes back to open for whoever takes the call up
        again with resume, and everything on it is kept: the person's answers, the questions and
        their answers, the checks. Nothing is deleted. The reason is required: it stays with the
        release, and whoever resumes the call sees it. Only the consultant who has the call can
        release it."""
        consultations.release(store, consultation, actor, reason)
        return "\n".join([
            f"Consultation #{consultation} released: open, with no one. Nothing was decided, and nothing is deleted.",
            "", consultations.view_text(consultations.view(store, consultation)), "",
            f"Whoever takes the call up again resumes it: resume({consultation}).",
        ])

    @role.register(writes=True)
    def resume(consultation: int) -> str:
        """Take up a consultation again: one that is open (released, or a reply the approver sent
        back) or whose consultant's lease ran out. It becomes in_progress, with you, as it was left:
        the person's answers, the questions and their answers and the checks are all on it, and its
        handovers say who released it and why. A consultation waiting for an approver is not
        resumed, and a closed one never is: its work has stopped, and a new call is a new
        consultation."""
        before = consultations.get(store, consultation)
        held = before["status"] == "in_progress" and before["claimed_by"] == actor and before["lease_active"]
        item = consultations.resume(store, consultation, actor)
        head = (f"Consultation #{consultation} is in progress with you already: nothing changed." if held
                else f"Consultation #{consultation} resumed: in_progress, with {actor}, as it was left.")
        advice = "Go on with ask, check and propose_reply."
        if item["data"]["person"]:
            advice = ("The person's answers are as recorded above, with who recorded them: if the situation may "
                      "have changed since, ask the person again before relying on them. Then go on with ask, check "
                      "and propose_reply.")
        return "\n".join([head, "", consultations.view_text(consultations.view(store, consultation)), "", advice])

    return role
