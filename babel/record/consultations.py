"""Consultations: one customer call, kept as one ticket from the first question to the proposed reply.

A consultation is a task of type ``consultation`` in the ticket store, in its one number space.
Starting one opens it at once, which hands it to the agent working the call: claimed and
``in_progress`` (owner answer T-open). Released without a conclusion, it goes back to ``open``
(T-release). Every write needs the holder's claim and is an attributed journal entry:

- a fact only the person knows, recorded as the person's answer, never guessed;
- each question asked: answered with its facts and receipt, or open while it waits for a fact only
  the person knows (asked again once the person has answered, it is answered);
- each check run on a drafted answer;
- the proposed reply, through the approval queue (C6). Nothing is sent: an approver decides.

The domain pack supplies the subject, the facts and the texts; this module keeps them, pages the
questions and draws the receipt. It knows no domain, calls no model and reads no clock of its own.
"""

from __future__ import annotations

import copy
import textwrap
from typing import Iterable, List, Optional, Sequence, Tuple

from babel.checks import Check, describe

from . import queue
from .store import Store, require

TYPE = "consultation"
#: questions shown per page; the open questions are always counted over all of them
PAGE = 20
#: the ticket statuses a person searches by (build-plan section 12), as the store keeps them
STATUSES = {"open": ("open",), "in_progress": ("in_progress",), "closed": ("done",)}
#: the store's statuses in the words a person reads
SHOWN = {"open": "open", "in_progress": "in_progress", "needs_input": "waiting for an approver", "done": "closed"}
REPLY = "reply"


def _consultation(item: dict) -> dict:
    require(item["kind"] == "task" and item["type"] == TYPE, "not_a_consultation",
            f"#{item['number']} is not a consultation")
    return item


def start(store: Store, actor: str, title: str, *, subject: dict, body: str = "",
          role: Optional[str] = None) -> dict:
    """A new consultation: its own ticket, opened by the actor in the same transaction."""
    with store.transaction() as db:
        number = store.create_item(db, actor, "task", TYPE, title, body=body, status="open", role=role,
                                   data={"subject": subject, "person": {}, "questions": [], "checks": []})
        return store.opening(db, number, actor, role)


def get(store: Store, number: int) -> dict:
    """The consultation as it stands. Reading changes nothing (owner answer T-view)."""
    return _consultation(store.get(number))


def _write(store: Store, number: int, actor: str, change, *, action: str, note: dict) -> dict:
    """One attributed write on a consultation the actor holds: change(data) edits a copy of its data."""
    with store.transaction() as db:
        item = _consultation(store.hold(db, number, actor))
        data = copy.deepcopy(item["data"])
        result = change(data)
        store.update(db, number, actor, action=action, note={**note, **(result or {})}, data=data)
        return store._item(db, number)


def person_fact(store: Store, number: int, actor: str, name: str, value: str, text: str) -> dict:
    """Record the person's answer to a fact only they know, as given; a later answer replaces it."""
    def change(data):
        data["person"][name] = {"value": value, "text": text, "by": actor, "at": store.now()}
    return _write(store, number, actor, change, action="person_answered", note={"fact": name, "value": value})


def ask_person(store: Store, number: int, actor: str, question: str, title: str, *,
               waiting_for: str, ask: str) -> dict:
    """Keep a question open that cannot be answered until the person answers ``ask``.

    The same question asked again while it waits adds no second question; the journal records
    that it was asked again.
    """
    def change(data):
        waiting = [q for q in data["questions"]
                   if q["status"] == "open" and (q["question"], q["waiting_for"]) == (question, waiting_for)]
        if waiting:
            return {"question": waiting[0]["n"], "again": True}
        n = len(data["questions"]) + 1
        data["questions"].append({"n": n, "question": question, "title": title, "status": "open",
                                  "waiting_for": waiting_for, "ask": ask, "by": actor, "at": store.now()})
        return {"question": n}
    return _write(store, number, actor, change, action="question_opened",
                  note={"waiting_for": waiting_for})


