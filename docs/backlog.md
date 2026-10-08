# Backlog: what is read, coded and planned

Every open item has one category:

- **Read.** Already defined in a sibling repository or in this plan. The task is to read the
  definition, record its origin and port it. No design call is needed.
- **Code.** Defined in this plan, and only needs building.
- **Plan.** Needs a decision or a design before code can start. Each has an owner question.
- **Done.** Built and tested.

Status of the whole board is summarised in [plan.md](plan.md).

## Done

| ID | Item | Where |
|---|---|---|
| D1 | Schema registry: fields, types, keys, row-level refusal, reference checks | `babel/schema/` |
| D2 | Synthetic spare-parts company with a year of history; stock ledger replays to today | `domains/spare_parts/` |

## Read (defined elsewhere, read and port)

| ID | Item | Source to read |
|---|---|---|
| R1 | Staging rules: cell type codes, row provenance, fingerprint, verify | `mcp-messy-data` `docs/ARCHITECTURE.md` (Staging) |
| R2 | Assumption lifecycle, decision log, named approver, agent names rejected | `mcp-messy-data` `docs/ARCHITECTURE.md` (Knowledge), `DOCTRINE.md` |
| R3 | Versioned schemas, N+1 never rewrites N | `mcp-messy-data` `docs/ARCHITECTURE.md` (Canonical) |
| R4 | Preview before apply; per-cell mapping results; before/after record hashes | `mcp-messy-data` `docs/F4.1-MAPPING-EXECUTION.md` |
| R5 | Reference workbooks as `MANUAL_REFERENCE` evidence | `mcp-messy-data` `docs/F4.2-EXTRACTION.md` |
| R6 | Close-of-day worklist: what needs attention, with the evidence on each line | Shop-flow `docs/adr/0019` (Decision 4), `0021`, `src/shopflow/worklist.py` |
| R7 | Four roles: human, modelling LLM (temporary), established worker, supervisory LLM outside the flow | Shop-flow `docs/adr/0019` (role table, Decision 1) |
| R8 | Sender recognition as routing; unknown sources refused as an output | Shop-flow `docs/adr/0020` |
| R9 | Establishment register: named approver, recorded limitations | Shop-flow `src/shopflow/established.py` (ADR 0019, Decision 2) |
| R10 | Evidence packet: the reasoner reads a vetted product, never the ledger | Shop-flow `docs/adr/0014`, `0015` |
| R11 | Case ≠ Worker; 0/1/many applicability, only a unique match runs | Governed Data Lab `ARCHITECTURE.md` (A1-1, A1-3) |
| R12 | Deterministic execution with no LLM reachable | Governed Data Lab `src/execution/` |
| R13 | MCP tiers declared in the protocol | Shopflow-furniture `src/shopflow/mcp_server.py` |
| R14 | Unknown path: observe, propose, human confirms, source established | Learning Lab (establishment flow) |
| R15 | Case store, evidence, typed findings, claims | Predictive-Spare-Parts-Lab `desk/cases.py`, `case_evidence.py`, `evidence_intake.py` |
| R16 | Bounded workbook reading, recognition, refusal, provenance | Predictive-Spare-Parts-Lab `desk/source_contract.py`, `source_publication.py` |
| R17 | Answer checks | Predictive-Spare-Parts-Lab `desk/expert.py` |
| R18 | Availability, lead time, service plan rules; menus | Predictive-Spare-Parts-Lab `desk/tools.py`, `views.py`, `mcp_server.py` |
| R19 | TSB and Croston methods, as-of features | Predictive-Spare-Parts-Lab `predictive_lab/intermittent.py`, `temporal.py` |
| R20 | Coverage map and proposals with audit log | Spare-Parts-Readiness |

Each ported file records its origin in [provenance.md](provenance.md).

## Code (defined, to build)

