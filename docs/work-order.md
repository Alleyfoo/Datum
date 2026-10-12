# Work order: what is left to finish

**As of 2026-10-12.** Done so far: the schema registry, the synthetic company, the intake chain (preserve, staging,
cleaning, trial, tickets, dispositions, schema versions and the create-schema gate), the desk's views with golden
tests, the customer-service slice (rules, checks, six MCP tools, consultations as tickets), all bugs B1 to B6, and
the formula rule. Round five (branch `build/round-five`, not merged) adds the owner's status name `closed`, the
`release` and `resume` tools and the P25-b status mapping (B2 and B3 below); 351 tests pass there. The authoritative
lists are [backlog.md](backlog.md) and [build-plan.md](build-plan.md). This page is the order of work and the
decisions still needed.

## A. Decisions needed from the owner (blocking, in order)

| ID | Question | Blocks |
|---|---|---|
| P25-b | Where does a ticket waiting for an approver (`needs_input`) show in the status filter? Built as recommended, to confirm: it keeps its own status in the approval queue and is listed under `in_progress` (`36665be`). The rest of P25 (`closed` replaces `done`) and P26 (`release` and `resume`) are answered in build-plan section 25 and built (B2, B3). | nothing now; a different answer changes one mapping and its test |
| P24 | A placeholder 0 that a program saved for a formula passes the null check. Decided as a working assumption (A-1): clean first. Revisit when real data arrives. | nothing now; real data only |
| P11 | Publish the repository, or post recordings only, for the job posts? | the public demo and the posts |
| P2 | Ticket grouping. Owner: later, one ticket per file for now. Confirm. | nothing now |
| P5 | Anomaly threshold for the analysis ticket. Owner: tune later, the assistant proposes values. | the analyst scene (C15) |

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
4. **Worklist (C16, reads R6).** Port the close-of-day worklist from Shop-flow onto tickets: one action sheet per role,
   each line with its evidence. Golden test on the synthetic company.
5. **Analysis tools (C14).** Lead-time spread and the pre-order proposal on the schema. Golden test. The pre-order is
   a proposal for an approver, never an order.
6. **Anomaly rule (C15, after P5).** The rule part only: an order above the threshold opens an analysis ticket. The
   threshold stays a named placeholder.
7. **Event history used by analytics (C17).** The lead-time and pre-order tools read the requests, deliveries and
   movements that exist since phase 1.
8. **Traceability (C20).** Every value in an answer names its source cell (staging row and column). Test on the
   stock export fixture.
9. **Module registry and establishment (C10, C11, reads R8, R9, R14).** The module contract with its approver and
   limitations, and the establishment ticket flow for a new company. Tests with two companies.
10. **Per-call role check (C12).** Everyone is a manager for now, so the check allows all and logs the actor. The
    real check waits for P6 (environment). Test that every call is logged with its actor.
11. **Demo surface (C18) and replay (C19).** A plant map, the conversation replay of the customer-service scene, the
    ticket view and the approval queue. Replays are recorded tool runs, deterministic, hostable. No live model in the
    replay. Demo steps 1 to 5 in [demo.md](demo.md) must run from a clean checkout.
12. **Reads still open (Read rows).** R10 (evidence packet), R11 (case and worker separation), R12 (no model in
    execution), R13 (tiers), R16 (workbook reading, mostly done in C2), R19 (forecast methods, needed for C14 only if
    a forecast is shown), R20 (coverage map for the plant view). Each read is recorded in provenance.md with its commit.
13. **Manager, ticket checks.** Port the analyst's citation and number checks (`desk/analyst.py`, `check_ticket`) so a
    manager ticket cites its evidence and is checked the same way. The schedule is not set up; the owner asks for it.

## C. Later (not part of the demo)

- Folder watcher (C3b): polling with a stability window; plan only (owner answer Q2).
- Mail collectors (C24), OCR and PDF (P3), unit conversion (P14), multi-warehouse optimisation (P18 limit).
- Second domain (C23), live model mode (C21), Claude Desktop connection (C22). The connection is MCP, so any client.
- Forecast methods per demand group (P4), exception share measurement (P16), interim ERP export format (P17): all need
  real data.
- Per-call identity check against a real environment (P6), tolerance for fits (P10), ticket grouping (P2).
- The Learning Lab supervisor and Shop-flow's other ADRs: read only where a rule is needed.

## D. Housekeeping

- Refresh the board counts in [plan.md](plan.md) after each merge.
- Record the customer-service slice's origins in [provenance.md](provenance.md) (done by the build run; check it).
- `.handoff.md` is git-ignored and should be updated at the end of each session (CLAUDE.md).
- The untracked `.claude/` folder (worktrees) should not be committed. Add it to `.gitignore` only with the owner's
  yes, since it changes the repository.
- The local folder is still named `Babel-Tower`; the GitHub repository is `Datum`. Renaming the folder is optional.

## E. Not in this repository

- Job application material (CV, letters, posts) is outside this repository. The posts depend on P11.
- Real company data stays out (owner decision RD-5). Synthetic only until real data is approved.

**Update (2026-10-12, sixth round):** P25-b is answered (`needs_input` under `in_progress`). P11 is answered as a static page built from the records (build-plan section 26). Both are recorded in [build-plan.md](build-plan.md) section 26.
