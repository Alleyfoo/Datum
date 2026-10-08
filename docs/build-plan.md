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

**Status:** done on branch `build/intake-chain` (`836d3e5`). The answers, their sources and the decision
list are in [research/import.md](research/import.md). The decision list holds proposals for the
owner; nothing in it changes a decision recorded here.

## 6. What the owner needs to confirm before the build starts

In order of how many items they unblock: G3 (state), G1 (canonical versus customer schema),
G9 (file kinds), G4 (identity), G2 (port, not extend), G6 and G7 (hook and reader), G10 (ticket
fields). Each is a yes, a change, or a different answer.

## 8. Owner answers (recorded 2026-10-08)

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

**Stale tickets (decided in principle, process not built).** A ticket that stays `in_progress` after its
agent stops is found by a separate check, not by the agent itself. That check is run by the manager agent
(the supervisory role from Shop-flow ADR 0019, outside the normal flow). It opens the stale ticket to inspect
it: it reads the journal, decides whether the work can be resumed, and records what it found. If resuming is
not possible, the ticket goes back to `open`, or to a person. The manager never concludes a ticket; only a
person or a worker records a decision.

Still open: whether the manager may release a ticket to `open` on its own, or may only propose it.
Recommendation: it may release, because a released ticket loses nothing and waits for a worker. It may not conclude.

Earlier note, still open: what happens if the agent stops without releasing. Options: the ticket stays `in_progress` until a
person releases it, or it returns to `open` after a set time.

## 11. The manager agent

| ID | Answer | What it means |
|---|---|---|
| M-role | System-side view | The manager agent sees the whole system. It gives verdicts from the system's side (for example, a ticket is stale, or a schema is failing often) and speaks to people only through tickets. |
| M-static | System tickets | The manager may open tickets of its own, not tied to an arriving file. Reading: these are system-level tickets, for example a stale ticket, a repeated failure, or a drift in a schema. Confirm the reading. |
| M-release | May release | The manager may release a ticket to `open`. The release is a journal entry, and the history stays. Nothing is deleted or rewritten. |
| M-conclude | May not conclude | Only a person or a worker records a decision. |

## 12. Static tickets

| ID | Answer | What it means |
|---|---|---|
| S-state | `static` is a flag on an in-progress ticket | A ticket that is `in_progress` but has not moved for a set time is marked `static`. It keeps its agent and its status; the mark says it has stalled. |
| S-who | Found by the manager | The manager agent finds static tickets, inspects them and reports on them (see section 11). A person can also see them. |
| S-leave | Leaves `static` when it moves or is released | If the agent resumes and the ticket moves, the mark is cleared. If the manager or a person releases it, it goes back to `open` and the history stays. |

Status list, now: `open`, `in_progress`, `closed`. `static` is a marker on `in_progress`, not a status of its own.
`waiting` from the earlier draft is not used. How long a ticket must be still before it is marked `static` is not
decided; it is a setting to tune later.

## 13. Two kinds of manager

| ID | Role | Watches | Creates tickets for | Can release | Can conclude |
|---|---|---|---|---|---|
| M-sys | System-side manager | The process: stale and static tickets, repeated failures, schema drift, the health of the queue | Process problems (for example, a static ticket, a schema that fails often) | Yes, with history kept | No |
| M-analysis | Analysis-side manager | The data: unusual orders, stock that will run out, patterns in exceptions | Business findings (for example, an order far above usual) | Yes, with history kept | No |

Both report only through tickets. Neither changes stock, a schema, or the record. Whether these are two agents
or one agent with two roles is open. Recommendation: two agents with separate scopes, so the process watcher
never reads business data it has no use for.

## 14. The manager, as decided

| ID | Answer | What it means |
|---|---|---|
| M-one | One manager | There is one manager: a separate, higher-level LLM, started twice a day. Section 13's two-agent split is withdrawn. |
| M-input | All data | Each run is given the full data view and the state of the tickets. |
| M-output | Conclusions as tickets | The run returns conclusions. Each conclusion that needs action becomes a ticket: process problems (stale or static tickets, failing schemas) and business findings (unusual orders, stock risk) alike. |
| M-limits | Same limits as before | The manager may release a ticket with its history kept. It may not conclude a ticket, and it changes no stock, schema or record. |

