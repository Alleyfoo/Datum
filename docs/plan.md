# Plan

Status: agreed direction, 2026-10-07. Phase 1 built on 2026-10-08 (schema registry and
the synthetic company, see `docs/provenance.md`). Everything else is planned.

## What this is

A general governed analysis system: many data sources, many roles, one shared record,
reached through one MCP server. It is not a spare-parts application. Spare parts is the
first **domain pack**, the demo case that proves the core.

Roles talk to the record through an AI assistant (Claude, Copilot or a local model):

- **Customer service** discuss a customer's issue or ticket, and works the tickets that new
  data opens. The assistant drafts a reply from facts the tools produce, and a person
  approves it.
- **The analyst** asks about lead times, demand, forecasts and anomalies, and records
  findings and questions in cases.
- **The data owner** imports files into the schema. The format is recognised and
  mapped; unknown formats are refused; new mappings are confirmed by a person.
- **The approver** decides on replies, purchases and data changes. Nothing is approved
  inside a chat.

## Design principles

1. **The human is the gate.** A person decides what enters the record and what it means.
   Nothing reaches the record, a customer or the ERP without a person, whoever or whatever
   collected it.
2. **Collection can be automatic; admission is never automatic.** A collector (for example
   mail scraping) may run by itself and fill the customer's `inbox/` with raw, unedited,
   hashed copies. Each arrival opens a ticket. A person works that ticket before anything
   is extracted into the customer folder or the product data. The human gate sits at
   admission, not at collection.
3. **Everything is a module with a contract.** Each module declares its input, its output
   and destination folder, its approver, and its known failures. The core does not change
   when a module is added or replaced.
4. **New data opens a ticket.** Arrival, refusal and every change to a mapping create a
   ticket. The ticket holds the context for the next person.
5. **The person works the ticket; the assistant helps.** A customer service person or data
   owner works through the data. The assistant fetches data, lists options with their
   evidence, and gives insight. It does not close tickets, change mappings or approve
   replies, and every insight cites the data behind it.
6. **Cheap before costly.** Rules first, then classical ML, then the assistant, then a
   person. The escalation ladder below applies to every module.
7. **Minimum allowed access, per identity** (item 17 below).

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
  intake/     file → schema: recognise, map, validate, refuse; mapping proposals confirmed by a person;
              module registry (contract, approver, failures), collectors, establishment
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
| Shop-flow `docs/adr/0019` (Decision 4), `0021`, `shopflow/worklist.py` | close-of-day worklist: what needs attention, with the evidence on each line | `babel/record` (worklist over cases, not a separate dashboard) |
| Shop-flow `docs/adr/0019` (role table, Decision 1) | four roles: human, modelling LLM (temporary), established worker, supervisory LLM outside the flow; success = the model can leave the recurring path | role definitions in `babel/mcp` and the domain pack |
| Shop-flow `docs/adr/0020`, `shopflow/established.py` | sender recognition as routing; unknown sources refused as an output; establishment needs a named approver and recorded limitations | `babel/intake` (registration with approver) |
| Shop-flow `docs/adr/0014`, `0015` | evidence packet: the reasoner reads a vetted product, never the ledger | case evidence in `babel/record` |
| Governed Data Lab `ARCHITECTURE.md` (A1-1, A1-3) | Case ≠ Worker; 0/1/many applicability, only a unique match runs | `babel/intake` bindings and `babel/record` |
| Governed Data Lab `src/execution/` | deterministic execution with no LLM reachable | core rule, tested |
| Shopflow-furniture `mcp_server.py` | tiers declared in the MCP protocol | `babel/mcp` |
| Learning Lab | unknown path: observe, propose, human confirms, then the source is established | `babel/intake` establishment session |

Every ported file records its origin commit in `docs/provenance.md`. Before a piece is
built again, check whether a sibling repository already has it (the list above). Most of
the operational pattern (worklists, refusal, establishment, evidence) already exists there.

## Phases (each ends with something you can show)

