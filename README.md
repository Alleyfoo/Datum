# Datum

**Data is the map of the environment.** Datum keeps one record of what a company's data says, and lets each
role draw its own view of it, with the evidence and the unknowns stated.

Operational data arrives as spreadsheets with their own columns, units and habits. Datum does four things with it:

1. **Preserves** each arriving file, unchanged, with a content hash and a ledger line.
2. **Checks** it against the header declaration the company's schema requires. A file that does not fit is refused
   with a verified reason; nothing is guessed into shape.
3. **Routes** the result to a person. A ticket records what was found. A named person admits data to the record.
4. **Answers** questions from the record through role tools shaped for MCP, with a receipt: the tools run, the
   rule applied, the checks passed, and what is not known. The MCP protocol server that exposes them to a client is
   not built yet; today the tools are plain Python functions in a registry.

Code measures and applies rules. An assistant asks, explains and drafts, and cannot change data or send anything.
People decide what enters the record and what is approved.

## What works today

- **Schema registry:** typed fields, keys and references; every row is accepted or refused with a code.
- **Intake:** inbox preservation, staging of Excel cells with their types and row provenance, a cleaning stage
  (trimming and declared case rules, every change recorded), the trial against a company's schema, schema
  versions and a strict create-schema gate.
- **Tickets:** one store for work, with claims, a journal, approvals, and the statuses `open`, `in_progress`,
  `needs_input`, `closed` and `finished`. A closed ticket is deleted after 30 days without a person's reaction;
  a finished ticket keeps its history.
- **Customer-service slice:** search, consultations as tickets, availability and lead-time answers with a receipt,
  answer checks, and proposals for an approver. Golden tests cover the reference scenario.
- **Desk views:** the text screens of a spare-parts desk, ported with golden tests.
- **Synthetic data:** a spare-parts company with a year of history, and a generator for a weekly stock export with
  a renamed-column variant.

## Data

Synthetic data only. The repository contains no real company, supplier or customer data, and none is used by the
tests. Real data is out of scope until it is approved for use.

## Running the tests

```text
pip install -e ".[test]"
python -m pytest
```

Python 3.11 or newer. The tests build their fixtures from the synthetic company and do not call any model.

## The daily sweep

Closed tickets are deleted after their retention period. The sweep runs only when it is called:

```text
python -m babel.record.sweep --store PATH_TO_STORE.sqlite --today YYYY-MM-DD
```

It exits with a non-zero code and prints the error when it fails. Scheduling it is left to the operator.

## Documentation

- [docs/plan.md](docs/plan.md): purpose, principles, status and phases.
- [docs/backlog.md](docs/backlog.md): every item, its status and its source.
- [docs/build-plan.md](docs/build-plan.md): the decisions taken, in order.
- [docs/intake.md](docs/intake.md): how a file becomes data.
- [docs/slice-customer-service.md](docs/slice-customer-service.md): the customer-service slice.
- [docs/provenance.md](docs/provenance.md): where each ported piece comes from.
- [docs/work-order.md](docs/work-order.md): what is still to finish.

## Status

Pre-release. The core and the intake chain are built and tested. Not yet built: the MCP protocol server, the demo
interface and recorded replays, the analyst tools, the worklist, and the scheduling of the manager run. There is no
hosted demo yet.

## Code layout

- `babel/`: the domain-free core (schema, intake, record, checks, the tool registry). The folder keeps the project's
  earlier working name.
- `domains/spare_parts/`: the first domain pack (schema, synthetic company, rules, views, customer-service tools).
- `tests/`: the test suite, golden files and synthetic fixtures.
- `scripts/`: golden-file regeneration. The `capture_lab_*` scripts are for the maintainer only: they read the
  private research repositories the reference text was captured from, and cannot run without them.

## Lineage

The rules and some code come from earlier research projects, kept in their own repositories. Each ported piece
records its origin in [docs/provenance.md](docs/provenance.md). The projects are not merged, and their evidence is
not edited.

## Licence

No licence has been chosen yet. Until one is added, all rights are reserved.
