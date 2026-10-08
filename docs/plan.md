# Plan

Status: agreed direction, 2026-10-07. Phase 1 built on 2026-10-08. Everything else is
planned, and the board below says which parts are read, coded or still to decide.

## What this is

A governed analysis system: many data sources, many roles, one shared record, reached through
one MCP server. Files come in, are checked against a schema, and go to a person before anything
is admitted. A consultant assistant works the tickets that arrivals and exceptions open. The
ERP stays the system of record. Spare parts is the first **domain pack**, the case that proves
the core.

Roles:

- **Customer service:** discusses a customer's issue, and works the tickets that new data opens.
  The assistant drafts a reply from facts the tools produce; a person approves it.
- **The analyst:** asks about lead times, demand, forecasts and anomalies, and records findings
  in cases.
- **The data owner:** brings files in, confirms mappings and schemas. Unknown formats are refused.
- **The approver:** decides on replies, purchases and data changes. Nothing is approved in a chat.

## Why it is being rebuilt here

The source lab (Predictive-Spare-Parts-Lab) grew as separate slices on synthetic datasets that
never meet. Nothing flows from an import into a case and on to an analyst or a customer reply,
and its demo never shows a conversation or a role. Its evidence is pinned by hashes and paths,
so it stays a frozen research archive. This repository takes its rules and code deliberately,
with origins recorded, rather than merging the labs.

## Design principles

1. **The human is the gate.** A person decides what enters the record and what it means.
   Nothing reaches the record, a customer or the ERP without a person, whoever or whatever
   collected it.
2. **Collection can be automatic; admission is never automatic.** A collector may fill a
   customer's `inbox/` by itself. Each arrival opens a ticket. A person works that ticket before
   anything is extracted into the customer folder or the product data.
3. **Everything is a module with a contract.** Each module declares its input, its output and
   destination, its approver and its known failures. The core does not change when a module is
   added or replaced.
4. **New data opens a ticket.** Arrival, refusal and every change to a mapping each create a
   ticket, and the ticket holds the context for the next person.
5. **The person works the ticket; the assistant helps.** The assistant fetches data, lists
   options with their evidence and gives insight. It does not close tickets, change mappings or
   approve replies, and every insight cites the data behind it.
6. **Cheap before costly.** Rules first, then classical ML, then the assistant, then a person.
   See [positioning.md](positioning.md).
7. **Preserve, reveal, define, then map.** Raw evidence is never changed, staging decides no
   meaning, and meaning is defined by a named person. See [intake.md](intake.md).
8. **Minimum allowed access, per identity (open).** Each user and each background job should get
   the fewest rights it needs, checked on every call. The environment is not known yet, so this
   is a principle, not a design (P6).

## The board

Each open item is one of: **Read** (defined elsewhere, port it), **Code** (defined here, build
it), **Plan** (decide first). Full list with sources in [backlog.md](backlog.md).

| Category | Count | What it means |
|---|---|---|
| Done | 2 | schema registry (D1); synthetic company and ledger (D2) |
| Read | 20 | sibling-repo rules and code to read and port (R1–R20) |
| Code | 24 | defined here, to build (C1–C24), including 4 defects from the lab |
| Plan | 19 | decisions still open (P1–P19) |
| Bugs | 5 | four open (B1–B4, one confirmed by probe), one fixed (B5) without a regression test |
| Research | 1 | the import research pass, before the trial and the create-schema gate are designed |

**Next up.** The build starts from [build-plan.md](build-plan.md): the owner confirms gaps G1 to G12 first, and the defect fixes (B1, B4, B5) can start at once. The intake chain comes next:

1. Read the staging and preserve rules (R1, R2, R4, R5), then build the inbox preserve and
   staging step (C1, C2).
2. Build the folder hook and the strict trial (C3, C4).
3. Extend the case store into the ticket spine (R15, C5), then the approval queue (C6) and the
   three dispositions (C7).