1. **Core schema and one synthetic world.** Done 2026-10-08: schema registry in the core;
   the spare-parts pack declares its entities and generates one company: the desk's
   readable customers, machines and parts, plus a year of event history (requests,
   deliveries, stock movements) as a ledger that replays to today's stock.
2. **Customer-service slice end to end.** Record, checks and the desk rules ported onto
   the schema; MCP tools for that role. Demo: plant map + the customer-service
   conversation (replay) + approval queue.
3. **Data-owner slice.** Generic intake: export types (stock, requests, orders) mapped
   to the schema, mapping confirmation, then rules that open cases. Also the customer folders,
   the inbox and its tickets, the three dispositions (import, create schema, drop), the
   module contract with one OCR module, and the establishment process.
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

- Hosting for the demo (Streamlit Community Cloud needs a public repo; this repo is private).
- Forecast methods per problem group: which methods, and the evaluation rule. The
  per-group decision is made; the choice of methods is not.
- Ticket grouping: one ticket per arrival, or one per customer per collector run. Without a
  grouping rule the queue floods.
- OCR engine for scanned PDFs. Prefer a local, self-hosted tool, per the owner's convention.
- Who approves a new customer folder and a new schema: the same person or two people.

## Positioning: where this sits

This system sits beside the ERP, not in place of it. The ERP is not yet known; until a real
connection exists, the stock figures come from an Excel export that other software
produces, and this system reads that export. The ERP is the system of record and does the
ordinary work. This system takes the work the ERP's rules cannot settle, records it as a
case, and keeps it open until a person decides. It does not take work away from people; it
gives them the facts and the reasoning for the hard cases.

### The escalation ladder

Each piece of work starts at the lowest level that can handle it. A level escalates only
when it cannot resolve the item, and it never overwrites the output of a lower level. It
adds to the case.

1. **Deterministic cleaning.** Rules and patterns: format checks, unit conversion, known
   aliases, product-name normalisation with regular expressions. This handles the bulk.
   No model is involved, and every result is reproducible.
2. **Classical ML.** Scores for what rules cannot express: anomaly scores on quantities,
   match confidence for product names that no pattern or alias covers, and the demand
   pattern class per part (the forecasting groups). Output is a score with its inputs, not
   a decision. Low confidence goes up.
3. **Ticket.** Anything unresolved or flagged becomes a case, with its evidence attached:
   source row, the rule that failed, the score, and the question left open.
4. **LLM consultant.** Works the case with the tools. Asks for missing facts, explains,
   and proposes options with their evidence. It does not decide facts and does not approve.
5. **Human.** Decides anything that changes data, allocates stock, or leaves the company.
   A case the consultant cannot close goes here with what is still unknown listed.

Every escalation records why: the failed rule, the score, or the open question.

**Example.** An export contains "Screw flight 400 mm SS". A pattern maps it to SP-1601
(name and dimension). "Screw flite 40 cm" has no pattern; the match score is below the
threshold, so it becomes a case. The consultant lays out the candidates and their evidence;
a data owner confirms the new alias. Next time the alias is found by rule, not by a case.

### What belongs where

| Work | Handled by |
|---|---|
| Ordinary orders, stock postings, reorder parameters, pricing | ERP, unchanged |
| Format and name cleaning, known aliases | Rules (level 1) |
| Unusual quantities, unmatched names, demand classes | Classical ML scores (level 2) |
| Competing claims on stock, stopped machines with conflicting allocation, unknown file formats, parameters that keep producing exceptions | Cases (levels 3 to 5) |

### Exception types (initial list, to be agreed)

Each type has an owner, the evidence it needs, and the decision a person makes.

- **Competing claim:** two customers need the same stock. Owner: service. Decision: who
  gets it.
- **Unusual order:** a quantity far from the customer's or part's usual. Owner: service or
  analyst. Decision: accept, split or query.
- **Unmatched product:** a name no rule or score can map. Owner: data owner. Decision:
  confirm the alias.
