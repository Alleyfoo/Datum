"""The approval queue: proposals on tickets that wait for an approver's decision.

It replaces the lab's command-line review script with a step inside the ticket flow. The holder
of a ticket proposes an action with a reason; the ticket is parked (`needs_input`) and the claim
handed back, so it waits in the queue for any approver. Only a person who holds the approver role
and whose name is not agent-like decides. Approving or rejecting writes a decision document about
the ticket with the approver's name and reason, and every step is a journal entry.

An approval may carry an effect: the action's own record, written in the same transaction. If the
effect refuses, nothing changes except a journal entry that records the refusal and its reason.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .store import CLOSED, RecordError, Store, require, text

#: effect(db, ticket, proposal) -> None or a dict with any of: "status", "title", "data",
#: "proposal" (the next step, which parks the ticket again), "record" (kept on the decision),
#: "summary" (added to the decision's text)
Effect = Callable[[object, dict, dict], Optional[dict]]


def propose(store: Store, number: int, actor: str, action: str, reason: str, *,
            payload: Optional[dict] = None, role: Optional[str] = None,
            assignee: Optional[str] = None) -> dict:
    action, reason = text(action, "action", 100), text(reason, "reason")
    with store.transaction() as db:
        item = store.hold(db, number, actor)
        acting = store.acting_role(db, actor, role)
        require(not item["data"].get("proposal"), "proposal_pending", f"#{number} already waits on a decision")
        if assignee is not None:
            store.approver(db, assignee)
        proposal = {"action": action, "reason": reason, "payload": payload or {}, "by": actor,
                    "role": acting, "at": store.now()}
        store.update(db, number, actor, role=acting, action="proposed",
                     note={"proposal": action, "reason": reason},
                     data={**item["data"], "proposal": proposal}, status="needs_input", assignee=assignee)
        return store.let_go(db, number, actor)


def pending(store: Store) -> List[dict]:
    """The queue: parked tickets with a proposal, oldest first, each with its findings."""
    queue = []
    for item in store.items("task"):
        proposal = item["data"].get("proposal")
        if item["status"] == "needs_input" and proposal:
            queue.append({
                "number": item["number"], "title": item["title"], "action": proposal["action"],
                "reason": proposal["reason"], "proposed_by": proposal["by"],
                "proposed_role": proposal["role"], "payload": proposal["payload"],
                "assignee": item["assignee"],
                "findings": [d["number"] for d in store.documents_about(item["number"], "finding")],
            })
    return queue


def _waiting(store: Store, db, number: int, expect: Optional[str]) -> dict:
    item = store._item(db, number)
    proposal = item["data"].get("proposal")
    require(proposal is not None and item["status"] == "needs_input", "nothing_to_decide",
            f"#{number} has no proposal waiting for a decision")
    require(expect is None or proposal["action"] == expect, "wrong_action",
            f"#{number} waits on {proposal['action']}, not {expect}")
    return item


def _refused(store: Store, number: int, actor: str, verb: str, error: RecordError) -> None:
    """Record a refused decision. An unknown actor or item leaves nothing to attribute it to."""
    try:
        with store.transaction() as db:
            store._item(db, number)
            store.write_journal(db, number, actor, store.acting_role(db, actor), f"{verb}_refused",
                                {"code": error.code, "message": str(error)})
    except RecordError:
        pass


def approve(store: Store, number: int, approver: str, reason: str, *, effect: Optional[Effect] = None,
            expect: Optional[str] = None) -> dict:
    """Approve what a ticket waits on. Without an effect saying otherwise, the ticket is done."""
    reason = text(reason, "reason")
    try:
        with store.transaction() as db:
            role = store.approver(db, approver)
            item = _waiting(store, db, number, expect)
            proposal = item["data"]["proposal"]
            store.take(db, number, approver, role)
            outcome = (effect(db, item, proposal) if effect else None) or {}
            body = (f"Approved by {approver} (approver): {reason}\n"
                    f"Proposed by {proposal['by']} ({proposal['role']}): {proposal['action']}, {proposal['reason']}")
            if outcome.get("summary"):
                body += "\n\n" + outcome["summary"]
            decision = store.document(
                db, approver, "decision", f"Approved: {proposal['action']} on #{number}", body,
                data={"decision": "approved", "action": proposal["action"], "ticket": number,
                      "approver": approver, "reason": reason, "proposal": proposal,
                      **outcome.get("record", {})},
                about=number, role=role)
            data = {k: v for k, v in item["data"].items() if k != "proposal"}
            data.update(outcome.get("data", {}))
            data["decisions"] = data.get("decisions", []) + [decision]
            follow = outcome.get("proposal")
            if follow:
                data["proposal"] = {"payload": {}, **follow, "by": approver, "role": role, "at": store.now()}
            fields = {"data": data, "status": outcome.get("status", "needs_input" if follow else CLOSED)}
            if outcome.get("title"):
                fields["title"] = outcome["title"]
            updated = store.update(db, number, approver, role=role, action="approved",
                                   note={"proposal": proposal["action"], "reason": reason, "decision": decision},
                                   **fields)
            if updated["status"] != CLOSED:
                store.let_go(db, number, approver)
            return store._item(db, number)
    except RecordError as error:
        _refused(store, number, approver, "approval", error)
        raise


def reject(store: Store, number: int, approver: str, reason: str, *, effect: Optional[Effect] = None,
           expect: Optional[str] = None) -> dict:
    """Turn a proposal down. The ticket goes back to the workers, open and unclaimed.

    `effect` may record what the rejection means for the proposed thing, in the same transaction.
    """
    reason = text(reason, "reason")
    try:
        with store.transaction() as db:
            role = store.approver(db, approver)
            item = _waiting(store, db, number, expect)
            proposal = item["data"]["proposal"]
            store.take(db, number, approver, role)
            outcome = (effect(db, item, proposal) if effect else None) or {}
            decision = store.document(
                db, approver, "decision", f"Rejected: {proposal['action']} on #{number}",
                f"Rejected by {approver} (approver): {reason}\n"
                f"Proposed by {proposal['by']} ({proposal['role']}): {proposal['action']}, {proposal['reason']}",
                data={"decision": "rejected", "action": proposal["action"], "ticket": number,
                      "approver": approver, "reason": reason, "proposal": proposal,
                      **outcome.get("record", {})},
                about=number, role=role)
            data = {k: v for k, v in item["data"].items() if k != "proposal"}
            data["decisions"] = data.get("decisions", []) + [decision]
            store.update(db, number, approver, role=role, action="rejected",
                         note={"proposal": proposal["action"], "reason": reason, "decision": decision},
                         data=data, status="open", assignee=None)
            return store.let_go(db, number, approver)
    except RecordError as error:
        _refused(store, number, approver, "rejection", error)
        raise
