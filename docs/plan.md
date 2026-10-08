# Plan

Status: agreed direction, 2026-10-07. Nothing built yet.

## What this is

A general governed analysis system: many data sources, many roles, one shared record,
reached through one MCP server. It is not a spare-parts application. Spare parts is the
first **domain pack**, the demo case that proves the core.

Roles talk to the record through an AI assistant (Claude, Copilot or a local model):

- **Customer service** discuss a customer's issue or ticket. The assistant drafts a
  reply from facts the tools produce, and a person approves it.
- **The analyst** asks about lead times, demand, forecasts and anomalies, and records
  findings and questions in cases.
- **The data owner** imports files into the schema. The format is recognised and
  mapped; unknown formats are refused; new mappings are confirmed by a person.
- **The approver** decides on replies, purchases and data changes. Nothing is approved
  inside a chat.

## Why it is being rebuilt here

The source lab (Predictive-Spare-Parts-Lab) grew as separate slices on three synthetic
datasets that never meet: desk (`SP-1601`, `CH-02`), prediction world (`SP-10012`) and
Excel intake (`TEST-PART-1`). Nothing flows from an import into a case and on to an
analyst or a customer reply, and its demo never shows a conversation or a role. Its
evidence is pinned by hashes and paths, so it stays a frozen research archive.

## Core vs. domain

The core must not mention parts, machines or warehouses.

```text
babel/                      core, domain-agnostic
  schema/     entity, field, unit, key and relationship declarations; one registry
  intake/     file → schema: recognise, map, validate, refuse; mapping proposals confirmed by a person
  record/     cases, evidence, findings, questions, proposals, decisions; append-only history
  analytics/  generic tools over the schema: aggregates, lead-time distributions,
              intermittent-demand forecasts, anomaly flags → cases
  checks/     answer checks: numbers must come from facts, confidential names must not leak
  mcp/        one server; roles map to tool lists; domain packs register their tools
domains/
  spare_parts/  schema, synthetic company, rules (availability, service plan, conflicts),
                role definitions, plant coverage view
demo/           Streamlit shell: domain home view + role conversations + shared record
```

A rule of thumb for placement: if a second domain (for example retail goods flow from
Shop-flow) would need it unchanged, it is core.

## What the demo shows: one world, several people, one shared record

- **Home:** the domain's overview. For spare parts that is the plant map, with machines
  coloured by spare-part coverage.
- **Role conversations that follow the same entity.** Chat on the left; on the right,
  the MCP tool calls and the shared record they read or write.
  1. **Customer service (built first):** "CH-02 has stopped, the customer needs
     SP-1601." Availability → fastest supply → conflicts → draft reply → checks →
     approval queue. The agent also sees the part's open case.
  2. **Data owner:** this week's Excel export. Recognised; a renamed column is refused;
     a mapping is proposed and confirmed; the import runs. An unusual request (40
     against a usual 2) opens a case.
  3. **Analyst:** "Is SP-1601 at risk? How long do orders really take?" Actual vs.
     quoted lead time, demand forecast, findings into the case, and a pre-order
     proposal for a buyer.
- **People decide:** approval queue and proposals.
- **Conversation mode:** recorded replays of real tool runs by default (deterministic,
  hostable). A toggle runs a local Ollama model when one is available. A section
  explains how to connect the real server to Claude Desktop.
- **Tools per role:** visible in the demo; each role sees only its own tools.

## What to port, and from where

| Source | Bring in | Lands in |
|---|---|---|
| Predictive-Spare-Parts-Lab `desk/cases.py`, `case_evidence.py`, `evidence_intake.py` | case store, immutable evidence, typed findings, claims | `babel/record` |
| Predictive-Spare-Parts-Lab `desk/source_contract.py`, `source_publication.py` | bounded OOXML reading, recognition, refusal, provenance | `babel/intake` (generalised from one TEST definition) |
| Predictive-Spare-Parts-Lab `desk/expert.py` checks | answer checks | `babel/checks` |
| Predictive-Spare-Parts-Lab `desk/tools.py`, `data.py`, `views.py`, `mcp_server.py` | availability, lead time, service plan rules; menus | `domains/spare_parts` + `babel/mcp` |
| Predictive-Spare-Parts-Lab `predictive_lab/intermittent.py`, `temporal.py` | TSB/Croston, as-of features | `babel/analytics` |
| Spare-Parts-Readiness | coverage map | `domains/spare_parts` view |
| Learning Lab | observe → propose mapping → person confirms | `babel/intake` |
| Governed Data Lab, Shop-flow | recognition (0/1/many), establishment, refusal, evidence kinds | rules re-implemented in the core |

Every ported file records its origin commit in `docs/provenance.md`.

## Phases (each ends with something you can show)

1. **Core schema and one synthetic world.** Schema registry in the core; the spare-parts
   pack declares its entities and generates one company: the desk's readable
   customers, machines and parts, plus event history (requests, deliveries, stock
   movements) for analytics.
2. **Customer-service slice end to end.** Record, checks and the desk rules ported onto
   the schema; MCP tools for that role. Demo: plant map + the customer-service
   conversation (replay) + approval queue.
3. **Data-owner slice.** Generic intake: export types (stock, requests, orders) mapped
   to the schema, mapping confirmation, then rules that open cases.