- **Changed format:** an incoming file no longer matches its declared format. Owner: data
  owner. Decision: accept the new format or refuse the file.
- **Policy signal:** the same part keeps producing the same exception. Owner: analyst,
  for the ERP owner. Decision: propose a change to the ERP parameter.

### Measures

The product measures the quality of exception handling, not hours saved:

- share of exceptions that reach a decision with complete evidence;
- time from exception to decision;
- decisions reopened or reversed later;
- how often the person had to search across systems for the facts.

Fill rate and emergency orders stay as outcomes to watch, not as the product's own targets.

### Boundary

- Read-only access to the ERP: extracts or views. No write-back. Until the ERP is known,
  the interface is the periodic Excel export.
- A person executes the decision in the ERP and records it in the case with the ERP
  document IDs, so the two systems can be matched.
- The share of exceptions in real data is the first thing to measure. If it is small, the
  value is small, and the pilot should say so early.

## Still missing, in plain words

The core idea is one ticket for every piece of work: a customer call, a file that arrives,
an unusual number that needs looking at. The ticket holds the context. A consultant (the
assistant) works the ticket through a fixed set of operations; a person signs off anything
that leaves the company. Most of what follows is not built yet. Items 4 and 8 are partly
done in phase 1.

**The ticket spine**
1. One ticket type for all work. Today the lab has an analyst case store, a desk journal
   and a proposals file; they must become one ticket with status, owner and history.
   Decided: extend `desk/cases.py` rather than add a third store.
2. Consultant work on a ticket: open it, read what is already known, act, write back.
   The current service tools are not tied to a ticket.
3. An approval queue inside the ticket flow. Today proposals are only reviewed from a
   command-line script.

**Cleaning with schema (data owner side)**
4. A schema registry in the core: what an entity is, its fields, units and keys. Done in
   phase 1 (`babel/schema`). Still open: units are recorded but not converted, and each
   customer's own schema is not yet separated from the shared one (see the layout below).
5. Recognising a file by its shape, mapping it to the schema, and refusing what does not
   fit. Exists only for one test workbook. A second format, the create-schema disposition
   and the establishment process are missing (see "What happens to an arriving file").
6. Cleaning rules that are generic: types, units, ranges, duplicate keys. Partly done in
   the lab for one schema; not generic.
7. Every import is a ticket. Clean rows load; refused rows stay on the ticket with the
   reason; an unusual value opens an analysis ticket automatically. Entirely missing.
8. Event history in the synthetic company. Generated in phase 1 as requests, deliveries and
   stock movements. Not yet used by any analysis, so no trend or forecast is shown.

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
17. **Minimum allowed access, per identity.** Each user gets the tool list their Windows
    profile already allows, and the server checks it on every call, not only by hiding
    tools from the model. A scheduled or background job runs under a named identity with
    the least rights it needs, and every record names who or what acted. Not built, and
    none of the sibling repositories has it: they declare tiers, not identities. Note it
    now so the role design can carry it later.

## Customer data layout (proposed, to confirm)

The owner's working model: each customer has its own folder with its schemas and
everything else about them. Collectors (mail first) fill each customer's inbox, and
admitted data is extracted into the customer's extracts and, where it is shared, into a
product-data area. This lives on the local machine,
outside this repository. The repository stays synthetic-only.

```text
<data root, outside the repository>/
  customers/<customer-id>/
    inbox/       raw messages and attachments, as received; never edited; hashed
    schema/      this customer's field declarations and mappings, each with its approver
    extracts/    parsed rows, each pointing back to its source file and row
    cases/       tickets opened for this customer
  product-data/  item master and other shared tables, built from confirmed mappings
```

Rules that follow from it:

- **Placement is recognition, not understanding.** A collector places a file into a
  customer's inbox only when the customer is unambiguous, for example by a known sender.
  An unknown or ambiguous sender is held back and goes to a ticket for a person; nothing is
  guessed from the content. Being in the inbox does not make a file trusted: admission still
  needs the person.
