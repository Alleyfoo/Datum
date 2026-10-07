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
