# Manager evaluation, Claude arm: report

**Run 2026-10-08.** As preregistered in [PREREGISTRATION.md](PREREGISTRATION.md): the same feed (version 3), the
same prompt (`prompt.txt`), the same expected tickets E1 to E7, and the same grading rules as L3-2. Each run was a
fresh Claude Opus 5.5 agent that saw only the prompt and wrote only its reply. Grading was done by the lab's own
code, unchanged, read only (`grades.json`).

## Result

Bar met in **5 of 5** runs. Pass rule: at least 4 of 5.

| Run file | Tickets | Level-3 found (of 3) | E1 found and checked | Failing evidence checks | Bar |
|---|---|---|---|---|---|
| claude-opus-1.json | 10 | 3 of 3 | yes | 0 | met |
| claude-opus-2.json | 10 | 3 of 3 | yes | 0 | met |
| claude-opus-3.json | 10 | 3 of 3 | yes | 0 | met |
| claude-opus-4.json | 10 | 3 of 3 | yes | 0 | met |
| claude-opus-5.json | 10 | 3 of 3 | yes | 0 | met |

Every run found all seven expected tickets (E1 to E7), wrote ten tickets, and had no ticket failing the evidence
check.

## Caveats

- The five runs produced very similar tickets (the same first ticket, the same evidence ids in most runs).
  That is consistent with one model on one prompt, but it means five samples are less spread than five
  independent analysts would be. The result says the model is reliable on this feed, not that the feed is hard.
- The runs were agent runs, not the scheduled setting that will run the manager. The timed setting is not
  tested here.
- The bar's wording for the failing-check limit was corrected once, before the first run (see the
  preregistration). No run was made before that change.
- Passing this evaluation says nothing about data privacy. The route rule in `build-plan.md` section 16 still
  applies before any real company data reaches a model.