4. Run the import research pass (`build-plan.md` section 5) before C4 and C8 are designed.
5. Decide the open items the intake chain needs: P1 (file identity), P2 (ticket grouping),
   P7 (who approves). These block C4 and C8.

**Blocked on decisions:** the wrong-file check (P1), the create-schema approver rule (P7), the
collector (P9), the identity items (P6, environment unknown), and the first real export (P17, P16).

## Phases (each ends with something you can show)

1. **Core schema and one synthetic world.** Done 2026-10-08: schema registry; the spare-parts
   pack with one synthetic company and a year of history as a ledger that replays to today's
   stock.
2. **Customer-service slice end to end.** Ticket spine, checks and the desk rules on the
   schema; role tools for that role (C5, C12, C13, C14). Demo: plant map, the conversation
   replay and the approval queue.
3. **Data-owner slice.** The intake chain (C1–C11) and the module contract with one OCR module,
   the customer folders and the establishment process (C24). Export types (stock, requests,
   orders) mapped to the schema, then rules that open cases (C15).
4. **Analyst slice.** Lead-time, demand and anomaly tools on the same data (C14, C17); findings
   and pre-order proposals in the shared record.
5. **Live mode and Claude Desktop connection** (C19, C21, C22); replays refreshed from real runs.
6. **Second domain sketch** to test that the core holds (C23).

## Decisions made

Decided by the owner, 2026-10-08:

- **Ticket spine:** extend the existing case store (`desk/cases.py` in the lab). One store for
  consultations, imports and analysis; no third store.
- **Forecasting is per problem group, not one method.** Demand patterns differ (steady wear
  parts, lumpy breakdown parts, rare parts, new parts), so the analyst picks a method per group
  from the pattern, and each group's method is evaluated on its own. The choice is a recorded,
  reviewable decision on the ticket.
- **Sharing:** the code stays private for now. A distilled version (the method, the schema and
  the demo story, without the full code) comes after the build is finished.
- **Zero refusals** is the rule for "fits". A tolerance is a later decision (P10).
- **The create-schema gate is strict:** a draft becomes active only when the file it came from
  passes with zero refusals, earlier files still pass, the full rule list is on the ticket, and a
  person who did not draft it confirms.
- **Collection can be automatic; admission is never automatic.**
- **Schema means the headers of a file kind.** Mapping a header to its meaning is a separate stage.
- **The old repositories stay frozen.** Their data is imported with provenance; their code is not extended.
- **Tickets are modelled on Subroutine** (`github.com/simonholliday/subroutine`): one numbering
  scheme, decisions as documents, `blocks`, leases on claims, attributed journal. Whether to use
  it as the backend is open (build-plan G10).
- **Identity is open** and kept as a design principle until the environment is known.

Proposed, awaiting the owner's confirmation: the customer folder layout in
[customer-layout.md](customer-layout.md).

## Defects to fix while porting

- `check_answer` compares number fragments: a date rebuilt from fact pieces passes
  (2026-10-02 → 2026-02-10). Compare whole dates and numbers.
- `get_case` derives open and resolved questions from the paged slice only.
- Substitute-stock supply options are not checked for conflicts.

## Documents

| Document | Contents |
|---|---|
| [plan.md](plan.md) | this page: purpose, principles, board, phases, decisions |
| [backlog.md](backlog.md) | every item with its category, source and dependencies |
| [build-plan.md](build-plan.md) | gaps to confirm before the build, what can start now, execution rules and definition of done |
| [positioning.md](positioning.md) | where the system sits beside the ERP, the escalation ladder, exception types, measures |
| [intake.md](intake.md) | the import definition, the arriving-file flow, dispositions, modules, establishment |
| [customer-layout.md](customer-layout.md) | customer folders and shared product data (proposed) |
| [demo.md](demo.md) | what the demo shows and the steps to a meaningful demo |
| [provenance.md](provenance.md) | where each ported piece comes from |
| [interaction.md](interaction.md) | the search, context, question and answer flow in three client tiers (draft) |
