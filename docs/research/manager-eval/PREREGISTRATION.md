# Manager evaluation, Claude arm: preregistration

**Written 2026-10-08, before any Claude run.** Changes after the first run go in REPORT.md, never here.

## Question

Can Claude, run as the twice-daily main analyst, write the level-3 tickets the spare-parts feed supports,
with every ticket passing the evidence checks? The bar is the one used for glm-5.3-flash in Parts-Service-Desk
L3-2: at least two of the three level-3 tickets in each run, and E1 found and checked in each run.
Passing means meeting the bar in at least 4 of 5 runs, as before.

## Setup (identical to L3-2 except for the arm)

- **Feed:** `daily_feed(demo(), version=3)`, the same text as `experiments/l3-2/feed.txt` in Parts-Service-Desk
  (checked: identical).
- **Prompt:** `prompt.txt` in this folder. It is `SYSTEM` plus `JSON_FORMAT` from `desk/analyst.py`, then the feed.
  The JSON schema is stated in the prompt, as for the glm arm.
- **Expected tickets, match rules, pairing check and exclusion rule:** exactly the code in
  `experiments/l3-2/run.py` (`RULES`, `_excluded`, `grade`) and `desk/analyst.py` (`check_ticket`, `parse`),
  run unchanged from the lab, read only.
- **Arm:** Claude, run through an agent (no API). Each run is a fresh agent with no memory, given only
  `prompt.txt`. It writes its exact reply to `raw/claude-opus-<n>.json`. It reads no other file, runs no code,
  and sees no grades.
- **Runs:** five. The model: Claude Opus 5.5, the stronger of the two; a run with another Claude model would
  be a separate preregistration.

## Two differences that cannot be avoided

1. The arm is an agent, not a model called with temperature 0.2. The temperature is not controllable here, so
   each run is one sample from the agent's default behaviour.
2. The agent is Claude, the same model family as the one writing this document. The grading is done by code,
   not by the agent, so the agent's own judgement of its tickets is not used.

## Grading

A script reads each raw reply, parses it with `analyst.parse`, and grades it with `run.grade`. The script is
kept outside the lab repository (no writes there) and its output goes to `grades.json` in this folder.

## Decision rule

(Amended once, before the first Claude run, to match the L3-2 bar exactly: the earlier wording of the failing-check
limit was wrong.)

- Pass: the bar met in at least 4 of 5 runs. Per run, the bar is: at least two level-3 tickets found, E1 found and
  checked, and at most one ticket failing the evidence check (the L3-2 candidacy bar, as written there).
- Fail: otherwise. A fail is reported as a fail, with the grades.
