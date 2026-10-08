# Provenance

Every ported file or value records its origin, so the lab's frozen evidence stays intact.

| Here | Origin | Notes |
|---|---|---|
| `domains/spare_parts/world.py` `snapshot()` | Predictive-Spare-Parts-Lab `desk/data.py` at `a8843ea` | Customers, machines, parts, substitutes, stock, bill of materials and open purchase orders copied as values. Counts checked by `tests/test_spare_parts_world.py`. Date fixed at 2026-10-02, as in the desk. |
| `domains/spare_parts/world.py` `generate_history()` | New | Requests, deliveries and stock movements generated from a seed. Not in the lab. |
| `babel/schema/registry.py` | New | Field and cleaning rules. The lab's `desk/source_contract.py` holds the workbook rules that will be generalised later (phase 3). |

Lab revision used as the reference for this port: `fa3836f` (HEAD at the time of the port).
