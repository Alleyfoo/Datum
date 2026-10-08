# Slice: the customer-service consultation

**Status:** built on branch `build/cs-slice`, not merged (build-plan section 23). The owner answered the open points
before the run (section "Owner answers" at the end). Where each criterion is tested is at the end, under "Built".

## What the slice is

One customer call, end to end, through MCP tools over the synthetic company:

> "CH-02 has stopped. The customer needs SP-1601."

The service person (or the Claude consultant on their behalf) searches, asks the questions only a person can answer, the
tools and rules compute the answer, the checks pass or fail, and a reply is queued for approval. Every consultation is a
ticket, and the answer carries its receipt: the tools run, the rule applied, the checks, what is not known, and who approves.

## Ported from the lab (read, then rewritten here, origin recorded in provenance.md)

| Lab source | What is ported | Lands in |
|---|---|---|
| `desk/tools.py` `machine_context`, `stock_by_warehouse`, `incoming_orders`, `lead_time`, `substitutes`, `where_used`, `due_soon`, `fastest_supply`, `conflicts`, `recommended_plan`, `availability`, `lead_time_plan`, `lead_time_question`, `service_plan`, `service_demand`, `critical_spares` | the rules that decide the availability, lead-time and service answers | `domains/spare_parts/tools.py` |
| `desk/expert.py` `numbers_in`, `customer_part`, `check_answer` | the answer checks: every number in the answer comes from the facts; no other customer is named | `babel/checks/` (core) and the spare-parts confidential names in the domain pack |
| `desk/mcp_server.py` `list_countries`, `list_companies`, `show_plant`, `show_machine`, `ask_question`, `check_answer`, `propose_customer_reply` | the tool surface for this role | `babel/mcp/` (server) with the spare-parts tools registered |
| `desk/analyst.py`, `desk/situation.py` | not in this slice (the manager and the feed belong to a later slice) | — |

Defects fixed while porting (backlog C13): the date check compares whole dates, not number fragments; `get_case`
derives open questions from all questions, not the page; substitute stock is checked for conflicts.

## Tools for the role (customer service)

| Tool | Does | Writes |
|---|---|---|
| `search(text, status?)` | finds customers, machines and parts by id, name or description; applies the 0/1/many rule (one match opens; several are listed for the person to choose; none is reported). With `status`, it also finds tickets of that status (`open`, `in_progress`, `closed`), so "what is waiting" is a status filter | nothing |
| `open_consultation(customer, machine?, part?)` | starts a consultation as a ticket (kind `consultation`), one number space | the ticket, status `in_progress` |
| `ask(consultation, question)` | answers Availability, Lead time or Service demand with the facts and the rule that applies | a receipt entry |
| `stopped(consultation, state)` | the person's answer: `stopped` or `planned`. Required before an availability answer; never guessed | a fact on the ticket, attributed |
| `check(consultation, answer)` | runs the answer checks | the check result on the ticket |
| `propose_reply(consultation, answer)` | queues the reply for an approver | a proposal (the approval queue, as built in C6) |

## Acceptance criteria

1. **Golden scenario.** `CH-02` with `SP-1601`, stopped: the answer's facts match the lab's `availability` output for the same
   company and date (2026-10-02), line for line, with the same recommended plan (PO-4718 by the breakdown rule). A golden file
   holds the text, the receipt and the checks.
2. **The unknown is shown.** The receipt names the competing claim that is not modelled (SC-01 overdue for 3 pcs of the same part
   from FI). A test fails if the receipt omits it.
3. **Person-only facts are asked, not guessed.** An availability answer without `stopped` returns the question, not an answer.
   A test covers it.
4. **0/1/many.** `search("screw")` returns several matches and opens none; `search("reclaim screw")` opens one; `search("zzz")`
   reports no match. Tests cover all three.
5. **Checks.** Every number in the answer is in the facts; another customer's name in the reply fails the check. The date-fragment
   defect is a test that fails on the old comparison and passes on the new one.
6. **Propose, do not send.** `propose_reply` puts a proposal in the approval queue. A test confirms nothing is sent and the
   proposal needs an approver.
7. **Every consultation is a ticket.** One ticket per consultation, with the status moving from `open` to `in_progress` when the
   consultation opens (the agreed rule), and back to `open` when released unconcluded.
8. **Determinism.** Same inputs, same text, every run. No model call inside a tool.
9. **Status filter.** `search(status="open")` lists open tickets only; `status="in_progress"` lists tickets with an agent; a test covers each status and a search with no match.
10. `python -m pytest` passes; no existing test is weakened.

## Not in this slice

- The demo UI and recorded replays (later slice).
- The analyst, the manager and the worklist.
- Live model runs. The consultant is Claude through MCP, used by the owner; the tests use no model.
- Customer-facing sending. Replies are proposals only.

## Owner answers (fifth round)

1. **Receipt default: answered.** Show the full receipt in the golden file; fold it in the conversation view later.
2. **"Stopped" as an argument: answered.** Required; the consultant must ask the person first.
3. **Search scope: answered.** Search filters by ticket status (see the `search` tool and criterion 9). Pending approvals are not separately searched in this slice.

## Built

| Criterion | Tested in | Commit |
|---|---|---|
| 1 Golden scenario | `tests/test_cs_rules.py` (every brief against the lab's), `tests/test_cs_golden.py` | `52e0ffc`, `77748b7`, `28a2aa1` |
| 2 The unknown is shown | `test_the_receipt_names_the_competing_claim_that_is_not_modelled` (`test_cs_golden.py`, `test_cs_tools.py`) | `4de9290` |
| 3 Person-only facts are asked | `test_availability_without_the_persons_answer_returns_the_question_not_an_answer` | `7ebc795` |
| 4 0/1/many | `tests/test_cs_search.py` | `7508baf` |
| 5 Checks | `tests/test_checks.py` (the lab's fragment comparison beside the new one) | `d1cf46b` |
| 6 Propose, do not send | `test_propose_reply_queues_it_for_an_approver_and_sends_nothing` | `8b65872`, `7ebc795` |
| 7 Every consultation is a ticket | `tests/test_consultations.py`, `tests/test_record_store.py` (T-open, T-release) | `0e5aaa6`, `8b65872` |
| 8 Determinism | `test_two_runs_in_one_process_give_identical_text`, `test_two_processes_give_identical_text`, `test_no_tool_calls_a_model` | `28a2aa1`, `7ebc795` |
| 9 Status filter | `test_the_status_filter_lists_tickets_of_that_status_only`, `test_a_status_with_no_ticket_is_reported` | `7508baf` |
| 10 The suite passes | 333 tests; no existing test changed | all |

Also fixed while porting (C13): open questions counted over all questions, not the page (`ceff80f`), and substitute stock
checked for conflicts (`d2c2274`). Raised for the owner: P25 and P26 in [backlog.md](backlog.md).