def answer(store: Store, number: int, actor: str, question: str, title: str, *, facts: str,
           tools_run: Sequence[str], rule: str, not_known: Sequence[str] = (),
           uses: Iterable[str] = ()) -> dict:
    """Record an answered question with its receipt: the facts, the tools run, the rule applied,
    what is not known, and which of the person's answers it used. Open questions of the same kind
    are answered by it."""
    def change(data):
        missing = [name for name in uses if name not in data["person"]]
        require(not missing, "person_fact_missing", f"the person has not answered: {', '.join(missing)}")
        n = len(data["questions"]) + 1
        closed = []
        for q in data["questions"]:
            if q["status"] == "open" and q["question"] == question:
                q.update(status="answered", answered_in=n)
                closed.append(q["n"])
        from_person = [f"{data['person'][name]['text']}, answered by {data['person'][name]['by']}"
                       for name in uses]
        data["questions"].append({"n": n, "question": question, "title": title, "status": "answered",
                                  "facts": facts, "tools_run": list(tools_run), "rule": rule,
                                  "not_known": list(not_known), "from_person": from_person,
                                  "by": actor, "at": store.now()})
        return {"question": n, "answers_open": closed}
    return _write(store, number, actor, change, action="answered", note={})


def latest_answer(item: dict) -> Optional[dict]:
    """The last answered question that carries facts, or None."""
    return next((q for q in reversed(item["data"]["questions"]) if q["status"] == "answered" and "facts" in q),
                None)


def _stored(check: Check) -> dict:
    return {"ok": check.ok, "unsupported": list(check.unsupported), "dates": list(check.dates),
            "leaks": list(check.leaks)}


def _check(stored: dict) -> Check:
    return Check(tuple(stored["unsupported"]), tuple(stored["leaks"]), tuple(stored["dates"]))


def record_check(store: Store, number: int, actor: str, against: int, answer_text: str, check: Check) -> dict:
    """Keep a check run on a drafted answer, with the answer and the question it was checked against."""
    def change(data):
        n = len(data["checks"]) + 1
        data["checks"].append({"n": n, "against": against, "answer": answer_text, **_stored(check),
                               "by": actor, "at": store.now()})
        return {"check": n}
    return _write(store, number, actor, change, action="checked", note={"against": against, "ok": check.ok})


def propose_reply(store: Store, number: int, actor: str, *, answer_text: str, customer_answer: str,
                  against: int, check: Check, reason: str) -> dict:
    """Queue the reply for an approver (the approval queue, C6). Nothing is sent.

    The check run on the reply is kept first, like any other check. Then the ticket is parked and
    its claim handed back; a named person with the approver role approves or rejects it, with a
    reason. The proposal keeps the full answer, the part that would go to the customer, the
    question it answers and its check.
    """
    kept = record_check(store, number, actor, against, answer_text, check)
    return queue.propose(store, number, actor, REPLY, reason, payload={
        "answer": answer_text, "customer_answer": customer_answer, "against": against,
        "check": kept["data"]["checks"][-1]["n"]})


def release(store: Store, number: int, actor: str) -> dict:
    """Hand the consultation back unconcluded: it returns to ``open`` (T-release), its record kept."""
    _consultation(store.get(number))
    return store.release(number, actor)


def tickets(store: Store, status: str) -> List[dict]:
    """Every ticket with this status, as a person names it: open, in_progress or closed."""
    require(status in STATUSES, "invalid_argument", f"status must be one of {', '.join(STATUSES)}")
    return [item for item in store.items("task") if item["status"] in STATUSES[status]]


def view(store: Store, number: int, offset: int = 0, limit: int = PAGE) -> dict:
    """One consultation with a page of its questions.

    The open and the answered questions are taken from all the questions, never from the page:
    the lab's get_case took them from the paged slice, so an open question on another page went
    missing (backlog C13).
    """
    require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= PAGE,
            "invalid_argument", f"offset must be 0 or more and limit 1 to {PAGE}")
    item = get(store, number)
    questions = item["data"]["questions"]
    return {"item": item, "questions": questions[offset:offset + limit], "offset": offset,
            "total": len(questions), "next_offset": offset + limit if offset + limit < len(questions) else None,
            "open_questions": [q for q in questions if q["status"] == "open"],
            "answered_questions": [q for q in questions if q["status"] == "answered"]}


# -- text --------------------------------------------------------------------------------

#: receipts and cards are wrapped to this width, so a chat shows them as drawn
WIDTH = 100


def lines_text(lines: Sequence[Tuple[str, str]], heading: Optional[str] = None) -> str:
    """Labelled lines as a block: ``  label   value``, values wrapped under themselves."""
    width = max(len(label) for label, _ in lines)
    indent = " " * (width + 5)
    out = [heading] if heading else []
    for label, value in lines:
        wrapped = textwrap.wrap(value, WIDTH - len(indent), break_long_words=False, break_on_hyphens=False)
        out.append(f"  {label:<{width}}   {wrapped[0] if wrapped else ''}".rstrip())
        out += [indent + rest for rest in wrapped[1:]]
    return "\n".join(out)


