# Build plan: what to build, in what order, and how to know it is done

This is the handoff document for the build. It answers the questions a builder would
otherwise have to guess at. Items marked **Proposal** are recommendations the owner must
confirm before the item they affect is built. Everything else is settled in
[plan.md](plan.md), [intake.md](intake.md) or [backlog.md](backlog.md).

## 1. Gaps found in review, with proposed answers

| ID | Gap | Proposal | Blocks |
|---|---|---|---|
| G1 | Resolved by the owner: "schema" means the headers of a file kind (names, order, types). Mapping a header to its meaning is the Map stage, not the schema. | **Decided:** a file kind's schema is its header declaration, versioned per customer, with its approver recorded. Canonical meaning is declared by the domain pack and referenced by the mapping. | C4, C8, C9 |
| G2 | Resolved by the owner: the old repository stays frozen; its data is imported, not its code extended. | **Decided:** the case store is ported into `babel/record` with its origin recorded. Data from the lab is copied in as import, with provenance, never edited in place. | C5, C15 |
| G3 | Where state lives is not stated. | **Proposal:** SQLite for state (tickets, ledger, decisions, audit), as `mcp-messy-data` does; files for raw evidence, staging and extracts. | C1, C5 |
| G4 | Resolved by the owner: identity is not set and the environment is unknown. | **Open, kept as a design principle, not built.** Principle 8 in `plan.md` says access is minimum per identity. Items that depend on an identity (C12, C22, C24) wait until the environment is known. The hook and collectors are built to run with no identity assumption beyond the file system they are given. | C12, C22, C24 |
| G5 | One server or several, per role? | **Proposal:** one MCP server; per-call identity check (G4) decides which tools answer. Role tool lists are then a policy, not separate processes. | C12, C22 |
| G6 | How the folder hook detects a complete file is not specified. | **Proposal:** polling from the standard library, with a stability window: a file is complete when its size and modification time are unchanged for a set interval. No OS-specific watcher dependency. | C3 |
| G7 | Excel reader is not chosen. | **Proposal:** `openpyxl` in read-only mode, pinned to a version. Staging reads cell values and their types, never formulas evaluated by the reader. | C2 |
| G8 | Synthetic data generators exist. | **Decided:** reuse them. Messy-data `fixtures/synthetic/make_fixtures.py` makes messy workbooks; the lab's `predictive_lab/world.py` pattern (seeded generation) is already followed by D2. C25 adapts the messy-data generator to the weekly stock export and its renamed-column variant. | C25, demo step 3 |
| G9 | A file kind is not declared: which sheet, which header row, which columns are required. | **Proposal:** a file kind declares sheet name, header row, and required columns, as part of its customer mapping (G1). Without a declared kind there is no trial. | C2, C4 |
| G10 | Ticket model. The owner points to Subroutine (`github.com/simonholliday/subroutine`) as a similar system. | **Decided: yes, copy Subroutine's model** into our own SQLite store. One numbering scheme for tasks and documents; decisions and findings as documents; `blocks`; claims as leases that expire when the worker stops; an attributed append-only journal; comments record what happened, documents record conclusions. | C5, C6, P12 |
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

## 5. Research pass before the import design

Owner decision: the import system needs a research pass before its design is fixed. It runs
before C4 (the trial) and C8 (the create-schema gate), and writes its findings to
`docs/research/import.md`. Questions it must answer, from the messy-data and lab material:

1. Which header drifts happen in real supplier files (renamed, added, removed, reordered,
   merged cells, multiple header rows), and how often does each occur in the lab's evidence?
2. What minimum header declaration is enough to tell a file kind apart from another, without
   looking at values?
3. How are formula cells and cached values handled when the file is produced by software and
   not by a person?
4. What does the trial need to report per cell for a person to decide in under a minute?
5. How does a lease (claim) on a ticket behave when the person holding it stops working?

The research pass has no code output. It ends with a decision list that feeds back into this
document.

## 6. What the owner needs to confirm before the build starts

In order of how many items they unblock: G3 (state), G1 (canonical versus customer schema),
G9 (file kinds), G4 (identity), G2 (port, not extend), G6 and G7 (hook and reader), G10 (ticket
fields). Each is a yes, a change, or a different answer.

## 6. Yes or no

Each question below needs a yes or a no. The recommendation is the answer this plan assumes
unless you say otherwise. Answers are recorded in [plan.md](plan.md) under "Decisions made".

| ID | Question | Recommended |
|---|---|---|
| Q1 | Is the state (tickets, ledger, decisions) kept in SQLite, with raw, staging and extract files on disk? (G3) | Yes |
| Q2 | Does the folder hook detect new files by polling, using a stable size and time for a short interval, with no OS watcher? (G6) | Yes |
| Q3 | Is the Excel reader `openpyxl`, in read-only mode and pinned to one version? (G7) | Yes |
| Q4 | Does every file kind declare its sheet name, header row and required columns before a trial runs? (G9) | Yes |
| Q5 | For the wrong-file check, is a file's identity its sender (for mail) or its export header (for a spreadsheet)? (P1) | Yes |
| Q6 | Does each arriving file get its own ticket, with no grouping per collector run for now? (P2) | Yes |
| Q7 | Must the person who confirms a new schema differ from the person who drafted it? (P7) | Yes |
| Q8 | Is the mail collector left out of the demo, and built only when a real mailbox is named? (P9) | Yes |
| Q9 | Does the demo run locally, with the repository kept private? (P11) | Yes |
| Q10 | Is Python 3.11 the target, as the machine runs it, and `pyproject.toml` changed to match? (P13) | Yes |
| Q11 | Is unit conversion left out of the demo, with units recorded only? (P14) | Yes |
| Q12 | Is multi-warehouse kept as a stated limit: stock moves between FI and SE, with no multi-echelon optimisation? (P18) | Yes |
| Q13 | Is the first desktop connection Claude Desktop only? (P19) | Yes |
| Q14 | Is the Excel stock export the only ERP input for the demo? (P17) | Yes |
| Q15 | Is the starting list of five exception types accepted as it stands? (P15) | Yes |
| Q16 | Is one shared item master used across customers, rather than one per customer? (P8) | Yes |
| Q17 | Does an order above three times a customer's usual quantity open an analysis ticket, with the threshold tuned later? (P5) | Yes |
| Q18 | Is identity kept as a design principle, with no identity code built until the environment is known, and the hook and collectors written to need no identity beyond the file system? (P6, G4) | Yes |
| Q19 | Does the import research pass (section 5) run before the trial and the create-schema gate are designed? | Yes |

Decided already, not a question: Subroutine's model is copied (G10); the old repositories stay
frozen and their data is imported (G2); the schema means the headers of a file kind (G1).
