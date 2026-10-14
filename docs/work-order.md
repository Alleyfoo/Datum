# Work order: what is left to finish

**As of 2026-10-14.** Done so far: the schema registry, the synthetic company, the intake chain (preserve, staging,
cleaning, trial, tickets, dispositions, schema versions and the create-schema gate), the desk's views with golden
tests, the customer-service slice (rules, checks, six MCP tools, consultations as tickets), all bugs B1 to B6, and
the formula rule. Round five (merged into `main`, `b72177e`) added the owner's status name `closed`, the `release`
and `resume` tools and the P25-b status mapping (B2 and B3 below). Round six (branch `build/round-six`, not merged)
builds the two end states, `closed` and `finished`, with closing, the creator's choices, finishing and the 30-day
deletion (B4 below); 392 tests pass there. The authoritative lists are [backlog.md](backlog.md) and
[build-plan.md](build-plan.md). This page is the order of work and the decisions still needed.

## A. Decisions still open

| ID | Question | Blocks |
|---|---|---|
| Licence | Which licence, if any, before the repository is public? | publication |
| History | Rewrite the git history to remove the author email and old local paths, or accept it? | publication |
| P24 | A placeholder 0 saved for a formula passes the null check. Working assumption A-1: clean first; revisit with real data. | real data only |
| P2 | Ticket grouping: one ticket per file for now. | nothing now |
| P5 | Anomaly threshold for the analysis ticket: tuned later from data. | the analyst scene (C15) |

Answered since the first version of this page: P25 and P25-b (statuses), P26 (release and resume), P11 (publication),
and round six's four questions (build-plan sections 25 to 31).

## B. Finish for the demo (in this order)

1. **Small fixes in the slice (C13 follow-up).** The receipt wording that the build run did not finish (a critical part
   described twice in one sentence). One commit, with its golden file updated in the same commit.
2. **Done: release and resume tool (P26).** `release(consultation, reason)` and `resume(consultation)` are consultant
   tools: a release needs its reason and goes back to `open` with everything kept; resume takes up an open
   consultation, or one whose lease ran out, and refuses a closed one with its reason; both are journal entries and
   the card's handovers show them. Commits `8820bf5`, `9481c74`, `fd5138e`; golden `1b85414` (a consultation released,
   then resumed by a second consultant); tests that pinned the six tools or released without a reason changed in
   `1f2eba1` and `7798ef8`.
3. **Done: status mapping (P25).** The store's status `done` is `closed`, in the filter, the ticket view and the
   journal, and an older store is migrated once when it opens (`6323e83`, `c679ee0`; tests that pinned `done`
   changed in `d15fe4e`). A ticket waiting for an approver is listed under `in_progress`, as recommended and still to
   confirm (P25-b, `36665be`; the test that pinned the old placement changed in `2549309`). Tests for each status.
4. **Done: the end states (round six; S-two to S-finish, build-plan sections 27 to 29).** Statuses `open`,
   `in_progress`, `needs_input`, `closed`, `finished`; the filter lists `open`, `in_progress` (with `needs_input`),
   `closed` and `finished`. A worker closes a ticket that cannot be finished, with the reason (`close`, also the
   consultant's tool), and a notice tells its creator to amend and repost it, or delete it (`amend`, `repost`,
   `delete`). Only an approver finishes a ticket, with a decision and a reason (`finish`); an approval finishes its
   ticket. A closed ticket nobody reacts to for 30 days (`CLOSED_RETENTION_DAYS`) is deleted by `sweep(today)`,
   leaving one audit line; a finished one never is. `release` is unchanged. Older stores open with every ticket
   (store version 3). Commits `68823ec` to `96eafb2` on `build/round-six`; the choices are in build-plan section 30.
   Next: the owner's answers to R6-Q1 to R6-Q4, and the merge.
5. **Worklist (C16, reads R6).** Port the close-of-day worklist from Shop-flow onto tickets: one action sheet per role,
   each line with its evidence. Golden test on the synthetic company.
6. **Analysis tools (C14).** Lead-time spread and the pre-order proposal on the schema. Golden test. The pre-order is
   a proposal for an approver, never an order.
7. **Anomaly rule (C15, after P5).** The rule part only: an order above the threshold opens an analysis ticket. The
   threshold stays a named placeholder.
8. **Event history used by analytics (C17).** The lead-time and pre-order tools read the requests, deliveries and
   movements that exist since phase 1.
