# Babel Tower

**Many sources, many roles, one shared understanding.**

Operational data arrives in many languages: Excel exports, ERP tables, supplier files,
each with its own columns, units and habits. People ask about it in their own
languages too. Customer service ask "can we deliver by Friday?", analysts ask "are
lead times drifting?", data owners ask "does this new file mean the same as last
month's?".

Babel Tower translates all of it into one governed record and lets every role talk
to that record through an AI assistant over MCP:

```text
SOURCES        Excel · CSV · ERP views · supplier files
   ↓           recognise the format · map it to the schema · validate · refuse what doesn't fit
ONE RECORD     typed entities and events, each value traceable to its source cell
   ↓           rules, statistics and forecasts handle the ordinary
EXCEPTIONS     the unusual becomes a case: evidence, findings, open questions
   ↓
ROLES          customer service · analyst · data owner · approver
               each talks to the record through its own MCP tool list
   ↓
PEOPLE DECIDE  replies, purchases and data changes are proposed, then approved by a person
```

Code measures and applies rules. The assistant asks, explains and drafts. People
establish meaning and approve anything consequential.

## Domains

The core is not about any one business. A **domain pack** supplies the schema, the
rules, the role tools and a synthetic world:

- `spare_parts`: the first demo domain. Industrial spare parts for customer
  machines: stock in two warehouses, lead times, service schedules.

A second domain is the test of that claim.

## Status

Planning. See [docs/plan.md](docs/plan.md). Synthetic data only; no real company,
customer or supplier data enters this repository.

## Lineage

Built from research that remains authoritative in its own repositories:
Predictive-Spare-Parts-Lab (desk tools, case store, Excel intake, forecasting evidence),
Spare-Parts-Readiness (coverage map), Learning Lab (onboarding unfamiliar files),
Governed Data Lab and Shop-flow (recognition, establishment, refusal and evidence rules).
Code is ported deliberately, with its origin recorded; the labs are not merged.