The earlier worry (a process watcher reading business data it does not need) is set aside, since the owner has decided.

## 15. The manager: reference and model

| ID | Answer | What it means |
|---|---|---|
| R-ref | Reference is Parts-Service-Desk's main analyst | The manager is the design in `Parts-Service-Desk` (`desk/analyst.py`, PRODUCT.md D10 and D11). It is part of this project's scaffolding. The Learning Lab supervisor is a related experiment, not the reference. |
| R-model | No local models in the design | Local models were for tests only. The owner judges them not good enough for decisions, so none runs the manager. The evaluation's 9B result (2 of 3 runs, under the bar of 4 of 5) confirms it. |
| R-run | Timed run, no complex setup | The manager runs on a timer, twice a day, like the scheduled runs in Claude work. Same role and limits as before. No extra infrastructure. |
| R-code | Take the code we need | The owner's code can be taken into this repository, with origin recorded in `docs/provenance.md`. |

**Flag for the owner.** The model that passed the evaluation (`glm-5.3-flash:cloud`) is cloud-hosted: each run
sends the day's data to a provider. Our `CLAUDE.md` asks for local, self-hosted tools where possible, and the
data rules say customer data stays out of the repository. Synthetic data is fine now. Before any real company
data is sent to a cloud model, that needs an explicit decision: which provider, what data leaves, and under
what agreement.

**Correction to the earlier summary.** glm-5.3-flash was the only model to pass the bar. The 9B passed 2 of 3
runs, which is below the bar, so it did not qualify. "Only one that could run it" is accurate for the bar; "the
9B cannot run it at all" is not.

## 16. The model must be a confirmed, secured tool

| ID | Answer | What it means |
|---|---|---|
| R-secure | Confirmed and secured | The manager's model must be a tool whose data handling is confirmed in writing: no training on our data, no retention beyond the request, and a stated hosting route. Local models are out of the design (section 15). |
| R-gate | Check before any run with real data | Before a model receives real company data, its written policy must cover the exact route the request takes, not only the vendor's general policy. |

