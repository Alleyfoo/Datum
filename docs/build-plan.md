# Build plan: what to build, in what order, and how to know it is done

This is the handoff document for the build. It answers the questions a builder would
otherwise have to guess at. Items marked **Proposal** are recommendations the owner must
confirm before the item they affect is built. Everything else is settled in
[plan.md](plan.md), [intake.md](intake.md) or [backlog.md](backlog.md).

## 1. Gaps found in review, with proposed answers

| ID | Gap | Proposal | Blocks |
|---|---|---|---|
| G1 | The word "schema" means two things: the domain's meaning (canonical) and one customer's mapping of their file to it. The plan does not separate them. | **Proposal:** a domain pack declares canonical entities, owned by the domain owner. A customer's schema is a versioned mapping from one file kind's staged columns to canonical fields, with its approver recorded. The registry in `babel/schema` holds canonical entities; mappings live under `customers/<id>/schema/`. | C4, C8, C9 |
| G2 | Decision "extend `desk/cases.py`" conflicts with the lab being a frozen archive. | **Proposal:** port the case store into `babel/record` with its origin recorded, and extend it there. The lab is not edited. | C5 |
| G3 | Where state lives is not stated. | **Proposal:** SQLite for state (tickets, ledger, decisions, audit), as `mcp-messy-data` does; files for raw evidence, staging and extracts. | C1, C5 |
| G4 | Identity model is not designed (P6). | **Proposal:** interactive use runs as the Windows user. The hook and collectors run as named service identities. A policy file maps each identity to allowed tools and paths. The server checks it on every call and logs each denial. | C12, C3, C24 |
| G5 | One server or several, per role? | **Proposal:** one MCP server; per-call identity check (G4) decides which tools answer. Role tool lists are then a policy, not separate processes. | C12, C22 |
| G6 | How the folder hook detects a complete file is not specified. | **Proposal:** polling from the standard library, with a stability window: a file is complete when its size and modification time are unchanged for a set interval. No OS-specific watcher dependency. | C3 |
| G7 | Excel reader is not chosen. | **Proposal:** `openpyxl` in read-only mode, pinned to a version. Staging reads cell values and their types, never formulas evaluated by the reader. | C2 |
| G8 | "This week's stock export" (demo step 3) has no source. | **Proposal:** a new code item C25: a generator that writes a synthetic stock export from the snapshot, plus a variant with one renamed column. Both are committed as fixtures. | C25, demo step 3 |
| G9 | A file kind is not declared: which sheet, which header row, which columns are required. | **Proposal:** a file kind declares sheet name, header row, and required columns, as part of its customer mapping (G1). Without a declared kind there is no trial. | C2, C4 |
| G10 | Ticket fields are not defined (P12). | **Proposal:** `id`, `customer`, `kind` (arrival, new_schema, mismatch, establishment, exception), `status` (open, in_progress, waiting, closed), `owner`, `evidence` (references to raw, staging and extract rows), `options`, `decision`, `decided_by`, `decided_at`, and an append-only `history`. | C5, C6 |
| G11 | No test strategy. | **Proposal:** synthetic fixtures committed to the repo; golden files for staging output and trial results; fixed seeds for generated data; a recorded tool-call format (JSON: call, arguments, result) for replays. | all |
| G12 | Dependencies are not chosen. | **Proposal:** standard library, `openpyxl`, `pytest`, and nothing else until a build item needs it. Each addition is recorded in `pyproject.toml` with a reason. | all |

## 2. What can start now

Only items with no open Proposal dependency start now. Everything else waits for the
owner's confirmation of the Proposal it depends on.

| Order | Item | Depends on | Acceptance |
|---|---|---|---|
| 1 | B1: reject `NaN` and `inf` in `decimal` | — | a test per value, each refused with code `non_finite`; existing tests still pass |
| 2 | B4: fix the snapshot test | — | the test fails when a snapshot is mutated, and passes on the current code |
| 3 | B5: regression test for same-day receipt and issue | — | a fixture with both on one day gives a non-negative opening balance and passes conservation |
| 4 | R1, R2, R4, R5: read the staging, assumption and mapping rules; record origins | — | `docs/provenance.md` lists each rule read, with the commit it was read at |
| 5 | C1: inbox preserve | G3 (proposed) | same bytes give one id and one copy; the copy's hash is verified; a write to an inbox file raises; the ledger is append-only |
| 6 | C2: staging | G7, G9 | a fixture workbook gives the same fingerprint on every run; spaces are kept; numbers keep their `n` code; blank rows are flagged; `verify` rebuilds from raw and matches |
| 7 | C25: synthetic stock export and renamed-column variant | D2 | both files generated from a seed; the variant differs only in one header |

Items 1 to 3 are defect fixes and can be done first. Items 5 to 7 start once G3, G7 and G9
are confirmed.

## 3. Execution rules for the build

- One item per commit. Tests pass before each commit. Conventional commit messages, pushed to
  `origin/main` after each milestone, as `CLAUDE.md` asks.
- A builder never decides a **Plan** item. If an item depends on an open Proposal, it stops that
  item, records the question in `backlog.md`, and moves to the next unblocked item.
- Sibling repositories are read-only. Nothing is written to `Predictive-Spare-Parts-Lab`,
  `Governed-data-lab`, `Shop-flow`, `Shopflow-furniture`, `Spare-Parts-Readiness`, or
  `mcp-messy-data`.
- Synthetic data only. No file from a real customer or from `customers/` is read by the build or
  committed.
- Each item updates its row in `backlog.md` and its origin entries in `provenance.md`.
- A test is not weakened to make it pass. If a test is wrong, the change to it is its own
  commit, with the reason.

## 4. Definition of done

An item is done when:

1. its acceptance row above is met, by tests that run in one command: `python -m pytest`;
2. no existing test is failing or skipped;
3. its backlog row is marked Done with the commit hash;
4. any ported code has its origin recorded.

Phase 2 (the customer-service slice) is done when a recorded replay runs from a clean checkout
with no live model and the approval queue shows the ticket and its decision (demo steps 1, 2 and
5 in [demo.md](demo.md)).

## 5. What the owner needs to confirm before the build starts

In order of how many items they unblock: G3 (state), G1 (canonical versus customer schema),
G9 (file kinds), G4 (identity), G2 (port, not extend), G6 and G7 (hook and reader), G10 (ticket
fields). Each is a yes, a change, or a different answer.
