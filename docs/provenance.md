# Provenance

Every ported file or value records its origin, so the lab's frozen evidence stays intact.

| Here | Origin | Notes |
|---|---|---|
| `domains/spare_parts/world.py` `snapshot()` | Predictive-Spare-Parts-Lab `desk/data.py` at `a8843ea` | Customers, machines, parts, substitutes, stock, bill of materials and open purchase orders copied as values. Counts checked by `tests/test_spare_parts_world.py`. Date fixed at 2026-10-02, as in the desk. |
| `domains/spare_parts/world.py` `generate_history()` | New | Requests, deliveries and stock movements generated from a seed. Not in the lab. |
| `babel/schema/registry.py` | New | Field and cleaning rules. The lab's `desk/source_contract.py` holds the workbook rules that will be generalised later (phase 3). |
| `domains/spare_parts/data.py` record classes and `ServiceData` | Predictive-Spare-Parts-Lab `desk/data.py` at `fa3836f` (blob `7be9e2c`) | Field for field, in `0c7c97c`. `from_tables()` is new: the company is read from the schema's tables instead of the lab's literals, and `demo()` is `build()` read through it. Tables with a warehouse other than FI and SE are refused. The lab's `TODAY` is `world.AS_OF`. |
| `tests/golden/views/lab_reference/` | Output of Predictive-Spare-Parts-Lab `desk/views.py` at `fa3836f` | Captured once in `7181e03` by `scripts/capture_lab_reference.py`, which reads the five desk files with `git show` and runs them outside the lab. Evidence: never regenerated. |

Lab revision used as the reference for this port: `fa3836f` (HEAD at the time of the port).

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