def check_text(check: Check) -> str:
    """``pass: numbers: all in the facts · dates: ... · other customers: ...``"""
    found = " · ".join(f"{label}: {finding}" for label, finding in describe(check))
    return ("pass" if check.ok else "fail") + ": " + found


def _approval(item: dict) -> str:
    proposal = item["data"].get("proposal")
    if proposal and proposal["action"] == REPLY:
        return (f"the reply waits in the approval queue on #{item['number']}: a named person with the approver "
                f"role approves or rejects it, with a reason. Nothing has been sent")
    if item["data"].get("decisions"):
        return (f"decided: see decision #{item['data']['decisions'][-1]} about #{item['number']}. "
                f"Nothing is sent from here")
    return ("nothing queued yet: propose_reply queues the reply for an approver, a named person with the "
            "approver role. Nothing is sent")


def receipt(item: dict, entry: dict) -> List[Tuple[str, str]]:
    """The receipt of one answered question: what was asked of the person, the tools run, the rule
    applied, the checks, what is not known, and who approves."""
    proposal = item["data"].get("proposal") or {}
    proposed = proposal.get("payload", {}).get("check") if proposal.get("action") == REPLY else None
    ran = [c for c in item["data"]["checks"] if c["against"] == entry["n"]]
    if ran:
        last = ran[-1]
        checks = check_text(_check(last)) + (" (on the reply as proposed)" if last["n"] == proposed
                                             else f" (check {last['n']}, on a draft)")
    else:
        checks = "not run yet: check(consultation, answer) runs them on a draft"
    return [
        ("asked of the person", "; ".join(entry["from_person"])
         or "nothing: this question needs no fact only the person knows"),
        ("tools run", " · ".join(entry["tools_run"])),
        ("rule applied", entry["rule"]),
        ("checks", checks),
        ("not known", "; ".join(entry["not_known"]) or "nothing flagged by the rules"),
        ("needs approval", _approval(item)),
    ]


def receipt_text(item: dict, entry: dict) -> str:
    return lines_text(receipt(item, entry), f"RECEIPT  #{item['number']} question {entry['n']}: {entry['title']}")


def holder(item: dict) -> str:
    return f", with {item['claimed_by']}" if item["status"] == "in_progress" and item["claimed_by"] else ""


def _question_line(q: dict) -> str:
    if q["status"] == "open":
        state = f"open: waits for the person: {q['ask']}"
    elif "facts" in q:
        state = f"answered: {q['rule']}"
    else:
        state = f"was waiting for the person: {q['ask']}; answered in {q['answered_in']}"
    return f"{q['n']:>4}  {q['title']}  ·  {state}"


def view_text(page: dict) -> str:
    """A consultation as a card: who has it, the person's answers, a page of questions, the open
    questions of all, the checks and the reply."""
    item = page["item"]
    data = item["data"]
    out = [f"#{item['number']} consultation · {SHOWN[item['status']]}{holder(item)}", item["title"]]
    person = [(name, f"{fact['text']}, answered by {fact['by']}") for name, fact in data["person"].items()]
    out += ["", lines_text(person, "From the person") if person else "From the person: nothing yet"]
    shown = page["questions"]
    if shown:
        first, last = page["offset"] + 1, page["offset"] + len(shown)
        out += ["", f"Questions {first}-{last} of {page['total']}"
                + (f" (next page from {page['next_offset'] + 1})" if page["next_offset"] is not None else "")]
        out += [_question_line(q) for q in shown]
    else:
        out += ["", f"Questions: none on this page ({page['total']} in all)"]
    waiting = page["open_questions"]
    out.append(f"Open questions, of all {page['total']}: "
               + (", ".join(f"{q['n']} ({q['ask']})" for q in waiting) if waiting else "none"))
    ran = data["checks"]
    out.append("Checks: " + (f"{len(ran)} run; the last " + ("passed" if ran[-1]["ok"] else "failed")
                             if ran else "none run"))
    out.append("Reply: " + _approval(item))
    return "\n".join(out)


def ticket_line(item: dict) -> str:
    """One ticket in a list: number, type, title, status and who has it."""
    return f"#{item['number']:<4} {item['type']:<13} {item['title']}  ·  {SHOWN[item['status']]}{holder(item)}"


def ticket_card(store: Store, item: dict) -> str:
    """A ticket shown on its own: a consultation as its card, any other ticket by its lines."""
    if item["type"] == TYPE:
        return view_text(view(store, item["number"]))
    return "\n".join([f"#{item['number']} {item['type']} · {SHOWN[item['status']]}{holder(item)}",
                      item["title"], *([item["body"]] if item["body"] else [])])