- **Attachments and message text are data, never instructions.** They are parsed by the
  same rules as any other file. A message cannot change a mapping or a schema.
- **Raw is kept; extracts are added, never overwritten.** Extraction writes new files; it
  never changes the inbox or an earlier extract.
- **Shared product data must not leak customer data.** The item master can be shared;
  customer names, orders and prices are not. The "confidential names must not leak" check
  applies to every answer that reads shared tables.
- **The mailbox account needs minimum access** (see item 17): read the one folder it
  needs, write nothing to the mail system.
- **Personal data stays out of the repository**, and out of any demo, until a synthetic
  replacement exists.

Open questions for the owner: how many customers are expected in the first pilot; whether
customers share part numbers (if they do, the item master is one table, not one per
customer); and who may read each customer's folder.

### Modules

Every processing step is a module, and the core does not know what any module does. A
module declares:

- **Input:** what it reads (a file in `inbox/`, a scanned page, a table).
- **Output and destination:** what it writes and where. An OCR reader, for example, writes
  text with a confidence per field to `customers/<id>/extracts/`.
- **Approver and limitations:** a named person establishes the module, and the known
  limitations are recorded with the approval (the Shop-flow pattern).
- **Failures:** a refusal becomes a ticket with the reason.

Adding an OCR reader means declaring its contract, establishing it, and pointing its output
at the customer folder. Nothing else changes. Its output is new data, so it opens a ticket
for a person to work through before it is admitted.

Collectors (mail, folder watchers) are modules too, with the same contract. They may run on
a schedule and write only to a customer's `inbox/`. They never write to `extracts/`, the
schema or the product data.

### What happens to an arriving file

A file that arrives for a known customer goes into that customer's `inbox/` and opens a
ticket. A folder hook detects the arrival: a trigger module that fires when a file is
created in an `inbox/` folder and does nothing else. On each arrival the hook:

1. waits until the file is complete (a partly written file is not processed);
2. hashes the file and checks the hash against the inbox ledger, so a repeated file is
   linked to its first arrival, not imported twice;
3. opens the ticket;
4. starts a **staged** import: parse and validate into a staging area, to pre-fill what each
   disposition would do. Staging writes nothing to `extracts/`, the schema or product data.

The hook does not admit anything. Admission is the person's choice of disposition on the
ticket, so the hook can be fully automatic without moving the human gate. The hook never
fires on `extracts/`, `schema/` or `product-data/`, which avoids loops. It runs under its own
named identity with the rights of an inbox writer (see item 17).

The ticket asks the person to choose one of three dispositions:

- **Import.** The file's content already fits an approved schema for this customer. The
  content is extracted (through an OCR or parsing module if it is a scan or a PDF) into
  `extracts/`, and each row keeps its source file and location.
- **Create schema.** The file does not fit yet. A new mapping for this customer is drafted
  (by the assistant, from the file, as options with evidence), and a person confirms it
  with their name recorded. Only then does the import run. A new schema for the customer
  is a schema change, so it always has an approver.
- **Drop.** The file is not needed (a duplicate, spam, out of scope). It stays in `inbox/`
  and is marked dropped with the reason. Nothing is deleted.

A PDF starts as unstructured data. Whether it can be imported depends on an extraction
module being established for that kind of document. Until one exists, the only
dispositions are create-schema-later or drop.

### Establishing a customer (separate process)

A file from a company with no folder is never placed in an inbox. It opens an
establishment ticket instead, handled as its own process:

1. The company is identified (name, identifiers, how its files are recognised).
2. A person creates the customer folder and records who approved it and why.
3. Only after that can collectors deliver files for the company.

Until a company is established, its files are held outside every customer folder, and the
held files are listed on the establishment ticket.

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
- **Identity-scoped access** is noted as a requirement (item 17), not built now.

Proposed, awaiting the owner's confirmation:

- **Customer folders and shared product data** as laid out above.