**What is known now (2026-10).** Ollama's privacy policy (updated March 2026) says cloud-hosted models process prompts
only transiently, do not use them for training, and minimise retention ([source](https://registry.ollama.ai/privacy)).
Its cloud page says partners are held to no logging, no training and zero retention ([source](https://standardcompute.com/providers/ollama)).
A search summary found no official statement on whether models hosted by third parties see or keep prompts. That
gap is exactly the route question above.

**Not yet confirmed for `glm-5.3-flash:cloud`:** which company runs the model, and whether that company's terms
match Ollama's. Until this is confirmed, the manager runs on synthetic data only.

**Next step:** confirm the hosting route and terms for glm-5.3-flash. If they do not meet the bar, choose a provider
that offers a signed data processing agreement with documented zero retention, and rerun the evaluation on that model.

## 17. The manager runs on Claude

| ID | Answer | What it means |
|---|---|---|
| R-claude | Use Claude for the manager | The manager's model is Claude. |
| R-why | Why glm was tested | The Parts-Service-Desk handoff (decision D13) says glm-5.3-flash:cloud stood in for Claude for work, through the Claude Code harness, because the experiments used cloud models. It was a proxy, not the chosen model. |
| R-gap | Claude is not evaluated yet | The evaluation (L3-2) measured glm. Claude has not been run through the same feed, prompt, checks and bar. Before the manager goes live, run the same evaluation on Claude (the planned L3-3 is the place). |
| R-route | Data route still checked | The section 16 rule still applies: before real company data is sent, the written terms for the Claude route must cover no training and the retention used. |

## 18. Manager: status after the Claude evaluation

| ID | Answer | What it means |
|---|---|---|
| X-sched | Not yet | The twice-daily timed run is not set up. Next step only when the owner asks. |
| X-safe | Trusted | The owner accepts Claude's stated data-safety terms. This replaces the open route check in section 16 for Claude, on the owner's decision. The basis is the vendor's stated terms, not an audit done here. |
| X-bench | A benchmark only | The synthetic feed gives a simple benchmark. Synthetic data cannot supply the range of real cases the manager needs, so the evaluation does not prove production readiness. More real cases are needed before relying on it. |

## 19. A real import example, for later

| ID | Answer | What it means |
|---|---|---|
| RD-1 | Real example exists | `messy-data.xlsx` in `mcp-messy-data` is real import data. It is kept for a later run. |
| RD-2 | Finish everything first | No real-data run until the build and the demo are finished. |
| RD-3 | Stays out of this repository | The file is not copied into Babel-Tower and is not read by the build. Any later run uses a copy kept outside the repositories, chosen by the owner. |
| RD-4 | Flag: the sibling repo tracks it | `mcp-messy-data` tracks `messy-data.xlsx`, `answers.xlsx` and several fixtures in git, although its README says no real source data is committed. Whether that is a problem depends on what the file contains; the owner should check it. The sibling repo is not edited. |

| RD-5 | Not used | The real workbooks are not used. The project uses synthetic data only until real data is approved. The tracking question in RD-4 is left to the owner; the sibling repo is not edited. |

## 20. Owner answers, fourth round

| ID | Answer | What it means |
|---|---|---|
| Q-merge-intake | Yes | Merged into `main` (commit `3585dc7`). |
| Q-merge-views | Yes | Merged into `main` (commit `c52342b`). |
| Q-claim | Keep | A ticket's claim (lease) stays. |
| Q-lease | One day | A lease runs for one day. (Replaces the 30-minute placeholder, P22.) |
| Q-stale | Keep `in_progress` | A ticket whose agent stops stays `in_progress` until a person releases it. Some tickets may take weeks. |
| Q-group | Later | Grouping of tickets is left for later; one ticket per file for now. |
| Q-bugs | Fix | B6 (a 27th part drops out of the menu), and the latent B2 and B3, are fixed. |
| Q-rename | Now | Done: the GitHub repository is `Alleyfoo/Datum`, still private. The local folder keeps its name. |
| Q-publish | No decision | Public repository or recordings for the job posts is still open. |
| P20 | Calculate, then process | A formula cell's value is calculated first, and the value is then processed like any other value. Formula cells are no longer refused. |

**Status:** built on branch `build/round-four`, not merged: the one-day lease (P22, `ca0d13b`), the ledger
ids (B2 `61fde1a`, B3 `9e6ddd9`), the menu letters past z (B6 `f9f102b`) and formula cells taken as the value
the file saved for them (P20, `447946c`). Building P20 raised one question for the owner, P24 in
[backlog.md](backlog.md): whether a saved formula value counts when the workbook marks it as not current.

## 21. Owner answer on P24, and the round-four merge

| ID | Answer | What it means |
|---|---|---|
| P24 | A null check, in data cleaning | A formula whose result is null is refused, as a rule of the cleaning stage, the way a spreadsheet's COUNTIF would count only filled cells. Declared per field in the schema, so it can be changed by the owner. |
| Merge | Done | `build/round-four` merged into `main`; 235 tests pass. |

**Caveat on P24.** A null check catches a missing result. It does not catch a placeholder 0 that a program saved
for a formula marked for recalculation: 0 is not null, so it still passes. That risk is still open and needs the
workbook's calculation settings, or a separate rule. Decide before any real workbook is read.

## 22. Working assumption: placeholder values

| ID | Status | Assumption | Revisit when |
|---|---|---|---|
| A-1 | Provisional | The placeholder-0 risk (section 21) is handled by clearing the data first: a workbook is cleaned and checked before its values are trusted. Until real data exists, this cannot be tested. | The first real workbook is read. |

Recorded as provisional, per the assumption rules in `mcp-messy-data` (a first observation is not a permanent rule).
