# Provenance

Every ported file or value records its origin, so the lab's frozen evidence stays intact.

| Here | Origin | Notes |
|---|---|---|
| `domains/spare_parts/world.py` `snapshot()` | Predictive-Spare-Parts-Lab `desk/data.py` at `a8843ea` | Customers, machines, parts, substitutes, stock, bill of materials and open purchase orders copied as values. Counts checked by `tests/test_spare_parts_world.py`. Date fixed at 2026-10-02, as in the desk. |
| `domains/spare_parts/world.py` `generate_history()` | New | Requests, deliveries and stock movements generated from a seed. Not in the lab. |
| `babel/schema/registry.py` | New | Field and cleaning rules. The lab's `desk/source_contract.py` holds the workbook rules that will be generalised later (phase 3). |

Lab revision used as the reference for this port: `fa3836f` (HEAD at the time of the port).

## Rules read (Read items)

Read on 2026-10-08 from `mcp-messy-data` at commit `3e9a0925da4a445457ddaa2a2cb1a7c7cec3b766`
(`git -C <path> rev-parse HEAD`). Only the rules were read for these items; code that applies
them is written here and listed in the table above when it lands.

| ID | Rule read | Read from | Lands in |
|---|---|---|---|
| R1 | Every cell is stored as text plus a one-character type code; nothing is trimmed, parsed, coerced, de-duplicated or renamed. Blank rows are kept and flagged; total rows are kept, because calling a row a total is a judgement. Column ids are mechanical (`c001`), and the source label travels as data, never as an identifier. Each row carries its source file, sheet, exact source row and ordinal. A dataset records a fingerprint over its logical content, and verification rebuilds it from raw evidence and compares. | `docs/ARCHITECTURE.md` (Staging), `src/mcpdd/cells.py`, `src/mcpdd/staging.py` | `babel/intake/staging.py` (C2). The brief narrows the codes to `e s n b d f x`, and `f` keeps the cached value; messy-data keeps `f` only for a formula with no cached value. |
| R2 | An assumption has a scope (`GLOBAL`, `DOMAIN`, `SUPPLIER`, `FILE_FAMILY`, `RUN`) and a lifecycle (`OBSERVED`, `PROVISIONAL`, `APPROVED`, `REJECTED`, `SUPERSEDED`). It can only be created as observed or provisional. Approval needs a named human approver, and agent-sounding names (`agent`, `assistant`, `llm`, `system`, `mcp`, `claude`) are rejected. Terminal states cannot be decided again; superseding keeps the old statement and links both ways. The decision log is an append-only record of who decided what, when and why. A first observation never becomes global truth by itself. | `docs/ARCHITECTURE.md` (Knowledge), `docs/DOCTRINE.md` (Assumption model, Knowledge model), `src/mcpdd/knowledge.py` lines 185–215 | approver checks in `babel/record` and the create-schema gate (C5, C8, C9) |
| R4 | A mapping run gives one result per source row and target field, each with status, source row and columns, source value, target value, rule chain and reason; an empty source cell has its own status so absence is not hidden. Executors are pure and deterministic with decimal arithmetic. The result is a candidate, not an import: the decision and record tables are hashed before and after the run and must be identical. Each validation check is tested to fail on a tampered result. A rule is previewed (matches, empty sources, differences) before it runs. | `docs/F4.1-MAPPING-EXECUTION.md` (Steps 1, 2, 5), `docs/F4.2-EXTRACTION.md` lines 104–109 (preview) | per-cell results of the trial (C4); before/after record hashes belong to Publish, not built in this run |
| R5 | A reference workbook is registered with authority `MANUAL_REFERENCE`: comparison evidence only, never a mapping input and never an authority over a ruling. Its reader accepts only such datasets, and mapping refuses a snapshot built from one. A mismatch with it is a finding; it never feeds back into a rule. | `docs/F4.2-EXTRACTION.md` Step 0 (lines 13–40), `src/mcpdd/sources.py` lines 151–161 | not built in this run: no reference workbook exists yet; recorded for the intake modules |

## Sources to read and port (not yet ported)

These are defined elsewhere. Each item in [backlog.md](backlog.md) under *Read* points here.
When a piece is ported, record the commit read and the commit it lands in.

| Source | Bring in | Lands in |
|---|---|---|
| Predictive-Spare-Parts-Lab `desk/cases.py`, `case_evidence.py`, `evidence_intake.py` | case store, immutable evidence, typed findings, claims | `babel/record` |
| Predictive-Spare-Parts-Lab `desk/source_contract.py`, `source_publication.py` | bounded workbook reading, recognition, refusal, provenance | `babel/intake` |
| Predictive-Spare-Parts-Lab `desk/expert.py` | answer checks | `babel/checks` |
| Predictive-Spare-Parts-Lab `desk/tools.py`, `views.py`, `mcp_server.py` | availability, lead time, service plan rules; menus | `domains/spare_parts`, `babel/mcp` |
| Predictive-Spare-Parts-Lab `predictive_lab/intermittent.py`, `temporal.py` | TSB and Croston, as-of features | `babel/analytics` |
| Spare-Parts-Readiness | coverage map | `domains/spare_parts` view |
| Shop-flow `docs/adr/0019` (Decision 4), `0021`, `src/shopflow/worklist.py` | close-of-day worklist | `babel/record` |
| Shop-flow `docs/adr/0019` (role table, Decision 1) | four roles and the model's removal from the recurring path | role definitions in `babel/mcp` and the domain pack |
| Shop-flow `docs/adr/0020`, `src/shopflow/established.py` | sender recognition as routing; refusal of unknown sources; establishment with a named approver | `babel/intake` |
| Shop-flow `docs/adr/0014`, `0015` | evidence packet: the reasoner reads a vetted product, never the ledger | case evidence in `babel/record` |
| Governed Data Lab `ARCHITECTURE.md` (A1-1, A1-3) | Case ≠ Worker; 0/1/many applicability | `babel/intake` bindings, `babel/record` |
| Governed Data Lab `src/execution/` | deterministic execution with no LLM reachable | core rule, tested |
| Shopflow-furniture `src/shopflow/mcp_server.py` | tiers declared in the MCP protocol | `babel/mcp` |
| Learning Lab | unknown path: observe, propose, human confirms, source established | `babel/intake` establishment |
| `mcp-messy-data` `docs/DOCTRINE.md`, `ARCHITECTURE.md`, `F4.1`, `F4.2` | the import pipeline and its rules | `babel/intake`, `babel/schema`, `babel/record` |
