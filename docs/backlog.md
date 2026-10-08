# Backlog: what is read, coded and planned

Every open item has one category:

- **Read.** Already defined in a sibling repository or in this plan. The task is to read the
  definition, record its origin and port it. No design call is needed.
- **Code.** Defined in this plan, and only needs building.
- **Plan.** Needs a decision or a design before code can start. Each has an owner question.
- **Done.** Built and tested.

Status of the whole board is summarised in [plan.md](plan.md).

## Done

| ID | Item | Where | Commit |
|---|---|---|---|
| D1 | Schema registry: fields, types, keys, row-level refusal, reference checks | `babel/schema/` | `fcee815` |
| D2 | Synthetic spare-parts company with a year of history; stock ledger replays to today | `domains/spare_parts/` | `0f48e76` |
| R1 | Staging rules read: cell type codes, row provenance, fingerprint, verify | [provenance.md](provenance.md#rules-read-read-items) | `17eedfe` |
| R2 | Assumption lifecycle, decision log, named approver, agent names rejected: rules read | [provenance.md](provenance.md#rules-read-read-items) | `17eedfe` |
| R4 | Preview before apply, per-cell mapping results, before/after record hashes: rules read | [provenance.md](provenance.md#rules-read-read-items) | `17eedfe` |
| R5 | Reference workbooks as `MANUAL_REFERENCE` evidence: rules read | [provenance.md](provenance.md#rules-read-read-items) | `17eedfe` |
| C25 | Synthetic weekly stock export and renamed-header variant, from a seed | `domains/spare_parts/exports.py`, `tests/fixtures/` | `f37d29d` |
| C1 | Inbox preserve: hash, read-only copy, content-derived id, append-only ledger | `babel/intake/inbox.py` | `de3d592` |
| C2 | Staging: text cells with type codes, no coercion, row provenance, fingerprint, verify | `babel/intake/staging.py` | `ef55cb0` |
| C5 | Ticket spine on the Subroutine model: one number space, documents, `blocks`, leases, attributed append-only journal, roles | `babel/record/store.py` | `ad403b5` |
| C6 | Approval queue inside the ticket flow: proposals park a ticket; a named approver decides with a reason | `babel/record/queue.py` | `095eea6` |
| C7 | Dispositions import, create schema, drop; each writes its own record (a decision document; admission also an accepted file) | `babel/intake/dispositions.py`, `babel/intake/accepted.py` | `e82f859` |
| C4 | Trial: strict fit (zero refusals), per-cell results, failure classes (wrong file, structural change, schema defect, value problem) | `babel/intake/trial.py`, `babel/schema/headers.py` | `3a50b74` |
| C3 | Hook, manual trigger: preserve, stage, try against the company's schemas, verify, open the ticket (the folder watcher stays planned) | `babel/intake/hook.py` | `2d783e3` |
| R3 | Versioned schemas, N+1 never rewrites N: rule read for C9 | [provenance.md](provenance.md#rules-read-read-items) | `1f30ed0` |
| C9 | Schema versioning per company and file kind: N+1 never rewrites N, status only forward, one active version | `babel/intake/schemas.py` | `1f30ed0` |
| C8 | Create-schema gate: full rule list on the ticket, the drafted file passes, no regression, a named approver with a reason (the drafter may confirm, Q7); agent names refused; nothing activates by timeout or hook | `babel/intake/schemas.py` (`confirm`, `refuse`) | `0e52240` |
| C27 | Schema amendment: an amendment is a new version; accepted files keep their version and are not checked against it (C8's regression check removed); drafting by anyone with access to the company's folder; demo step 3 as a test | `babel/intake/schemas.py`, `babel/intake/accepted.py`, `babel/intake/hook.py` | `78ad2e7` (tests that pinned the replaced rules changed in `e4328c3`) |
| C26 | Cleaning stage: trim by default (T1), case declared per field, every change recorded against its cell; staging unchanged; the trial runs on cleaned values | `babel/intake/cleaning.py`, `babel/schema/headers.py` | `017afb1` |
| D3 | The desk's data (`ServiceData`) read from the company tables; the lab's desk views captured once as reference text | `domains/spare_parts/data.py`, `tests/golden/views/lab_reference/` | `7181e03`, `0c7c97c`, `3813802` |
| D4 | The desk's text views ported with the lab's exact text: line and machine status, countries, companies, plant view, machine card, menu tree, text menu, widget. Golden files written only by `scripts/regen_golden.py`; tested for identical text across calls and processes, emoji off by default, and no model, randomness or clock (the date is `AS_OF`) | `domains/spare_parts/views.py`, `tools.py`, `tests/golden/views/` | `1c4b4a7`, `1fba3c4`, `420c3ca`, `0761f71`, `53157b3`, `8217786` |
| P22 | Lease length, the owner's answer (build-plan section 20): a claim's lease runs one day from the holder's last write; tested held at 23 hours without a write and run out at 25 | `babel/record/store.py` (`LEASE`) | `ca0d13b` (tests that assumed 30 minutes changed in `1606d40`) |
| P20 | Formula cells, the owner's answer (build-plan section 20): a formula counts as the value the file saved for it (its cached value), taken first in the cleaning stage (rule F1, recorded against the cell with the formula), then cleaned and tried like any other value; a formula with no saved value is refused as `formula_not_calculated` (R6). Staging is unchanged and keeps the formula and the saved value. No formula engine is used | `babel/intake/cleaning.py`, `babel/intake/trial.py`, `babel/schema/headers.py` | `447946c` (tests that pinned the formula refusal and the one-rule cleaning default changed in `2371337`) |
| D5 | The service rules ported from the lab with its text: availability, lead time and service demand, the same facts for every question on every part of every machine, checked against the lab's captured briefs (golden case: CH-02 with SP-1601 stopped takes PO-4718 by the breakdown rule). Each brief also states the rule it applied and what the rules do not weigh: the other planned needs on an incoming order the plan takes | `domains/spare_parts/tools.py`, `tests/golden/cs/lab_reference/` | `52e0ffc`, `77748b7`, `4de9290` |
| C13 | The lab's defects, fixed while porting: a date in an answer is compared whole, not as number fragments; a consultation's open questions are counted over all its questions, not the page; an approved substitute's stock is checked for conflicts. Each has a test that fails on the lab's rule | `babel/checks/answers.py`, `babel/record/consultations.py`, `domains/spare_parts/tools.py` | `d1cf46b`, `ceff80f`, `d2c2274` |
| R17 | Answer checks read and ported: every number and date of an answer is in the facts, and the customer answer names no other customer or machine | `babel/checks/` | `d1cf46b` |
| D6 | Consultations are tickets: one per call, opened to the agent (`in_progress`) and back to `open` when released unconcluded (the owner's T-open and T-release, now in the store); the person's answers, the questions, the checks and the reply through the approval queue, every write attributed; a receipt per answer | `babel/record/store.py`, `babel/record/consultations.py` | `0e5aaa6`, `8b65872`, `b430f54` |
| D7 | The customer-service role for spare parts: `search` (0/1/many; tickets by status), `open_consultation`, `ask`, `stopped` (required before an availability answer), `check` and `propose_reply` (nothing is sent), plain typed functions in a registry; no tool calls a model. The scenario's golden files are written only by `scripts/regen_golden_cs.py`, and the scenario gives the same text in one process and in two others | `babel/mcp/`, `domains/spare_parts/customer_service.py`, `tests/golden/cs/` | `06df35e`, `7508baf`, `7ebc795`, `c207f68`, `28a2aa1` |

## Read (defined elsewhere, read and port)

| ID | Item | Source to read |
|---|---|---|
| R6 | Close-of-day worklist: what needs attention, with the evidence on each line | Shop-flow `docs/adr/0019` (Decision 4), `0021`, `src/shopflow/worklist.py` |
| R7 | Four roles: human, modelling LLM (temporary), established worker, supervisory LLM outside the flow | Shop-flow `docs/adr/0019` (role table, Decision 1) |
| R8 | Sender recognition as routing; unknown sources refused as an output | Shop-flow `docs/adr/0020` |
| R9 | Establishment register: named approver, recorded limitations | Shop-flow `src/shopflow/established.py` (ADR 0019, Decision 2) |
| R10 | Evidence packet: the reasoner reads a vetted product, never the ledger | Shop-flow `docs/adr/0014`, `0015` |
| R11 | Case ≠ Worker; 0/1/many applicability, only a unique match runs | Governed Data Lab `ARCHITECTURE.md` (A1-1, A1-3) |
| R12 | Deterministic execution with no LLM reachable | Governed Data Lab `src/execution/` |
| R13 | MCP tiers declared in the protocol | Shopflow-furniture `src/shopflow/mcp_server.py` |
| R14 | Unknown path: observe, propose, human confirms, source established | Learning Lab (establishment flow) |
| R15 | Case store, evidence, typed findings, claims. Partly read: `desk/cases.py` at `fa3836f`, its concepts ported in C5; `case_evidence.py` and `evidence_intake.py` not yet | Predictive-Spare-Parts-Lab `desk/cases.py`, `case_evidence.py`, `evidence_intake.py` |
| R16 | Bounded workbook reading, recognition, refusal, provenance | Predictive-Spare-Parts-Lab `desk/source_contract.py`, `source_publication.py` |
| R18 | Availability, lead time, service plan rules; menus. Partly read: `desk/views.py` (D4), all of `tools.py` (D5) and the role tools of `mcp_server.py` (D7) are ported; its menu tools (`open_desk`, `pick`, the widget tool, prompts and forms) are not yet, and belong to the demo UI (C18) | Predictive-Spare-Parts-Lab `desk/tools.py`, `views.py`, `mcp_server.py`; Parts-Service-Desk `desk/mcp_server.py` |
| R19 | TSB and Croston methods, as-of features | Predictive-Spare-Parts-Lab `predictive_lab/intermittent.py`, `temporal.py` |
| R20 | Coverage map and proposals with audit log | Spare-Parts-Readiness |

Each ported file records its origin in [provenance.md](provenance.md).

## Code (defined, to build)

| ID | Item | Depends on | Spec |
|---|---|---|---|
| C3b | Folder hook: wait for a complete file (polling with a stability window, G6), then call the manual trigger (C3) | C3 | [intake.md](intake.md#what-happens-to-an-arriving-file); planned only (owner answer Q2) |
| C10 | Module registry: contract, approver, limitations, failures | R9 | [intake.md](intake.md#modules) |
| C11 | Establishment ticket flow for a new company (separate process) | C5, C10 | [intake.md](intake.md#establishing-a-customer-separate-process) |
| C12 | Role tool lists per role, with a server-side check on every call (a role's tool list is a registry since D7; the per-call check waits for P6) | P6 | P6 below |
| C14 | Analysis tools on the schema: lead-time spread, pre-order proposal (availability is built: D5, D7) | D2, R18 | [demo.md](demo.md) |
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

### Defects from the lab (fixed while porting, C13)

- `check_answer` compares number fragments: a date rebuilt from fact pieces passes
  (2026-10-02 → 2026-02-10). Compare whole dates and numbers. **Fixed** in `d1cf46b`.
- `get_case` derives open and resolved questions from the paged slice only. **Fixed** for
  consultations in `ceff80f` (the lab's case store itself is not ported).
- Substitute-stock supply options are not checked for conflicts. **Fixed** in `d2c2274`.

## Bugs to fix

Found in this repository's own code while reviewing the backlog. Each bug names how it was
found, so it can be reproduced before it is fixed.

| ID | Status | Bug | How found | Fix |
|---|---|---|---|---|
| B1 | Fixed (`024eb90`) | `Registry.clean` accepts `NaN` and `inf` as `decimal` values. A non-finite coordinate or quantity would enter the record silently. | Probe: `clean_row` with `x0=float("nan")` and `float("inf")` both accepted. | Done: refused with code `non_finite`; `test_decimal_refuses_non_finite_numbers` covers `nan`, `inf`, `-inf`. |
| B2 | Fixed (`61fde1a`) | The stock ledger links each request to its issue by `id()` of a Python object. It works today, but the link depends on object identity and list order, not on a stable key. | Code review of `generate_history`. Not reproduced failing. | Done: `generate_history` is split into `draw()` (every random choice, in the same order as before) and `ledger()` (no randomness), where each issue takes the `request_id` of its own request and same-day issues of one line are ordered by that id. Output for seeds 2026 and 41 unchanged. `test_each_issue_points_to_its_own_request_whatever_the_order_of_the_requests` shuffles the requests; `test_two_requests_on_one_line_and_day_keep_their_own_issues_in_either_order`. |
| B3 | Fixed (`9e6ddd9`) | A receipt's delivery is found by `(part, warehouse, date)`. If two receipts for the same key land on the same day, the lookup returns the first delivery for both. | Code review. Not reproduced: receipts are spaced 40 to 70 days apart. | Done: each delivery makes its own receipt movement with its `delivery_id`, as in B2; nothing is looked up afterwards. Output for seeds 2026 and 41 unchanged. `test_two_receipts_on_one_line_and_day_each_point_to_their_own_delivery` (the old lookup pointed both receipts to `DL-0001`). |
| B4 | Fixed (`5fd8908`) | `test_snapshot_is_not_mutated_by_build` compares two freshly built snapshots, so it cannot detect a mutation of shared data. | Code review of the test. | Done: the test keeps one snapshot object, makes `build` use it and compares each snapshot table to a deep copy; `test_the_snapshot_check_catches_a_mutation` shows it fails on a mutated table. |
| B5 | Fixed (`0f48e76`), regression test (`ae20790`) | The ledger replayed a same-day issue before its receipt, so the opening balance could be negative. | Found by the conservation test on seed 2026, and fixed by ordering receipts before issues on the same day. | Done: `test_same_day_receipt_and_issue_replays_without_going_negative` (one-line company, seed 41, receipt and issue on 2026-09-26). |
| B6 | Fixed (`f9f102b`) | `menu_tree` letters a machine's parts with `zip(string.ascii_lowercase, ...)`, so a machine with more than 26 parts loses the rest from the text menu, its codes and the widget, without a word. Kept as the lab has it, so the port's text equals the lab's. | Code review while porting `desk/views.py`. Not reproduced: the most parts on one machine is 6. | Done: parts are lettered a to z, then aa, ab, ..., zz, aaa (`part_letters`, as spreadsheet columns); the text menu pads the letters to two, so a single letter prints as the lab's and the golden files are unchanged. `test_a_machine_with_27_parts_keeps_every_part_in_the_menu_its_codes_and_the_widget`. |

## Plan (needs a decision or design first)

| ID | Question | Why it matters | Owner question |
|---|---|---|---|
| P1 | What is a file's identity for the wrong-file check: sender, export header, or both, per source? **Answered (build-plan Q5):** the file's headers must match the schema of the company it is filed under; sender identity is not used. Built in C4 (`wrong_file`) | The wrong-file check cannot be built without it | Answered |
| P2 | Ticket grouping: one per arrival, or one per customer per collector run | Without a rule the queue floods | Which does a service person want to see? |
| P3 | OCR engine and which document kinds it covers | PDFs and scans cannot be imported without it. Prefer a local, self-hosted tool, per the owner's convention | Which document kinds come first? |
| P4 | Forecast methods per demand group, and the evaluation rule | The per-group decision is made; the methods are not | Which groups, which methods? |
| P5 | Anomaly thresholds: what is unusual enough to open an analysis ticket | Drives C15 | What is the threshold, per part and per customer? |
| P6 | Identity-scoped access. Demo: two Subroutine roles (approver, worker). Real environment: still open. | Blocks C24 and real-environment access only | Which environment will this run in? |
| P7 | Who approves a new customer folder and a new schema: one person or two. **Answered for schemas (build-plan Q7):** the confirmer may be the drafter; the gate needs a named person and a reason. Built in C8. The customer folder (C11) is not built | Sets the approver rule in C8 and C11 | Answered for C8; C11 open |
| P8 | Customer layout: pilot size, shared part numbers, who reads a folder | Decides whether the item master is one table | See [customer-layout.md](customer-layout.md#open-questions-for-the-owner) |
| P9 | Mailbox collector: which account, what it may read, what it may write | Mail is the first collector | Which mailbox, which folder? |
| P10 | Tolerance for "fits" | Zero is the rule now | Later, after real files exist |
| P11 | Demo hosting: the repository is private and the public demo needs a public repo | Blocks step 7 | Public demo or private demo? |
| P12 | Ticket model: copy Subroutine's concepts, or use Subroutine as the backend. **Decided (build-plan G10): copy**, into our own SQLite store. Built in C5 | Shapes C5 | Answered |
| P13 | Python version. **Decided by the owner (build-plan Q10): target 3.11**; `pyproject.toml` now says `>=3.11` | Affects tooling only | Answered |
| P14 | Unit conversion scope | Units are recorded, not converted | Which conversions are needed? |
| P15 | Exception types: agree the list, owner and decision for each | Defines the first cases | See [positioning.md](positioning.md#exception-types-initial-list-to-be-agreed) |
| P16 | Measure exception share in real data | Shows whether the value is large enough | Which real export? |
| P17 | Interim ERP interface: the Excel export's fields and format | The only ERP input until the ERP is known | Which export, which fields? |
| P18 | Multi-warehouse scope: transfers are a small multi-echelon case. Limit or extend? | Sets the scope of the inventory logic | Keep as a stated limit? |
| P19 | Which assistant the desktop connection targets | Affects C22 | Claude Desktop only, or others? |
| P20 | May a formula cell's cached value count as the cell's value in the trial? Staging keeps both the formula and the cached value; the trial refuses formula cells for now (C4, rule R6). Evidence in [research/import.md](research/import.md#3-how-are-formula-cells-and-cached-values-handled-when-software-produces-the-file). **Answered (build-plan section 20): calculate, then process.** Done in `447946c`: the cached value is taken as the calculated value (rule F1, first in the cleaning stage), and a formula with no cached value is refused as `formula_not_calculated`. Known limit: openpyxl reads an empty cached text as no value, so a formula whose result is an empty text is refused too. Whether every cached value can be trusted is P24 | A stock export with formulas would never fit | Answered |
| P21 | Is whitespace inside a header significant? The trial compares headers exactly, as the lab does; mcp-messy-data normalises whitespace. See [research/import.md](research/import.md#2-what-minimum-header-declaration-tells-one-file-kind-from-another-without-values). **Answered (build-plan section 7):** yes, headers are trimmed; whitespace at either end is not significant. Built in C26 (`017afb1`) | A trailing space in a header makes a structural change | Answered |
| P22 | Lease length for a claim. A placeholder of 30 minutes is in `babel/record/store.py` (C5); neither source states one. **Answered (build-plan section 20): one day.** Done in `ca0d13b`: a lease runs one day from the holder's last write | How soon an abandoned ticket can be taken | Answered |
| P23 | Does the gate's "every accepted file still passes" apply to the header names? As written (and built, C8), a new version that renames a header is refused once any file with the old header was accepted, so the demo's renamed column (demo step 3) can never become a new version. Options: keep it (a rename is a new file kind); check accepted files only against the value rules, column by column in the declared order; or check only files accepted under the same header list. **Answered (build-plan section 7):** amendable. An amendment is a new version; accepted files keep theirs and are not checked against it, so the regression rule is gone. Built in C27 (`78ad2e7`); demo step 3 is a test | Blocked demo step 3 | Answered |
| P24 | Answered (section 21): a null check in cleaning. Open: a placeholder 0 is not null, so a calculation-settings rule is still needed before real workbooks. | — | [build-plan.md](build-plan.md) section 21 |
| P25 | Ticket statuses. The store keeps `open`, `in_progress`, `needs_input` and `done`; the owner's list is `open`, `in_progress` and `closed` (build-plan section 12). The status filter maps `closed` to `done`, and a ticket whose reply waits for an approver (`needs_input`, set by the approval queue, C6) appears under none of the three: it is found in the approval queue (the slice's owner answer 3). Raised by the customer-service slice | Decides what "what is waiting" shows, and whether the store's names follow the owner's | Does a ticket waiting for approval count as `in_progress`, or keep a status of its own? Should `done` be called `closed` in the store too? |
| P26 | Releasing and resuming a consultation through MCP. Both are built in the record and tested (`consultations.release`, T-release; `store.open_ticket`, T-open), but neither is among the six tools of the slice, so a consultant cannot hand a call back, and a released or rejected consultation can be taken up again only in code. Raised by the customer-service slice | Without a release tool, a consultation the consultant leaves stays `in_progress` until a person releases it (Q-stale) | Add `release(consultation)` and a way to resume a consultation (for example, open it by its ticket number) to the role's tools? |
