# Plan: Datum (working name)

The repository is named Datum (renamed from Babel-Tower on 2026-10-08). Datum is a reference point that every measurement is taken from.

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
9. **Data is the map of the environment.** One record holds the measured territory. Each role
   draws its own map of it for its use case. Every map is a view of the same record, not a copy,
   and it states its datum: the as-of time, the source, and what is not known.
8. **Minimum allowed access, per identity (open).** Each user and each background job should get
   the fewest rights it needs, checked on every call. The environment is not known yet, so this
   is a principle, not a design (P6).

## The board

Each open item is one of: **Read** (defined elsewhere, port it), **Code** (defined here, build
it), **Plan** (decide first). Full list with sources in [backlog.md](backlog.md).

| Category | Count | What it means |
|---|---|---|
| Done | 28 | schema registry (D1); synthetic company and ledger (D2); the desk's data (D3) and its text views with golden files (D4); staging, assumption, versioning, mapping and reference rules read (R1–R5); the intake chain C1–C9, the synthetic stock export (C25) and the cleaning stage (C26, C27); round four: the one-day lease (P22) and formula cells taken as their saved values (P20); the customer-service slice: the service rules (D5), the answer checks (R17), the lab's defects (C13), consultations as tickets (D6) and the role's tools with golden files (D7) |
| Read | 14 | sibling-repo rules and code to read and port (R6–R20 without R17; R15 and R18 partly read) |
| Code | 15 | defined here, to build (C10–C24 without C13, and the folder watcher C3b) |
| Plan | 26 | decisions (P1–P26): P1, P12, P13 and P20–P23 answered (P20 and P22 built in round four), P7 answered for schemas; P20–P23 raised by the intake build, P24 (saved formula values a workbook marks as not current) by the P20 build, P25 (where a ticket waiting for approval belongs among the three statuses) and P26 (tools to release and resume a consultation) by the customer-service slice |
| Bugs | 6 | all fixed: B1, B4, B5 (with its regression test), and in round four B2 and B3 (the ledger carries request and delivery ids) and B6 (menu letters go on past z) |
| Research | 1 | the import research pass: done, see [research/import.md](research/import.md) |

**Built, not merged: the customer-service slice** (branch `build/cs-slice`, build-plan section 23). One call, "CH-02 has
stopped; the customer needs SP-1601", runs through the role's tools as a ticket: search, the person asked whether the
machine stopped, the lab's rules and facts, the checks, and a reply that waits for an approver with its receipt. The
owner decides the merge and answers P25 and P26.