| ID | Item | Depends on | Spec |
|---|---|---|---|
| C1 | Inbox preserve: hash, read-only copy, content-derived id, idempotent ledger | — | [intake.md](intake.md#the-import-definition) (Preserve) |
| C2 | Staging step: text cells with type codes, no coercion, row provenance, fingerprint, verify | R1 | [intake.md](intake.md#the-import-definition) (Reveal) |
| C3 | Folder hook: wait for complete file, hash check, open ticket, run trial | C1, C2 | [intake.md](intake.md#what-happens-to-an-arriving-file) |
| C4 | Trial: strict fit (zero refusals), per-cell results, failure classes 2–4 | C2, R4 | [intake.md](intake.md#what-happens-to-an-arriving-file) |
| C5 | Ticket spine: one ticket type with status, owner, history, extended from `desk/cases.py` | R15 | [plan.md](plan.md#decisions-made) |
| C6 | Approval queue inside the ticket flow (replaces the command-line review script) | C5 | [demo.md](demo.md) |
| C7 | Dispositions: import, create schema, drop; each writes its own record | C5, C4 | [intake.md](intake.md#dispositions) |
| C8 | Create-schema gate: draft, regression check, full rule listing, a non-drafter confirms | R3, C7 | [intake.md](intake.md#what-happens-to-an-arriving-file) |
| C9 | Schema versioning (N+1) and rejection of agent-named approvals | R2, R3 | [intake.md](intake.md#the-import-definition) (Define) |
| C10 | Module registry: contract, approver, limitations, failures | R9 | [intake.md](intake.md#modules) |
| C11 | Establishment ticket flow for a new company (separate process) | C5, C10 | [intake.md](intake.md#establishing-a-customer-separate-process) |
| C12 | Role tool lists per role, with a server-side check on every call | P6 | P6 below |
| C13 | Checks and fixes: whole-date comparison, paged `get_case` questions, substitute conflicts | R17, R15 | defects below |
| C14 | Analysis tools on the schema: lead-time spread, availability, pre-order proposal | D2, R18 | [demo.md](demo.md) |
| C15 | Anomaly rules that open an analysis ticket automatically (rule part only) | C5, P5 | [demo.md](demo.md) step 4 |
| C16 | Worklist over tickets, one per role | R6, C5 | [positioning.md](positioning.md) |
| C17 | Event history used by analytics (requests, deliveries, movements) | D2 | [demo.md](demo.md) |
| C18 | Demo surface: plant map, conversation replay, ticket and queue views | C5, C6, C14 | [demo.md](demo.md) |
| C19 | Replay mode: recorded runs of real tool calls, deterministic, hostable | C18 | [demo.md](demo.md) |
| C20 | Traceability: each value traces to its source cell | C2 | [intake.md](intake.md#the-import-definition) |
| C21 | Live mode: a local model in the same consultant role | C19 | [demo.md](demo.md) step 6 |
| C22 | Claude Desktop connection | C12 | [demo.md](demo.md) step 7 |
| C23 | Second domain sketch on the same core | C1–C9 | [demo.md](demo.md) step 8 |
| C24 | Collectors (mail, folder watcher) as modules: write only to `inbox/` | C10, P9 | [intake.md](intake.md#modules) |

### Defects from the lab (fix while porting)

- `check_answer` compares number fragments: a date rebuilt from fact pieces passes
  (2026-10-02 → 2026-02-10). Compare whole dates and numbers.
- `get_case` derives open and resolved questions from the paged slice only.
- Substitute-stock supply options are not checked for conflicts.

## Bugs to fix

Found in this repository's own code while reviewing the backlog. Each bug names how it was
found, so it can be reproduced before it is fixed.

| ID | Status | Bug | How found | Fix |
|---|---|---|---|---|
| B1 | Open, confirmed | `Registry.clean` accepts `NaN` and `inf` as `decimal` values. A non-finite coordinate or quantity would enter the record silently. | Probe: `clean_row` with `x0=float("nan")` and `float("inf")` both accepted. | Reject non-finite floats in the `decimal` check; add a test for each. |
| B2 | Open, latent | The stock ledger links each request to its issue by `id()` of a Python object. It works today, but the link depends on object identity and list order, not on a stable key. | Code review of `generate_history`. Not reproduced failing. | Carry the request id explicitly through the ledger. |
| B3 | Open, latent | A receipt's delivery is found by `(part, warehouse, date)`. If two receipts for the same key land on the same day, the lookup returns the first delivery for both. | Code review. Not reproduced: receipts are spaced 40 to 70 days apart. | Carry the delivery id through the ledger, as in B2. |
| B4 | Open, test weakness | `test_snapshot_is_not_mutated_by_build` compares two freshly built snapshots, so it cannot detect a mutation of shared data. | Code review of the test. | Keep one snapshot object, call `build` on it, and compare it to a deep copy taken before. |
| B5 | Fixed (`0f48e76`), no regression test | The ledger replayed a same-day issue before its receipt, so the opening balance could be negative. | Found by the conservation test on seed 2026, and fixed by ordering receipts before issues on the same day. | Add a regression test with a same-day receipt and issue for one stock line. |

## Plan (needs a decision or design first)

| ID | Question | Why it matters | Owner question |
|---|---|---|---|
| P1 | What is a file's identity for the wrong-file check: sender, export header, or both, per source? | The wrong-file check cannot be built without it | Which identity does each real source carry? |
| P2 | Ticket grouping: one per arrival, or one per customer per collector run | Without a rule the queue floods | Which does a service person want to see? |
| P3 | OCR engine and which document kinds it covers | PDFs and scans cannot be imported without it. Prefer a local, self-hosted tool, per the owner's convention | Which document kinds come first? |
| P4 | Forecast methods per demand group, and the evaluation rule | The per-group decision is made; the methods are not | Which groups, which methods? |
| P5 | Anomaly thresholds: what is unusual enough to open an analysis ticket | Drives C15 | What is the threshold, per part and per customer? |
| P6 | Identity-scoped access: how a Windows profile maps to a tool list, what a background job may do, how the server enforces it | Every role and collector depends on it | Who gets which tools? |
| P7 | Who approves a new customer folder and a new schema: one person or two | Sets the approver rule in C8 and C11 | Same person or two? |
| P8 | Customer layout: pilot size, shared part numbers, who reads a folder | Decides whether the item master is one table | See [customer-layout.md](customer-layout.md#open-questions-for-the-owner) |
| P9 | Mailbox collector: which account, what it may read, what it may write | Mail is the first collector | Which mailbox, which folder? |
| P10 | Tolerance for "fits" | Zero is the rule now | Later, after real files exist |
| P11 | Demo hosting: the repository is private and the public demo needs a public repo | Blocks step 7 | Public demo or private demo? |
| P12 | Fields a ticket must hold | Shapes C5 | Which fields does the service team need? |
| P13 | Python version: `pyproject.toml` says 3.12+, the machine runs 3.11 | Affects tooling only | Which to target? |
| P14 | Unit conversion scope | Units are recorded, not converted | Which conversions are needed? |
| P15 | Exception types: agree the list, owner and decision for each | Defines the first cases | See [positioning.md](positioning.md#exception-types-initial-list-to-be-agreed) |
| P16 | Measure exception share in real data | Shows whether the value is large enough | Which real export? |
| P17 | Interim ERP interface: the Excel export's fields and format | The only ERP input until the ERP is known | Which export, which fields? |
| P18 | Multi-warehouse scope: transfers are a small multi-echelon case. Limit or extend? | Sets the scope of the inventory logic | Keep as a stated limit? |
| P19 | Which assistant the desktop connection targets | Affects C22 | Claude Desktop only, or others? |
