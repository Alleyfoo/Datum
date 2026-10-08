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

## 6. Owner answers (recorded 2026-10-08)

| ID | Answer | What it means for the build |
|---|---|---|
| Q1 | Yes | SQLite holds tickets, ledger and decisions; files hold raw, staging and extracts. |
| Q2 | Plan only | Polling is the planned hook mechanism. Not built now; the hook's first version is manual trigger. |
| Q3 | Yes | `openpyxl`, read-only, pinned. |
| Q4 | Yes, Excel only | Only Excel is supported. OCR and PDF are a later question, decided when they are implemented. |
| Q5 | Yes, with a change of meaning. Sender identity is optional: a file dragged into a folder has no sender, and the process is the same. | The wrong-file check is: the file's headers must match the schema of the company it is filed under. Sender identity is not used for now. |
| Q6 | Open | One test company exists, so one ticket per file is enough. Grouping waits for real cases. |
| Q7 | Not required (superseded in round 2: see below) | The confirmer may be the drafter. The gate still needs a named person and a recorded reason. Roles: a worker drafts, an approver (manager) confirms; one person may hold both. |
| Q8 | Yes | No mail collector in the demo. |
| Q9 | Yes | Demo runs locally, repository private. |
| Q10 | No preference: Python 3.11 | Target 3.11, the version installed here. `pyproject.toml` changes to `requires-python = ">=3.11"`. |
| Q11 | Yes | Demo shows principles and a concrete case only. Unit conversion waits. |
| Q12 | Yes | Multi-warehouse is a stated limit now; optimisation later. |
| Q13 | Yes | Demo connects through MCP. The owner has MCP set up for all agent systems, so the connection is generic MCP, not Claude-only. |
| Q14 | Yes | The Excel stock export is the only ERP input. |
| Q15 | Yes | Five exception types as listed. |
| Q16 | Yes, for the demo | The demo has one item master file, shared by all its data. Whether each customer later gets its own item master waits for the first pilot. |
| Q17 | Yes, tuned later | The threshold is a placeholder until real data exists. The assistant proposes tuning values from the data; a person approves them. |
| Q18 | Yes, with roles | Identity stays a principle for the real environment. The demo uses two Subroutine roles: approver and worker. |
| Q19 | Yes | The import research pass runs before the trial and the create-schema gate are designed. |

**On Python.** Never moving off 3.11 has no immediate cost: 3.11 receives security fixes into
2027, and nothing in the code needs 3.12. The costs come later: libraries drop 3.11 support
one by one, and newer language and speed features are unavailable. Since the owner has no
preference, 3.11 is the target until a dependency requires more.


## 7. Owner answers, second round

| ID | Answer | What it means |
|---|---|---|
| P23 | Yes, amendable | Renamed headers can be accepted by amending the schema. An amendment is a new version; old files keep theirs. The regression rule is replaced accordingly (intake.md). Fixes the conflict with demo step 3. |
| D-drafting | Folder access is enough | Anyone with access to the company folder may draft. The worker-only rule is removed. |
| D-email | Not now | No email design until a real mailbox exists. |
| D-merge | When settled | The branch `build/intake-chain` is merged once the owner agrees the idea is settled. |
| P21 | Yes | Whitespace in headers is not significant. Headers are trimmed. |
| D-clean | Own stage | Cleaning is a schema-driven stage, trim by default (intake.md). New backlog items C26 and C27. |
| D-repo | Lab frozen, this repository not | The lab is not edited. This repository extends its own port (plan.md). |

Items the branch must change before merging: the create-schema gate (amendment and folder-access
drafting), the cleaning stage with its trim default, and demo step 3 as a test.

## 9. Owner answers, third round

| ID | Answer | What it means |
|---|---|---|
| R3-1 | Same-version check (option A) | The schema-defect check compares a new version only against files accepted under that version. Confirmed. |
| R3-1b | One file kind for now | A company may later send several kinds of file (for example, one file for tyres and one for lamps), each with its own schema. Not built now. The model must allow several file kinds per company without a redesign. |
| R3-2 | Access comes from the host | Folder access is decided by the host system, which already holds the security status. The code asks whether a person may write to the folder and does not keep its own user list or statuses. The host's status is not known yet, so this is an interface with a stub. |
| R3-2b | Subroutine is not the tool | Subroutine is built for software development, not daily product handling. Its concepts stay as the ticket model, but it is not the backend. Who defines the worker and approver roles now needs a decision (see below). |
| R3-3 | Log everything | Every action is logged with the actor, the time, the action and the before and after values. Logs are append-only and kept. Refused work is kept too. Logs contain personal data (names), so access and retention rules are needed before real data arrives. |

**Roles, decided:** for now, everyone has the manager role. The system does not enforce worker or approver
restrictions yet; every action is still logged with the actor, so the record shows who did what. Real
restrictions come when a real environment is known, from the Windows profile.

Previous wording, kept for reference: roles come from the Windows profile. A manager gets manager access, and so on.
The approver and worker roles are mapped from the profile. Subroutine's role model is removed from the
design. A stricter role model may be needed later for regulated goods (for example medicines or
chemicals); it is not needed for spare parts or furniture.

## 10. Ticket state on open

| ID | Answer | What it means |
|---|---|---|
| T-open | Opening a ticket sets it to `in_progress` | When a person opens an open ticket, its status becomes `in_progress`, and the log records who opened it and when. Opening a ticket that is already `in_progress` changes nothing. |

| T-view | Viewing does not change state | Reading a ticket never changes its status. |
| T-release | Returns to `open` when not concluded | If the handler releases the ticket without a decision, it returns to `open`. |
| T-meaning | `in_progress` means the ticket has been given to an agent for processing | Opening a ticket hands it to an agent. `in_progress` stays until the ticket is concluded (a decision recorded) or released (back to `open`). The log records the agent, the time it was handed over, and the outcome. |

Still open: what happens if the agent stops without releasing. Options: the ticket stays `in_progress` until a
person releases it, or it returns to `open` after a set time.