**Next up.** The intake chain runs end to end on synthetic data: a file is preserved, staged,
cleaned, tried against its company's schema and routed to a ticket; a new schema version, also an
amendment for a renamed header (demo step 3), passes the create-schema gate only through a named
approver; an approver admits a fitting file. What it needs from the owner, in
[backlog.md](backlog.md#plan-needs-a-decision-or-design-first):

1. P24 (whether a saved formula value counts when the workbook marks it as not current). P20 (formula
   cells) and P22 (lease length) are answered and built.
2. Then the folder watcher (C3b), the module registry (C10) and customer establishment (C11).

**Blocked on decisions:** the collector (P9), the identity items (P6, environment unknown), and the
first real export (P17, P16).

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

- **Ticket spine:** one store for consultations, imports and analysis, built in this repository.
  The lab's case store (`desk/cases.py`) is ported here and extended here. The lab is frozen and
  is not edited; this repository is not frozen.
- **Forecasting is per problem group, not one method.** Demand patterns differ (steady wear
  parts, lumpy breakdown parts, rare parts, new parts), so the analyst picks a method per group
  from the pattern, and each group's method is evaluated on its own. The choice is a recorded,
  reviewable decision on the ticket.
- **Sharing:** the code stays private for now. A distilled version (the method, the schema and
  the demo story, without the full code) comes after the build is finished.
- **Zero refusals** is the rule for "fits". A tolerance is a later decision (P10).
- **Schemas can be amended.** An amendment is a new version. Accepted files keep their version;
  the amended version applies to new files.
- **Drafting:** anyone with access to the company's folder may draft a schema. Confirmation needs
  a named person; the drafter may confirm.
- **Cleaning is a stage of its own.** Default: trim whitespace in every text cell and header. Other
  transformations (case, format, units) are declared per field in the schema, and every change is
  recorded against its cell.
- **Email is out of scope** until a real mailbox exists.
- **Merge** to `main` happens once the owner agrees the idea is settled.
- **The create-schema gate is strict:** a draft becomes active only when the file it came from
  passes with zero refusals after cleaning, the full rule list is on the ticket, and a named person
  confirms it with a reason; the drafter may confirm. Files accepted under earlier versions keep
  their versions and are not checked against the new one.
- **Collection can be automatic; admission is never automatic.**
- **Schema means the headers of a file kind.** Mapping a header to its meaning is a separate stage.
- **The old repositories stay frozen.** Their data is imported with provenance; their code is not extended.
- **Round three:** the schema-defect check uses the same version only; one file kind per company for now,
  with the model open to more; folder access comes from the host system; every action is logged with its
  actor and kept. Subroutine is not the ticket backend (its concepts stay), and its role model is removed: for now
  everyone is a manager; the log records who did what, and real restrictions wait for a real environment. See build-plan.md section 9.
- **Tickets are modelled on Subroutine** (`github.com/simonholliday/subroutine`): one numbering
  scheme, decisions as documents, `blocks`, leases on claims, attributed journal. Whether to use
  it as the backend is open (build-plan G10).
- **Identity is open** and kept as a design principle until the environment is known.
- **The system is modular.** It is both a demo that tells the story and the start of real work, so
  each part is replaceable as the real environment becomes known.
- **The manager** is the main analyst from Parts-Service-Desk: twice a day, tickets only, every ticket cites
  its evidence and is checked. Model: cloud-hosted glm-5.3-flash, the only model that passed the evaluation.
  No local models in the design; they were for tests. Runs on a timer, no extra infrastructure. See build-plan.md section 15.
- **Ticket model is copied from Subroutine** (yes, decided), into our own SQLite store.
- **Storage:** SQLite for state; files for raw, staging and extracts. Excel is the only supported
  format for now; OCR and PDF are decided when they are implemented.
- **Wrong-file check:** a file's headers must match the schema of the company it is filed under.
- **Roles come from Subroutine.** Two roles for the demo: *approver* (manager: confirms schemas,
  decides dispositions and admissions) and *worker* (processes tickets and drafts). Role
  assignment in Subroutine is the demo's access model; a real environment's identity is still open.
- **Origin is not an input.** The system does not need to know whether a file was dragged or
  pushed into a folder. The process is the same either way. The schema decides validity: a file
  that passes is ready for the person to admit; a file that does not pass opens a ticket with the
  verified reason.
- **Sender identity is optional.** A file can be dragged into a customer folder with no sender
  known. The process is the same either way: the trial, the ticket and the disposition do not
  depend on where the file came from. The sender is recorded when it exists.
- **Python:** 3.11 is the target.
- **Demo:** one customer, local, private repository, connected through MCP. Identity and the mail
  collector are left out of the demo. Unit conversion and multi-warehouse optimisation wait.
- **Item master:** the demo has one item master file, shared by its data.
- **Thresholds** (for example, the unusual-order rule) are placeholders tuned later from data. The
  assistant proposes values; a person approves them.

Proposed, awaiting the owner's confirmation: the customer folder layout in
[customer-layout.md](customer-layout.md). Answers recorded in [build-plan.md](build-plan.md): the first
round in section 8, the second round in section 7.

## Defects fixed while porting (C13, on branch `build/cs-slice`)

- `check_answer` compares number fragments: a date rebuilt from fact pieces passes
  (2026-10-02 → 2026-02-10). Compare whole dates and numbers. Fixed: `d1cf46b`.
- `get_case` derives open and resolved questions from the paged slice only. Fixed for consultations: `ceff80f`.
- Substitute-stock supply options are not checked for conflicts. Fixed: `d2c2274`.

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
| [research/import.md](research/import.md) | the import research pass: five answers with sources, and a decision list for the owner |