4. **Analyst slice.** Lead-time, demand and anomaly tools on the same data; findings and
   pre-order proposals in the shared record.
5. **Live mode and Claude Desktop connection**; replays refreshed from real runs.
6. **Second domain sketch** to test that the core holds.

## Defects to fix while porting

- `check_answer` compares number fragments: a date rebuilt from fact pieces passes
  (2026-10-02 → 2026-02-10). Compare whole dates and numbers.
- `get_case` derives open/resolved questions from the paged slice only.
- Substitute-stock supply options are not checked for conflicts.

## Open decisions

- Forecast method for the analyst: LightGBM, TSB or both. The lab's evidence says they
  are close; the simplest well-calibrated method should win.
- Hosting for the demo (Streamlit Community Cloud needs a public repo; this repo is private).

## Still missing, in plain words

The core idea is one ticket for every piece of work: a customer call, a file that arrives,
an unusual number that needs looking at. The ticket holds the context. A consultant (the
assistant) works the ticket through a fixed set of operations; a person signs off anything
that leaves the company. Nothing below exists in this repository yet.

**The ticket spine**
1. One ticket type for all work. Today the lab has an analyst case store, a desk journal
   and a proposals file; they must become one ticket with status, owner and history.
   Recommended: extend `desk/cases.py` rather than add a third store.
2. Consultant work on a ticket: open it, read what is already known, act, write back.
   The current service tools are not tied to a ticket.
3. An approval queue inside the ticket flow. Today proposals are only reviewed from a
   command-line script.

**Cleaning with schema (data owner side)**
4. A schema registry in the core: what an entity is, its fields, units and keys. Today
   the spare-parts fields are hand-written in the data module.
5. Recognising a file by its shape, mapping it to the schema, and refusing what does not
   fit. Exists only for one test workbook. A second format and a person-confirmed mapping
   for unknown changes are missing.
6. Cleaning rules that are generic: types, units, ranges, duplicate keys. Partly done in
   the lab for one schema; not generic.
7. Every import is a ticket. Clean rows load; refused rows stay on the ticket with the
   reason; an unusual value opens an analysis ticket automatically. Entirely missing.
8. Event history in the synthetic company: requests, deliveries and stock movements. The
   current demo data is a snapshot, so no trends can be shown yet.

**Analyst side**
9. Analysis tools over the schema: lead-time spread, demand forecast, anomaly flags. The
   lab has the forecasting experiments, but not as tools on the core schema. The forecast
   method is still open (see below).
10. Findings and a pre-order proposal written to the ticket. Partly there in the case tools.
11. Automatic ticket creation from anomalies. Missing; the lab marks it as later work.

**Across the stack**
12. Traceability: every number traces to a source cell. Partly done in the lab for one format.
13. Role tool lists: each role sees only its own tools. Today there is one server with
    all tools.
14. The known defects in the list above are fixed while porting (date check, open
    questions across pages, substitute conflicts).
15. A demo surface that shows the flow: plant view, the conversation, the shared ticket,
    the approval queue. The lab's Streamlit demo is a starting point; Babel-Tower has none.
16. Hosting and a Claude Desktop connection. Last, after the demo works from a clean checkout.

## Steps to a meaningful demo

Each step ends with something a viewer can watch. The demo is meaningful when steps 1 to 5
run from a clean checkout with no live model, from recorded runs.

1. **The company.** Synthetic company with its history, and the schema it is described in.
2. **A call becomes a ticket.** A customer's conveyor stops. The consultant opens the ticket,
   asks "has it stopped?", runs the tools and rules, passes the checks, and the reply waits
   in the approval queue. The person approves; the ticket records who and when.
3. **A file arrives.** This week's stock export is recognised and loaded. A file with a
   renamed column is refused, the refusal sits on its own ticket, and the mapping is
   confirmed by a person before rows load.
4. **An unusual number opens a ticket.** An order of 40 against a usual 2 becomes an
   analysis ticket. The analyst consultant checks lead times and the forecast, records a
   finding and proposes a pre-order for a buyer to approve.
5. **The loop closes.** The service ticket for the same part shows the open analysis
   ticket. The gap from the earlier answer (a competing claim on incoming stock) is now
   a recorded finding, and the next service answer uses it. This is the payoff: one
   record, several roles.
6. **Live mode.** A local model runs the same consultant role, and the recorded runs are
   refreshed from real sessions.
7. **Connection.** The real server connects to a desktop assistant.
8. **A second domain sketch.** A different kind of data goes through the same schema and
   ticket flow, to test that the core holds.

## Decisions

Decided by the owner, 2026-10-08:

- **Ticket spine:** extend the existing case store (`desk/cases.py` in the lab). One store
  for consultations, imports and analysis; no third store.
- **Forecasting is per problem group, not one method.** Demand patterns differ (steady
  wear parts, lumpy breakdown parts, rare parts, new parts), so the analyst picks a method
  per group from the pattern, and each group's method is evaluated on its own. The method
  choice itself is a recorded, reviewable decision on the ticket.
- **Sharing:** the code stays private for now. A distilled version (the method, the
  schema and the demo story, without the full code) comes after the build is finished.