9. **Traceability (C20).** Every value in an answer names its source cell (staging row and column). Test on the
   stock export fixture.
10. **Module registry and establishment (C10, C11, reads R8, R9, R14).** The module contract with its approver and
    limitations, and the establishment ticket flow for a new company. Tests with two companies.
11. **Per-call role check (C12).** Everyone is a manager for now, so the check allows all and logs the actor. The
    real check waits for P6 (environment). Test that every call is logged with its actor.
12. **Demo surface (C18) and replay (C19).** A plant map, the conversation replay of the customer-service scene, the
    ticket view and the approval queue. Replays are recorded tool runs, deterministic, hostable. No live model in the
    replay. Demo steps 1 to 5 in [demo.md](demo.md) must run from a clean checkout. The sweep of closed tickets is
    run by a call with its date; who calls it, and when, belongs here or with the manager's schedule. Started: the
    demo run (C29, `scripts/demo_run.py`) runs the intake steps, the consultation and a close with one sweep from a
    clean checkout and writes `demo.json`, each call in the replay format, for the static page (P11-site) to read.
    Still to build: the page itself, and steps 4 and 5 (the analysis ticket, after C14 and C15).
13. **Reads still open (Read rows).** R10 (evidence packet), R11 (case and worker separation), R12 (no model in
    execution), R13 (tiers), R16 (workbook reading, mostly done in C2), R19 (forecast methods, needed for C14 only if
    a forecast is shown), R20 (coverage map for the plant view). Each read is recorded in provenance.md with its commit.
14. **Manager, ticket checks.** Port the analyst's citation and number checks (`desk/analyst.py`, `check_ticket`) so a
    manager ticket cites its evidence and is checked the same way. The schedule is not set up; the owner asks for it.

## C. Later (not part of the demo)

- Folder watcher (C3b): polling with a stability window; plan only (owner answer Q2).
- Mail collectors (C24), OCR and PDF (P3), unit conversion (P14), multi-warehouse optimisation (P18 limit).
- Second domain (C23), live model mode (C21). The MCP server exists (C28), so any MCP client connects; the Claude
  Desktop connection (C22) waits only for the per-call check (C12, P6).
- Forecast methods per demand group (P4), exception share measurement (P16), interim ERP export format (P17): all need
  real data.
- Per-call identity check against a real environment (P6), tolerance for fits (P10), ticket grouping (P2).
- The Learning Lab supervisor and Shop-flow's other ADRs: read only where a rule is needed.

## D. Housekeeping

- Refresh the board counts in [plan.md](plan.md) after each merge.
- Record the customer-service slice's origins in [provenance.md](provenance.md) (done by the build run; check it).
- `.handoff.md` is git-ignored and kept as a local session note.
- The `.claude/` folder (local agent worktrees) is ignored by git.
- The local folder is still named `Babel-Tower`; the GitHub repository is `Datum`. Renaming the folder is optional.

## E. Not in this repository

- Material outside this repository (for example publication notes) is not part of it.
- Real company data stays out (owner decision RD-5). Synthetic only until real data is approved.

**Update (2026-10-12, sixth round):** P25-b is answered (`needs_input` under `in_progress`). P11 is answered as a static page built from the records (build-plan section 26). Both are recorded in [build-plan.md](build-plan.md) section 26.

**Update (2026-10-14, round six):** the end states are built on `build/round-six`, not merged (B4): `closed` and `finished`, closing with a reason and the creator's notice, amend, repost and delete, finishing by an approver's decision, and the 30-day sweep. 392 tests pass. The choices and four questions for the owner (R6-Q1 to R6-Q4) are in [build-plan.md](build-plan.md) section 30.

**Update (2026-10-14, MCP server and demo run):** built on `build/mcp-server`, not merged. The MCP protocol server (C28): `python -m datum.mcp.server --store PATH` serves the customer-service tools over stdio, and the README says how a client connects. The synthetic demo run (C29): `scripts/demo_run.py --out DIR` writes the scenario as `demo.json` and `demo.md` beside its record, the same bytes on every run (item 12 above). One defect found on the way, B7 (a decided consultation's receipt labels the reply's check as a draft's), is open in [backlog.md](backlog.md). 441 tests pass. The dependency and the choices the run made are in [build-plan.md](build-plan.md) section 32. Next: the static page that reads `demo.json` (C18, P11-site), then the worklist (item 5).
