"""The spare-parts entities, declared once for the core registry.

Customers have machines; machines use parts (bill of materials); parts are stocked in
warehouses and move through a ledger of receipts and issues; requests come from machines
and are fulfilled or backordered; purchase orders are open until they arrive.
"""

from __future__ import annotations

from babel.schema import Entity, Field, Registry


def _f(name, type, *, required=True, unit=None, ref=None):
    return Field(name, type, required=required, unit=unit, ref=ref)


ENTITIES = (
    Entity("warehouse", ("code",), (
        _f("code", "text"), _f("name", "text"), _f("country", "text"),
    )),
    Entity("customer", ("customer_id",), (
        _f("customer_id", "text"), _f("name", "text"), _f("site", "text"), _f("country", "text"),
    )),
    Entity("machine", ("machine_id",), (
        _f("machine_id", "text"),
        _f("customer_id", "text", ref="customer"),
        _f("name", "text"), _f("type", "text"), _f("area", "text"),
        _f("criticality", "text"),  # A stops production, B degrades it, C minor
        _f("x0", "decimal"), _f("y0", "decimal"), _f("x1", "decimal"), _f("y1", "decimal"),
    )),
    Entity("part", ("part_no",), (
        _f("part_no", "text"), _f("description", "text"), _f("category", "text"),
        _f("wear_part", "bool"),
        _f("lead_time_days", "int", unit="days"),
        _f("service_interval_months", "int", required=False, unit="months"),
    )),
    Entity("substitute", ("part_no", "substitute_no"), (
        _f("part_no", "text", ref="part"), _f("substitute_no", "text", ref="part"),
    )),
    Entity("bom_line", ("machine_id", "part_no"), (
        _f("machine_id", "text", ref="machine"), _f("part_no", "text", ref="part"),
        _f("qty_installed", "int", unit="pcs"), _f("critical", "bool"),
        _f("last_replaced", "date", required=False),
    )),
    Entity("stock_level", ("part_no", "warehouse"), (
        _f("part_no", "text", ref="part"), _f("warehouse", "text", ref="warehouse"),
        _f("on_hand", "int", unit="pcs"),
    )),
    Entity("purchase_order", ("po",), (
        _f("po", "text"), _f("part_no", "text", ref="part"),
        _f("warehouse", "text", ref="warehouse"), _f("qty", "int", unit="pcs"), _f("due", "date"),
    )),
    Entity("request", ("request_id",), (
        _f("request_id", "text"), _f("machine_id", "text", ref="machine"),
        _f("part_no", "text", ref="part"), _f("qty", "int", unit="pcs"),
        _f("requested_on", "date"),
        _f("reason", "text"),   # planned | breakdown
        _f("status", "text"),   # fulfilled | backordered
    )),
    Entity("delivery", ("delivery_id",), (
        _f("delivery_id", "text"), _f("part_no", "text", ref="part"),
        _f("warehouse", "text", ref="warehouse"), _f("qty", "int", unit="pcs"),
        _f("delivered_on", "date"),
    )),
    Entity("stock_movement", ("movement_id",), (
        _f("movement_id", "text"), _f("part_no", "text", ref="part"),
        _f("warehouse", "text", ref="warehouse"),
        _f("qty", "int", unit="pcs"),   # receipts positive, issues negative
        _f("kind", "text"),             # receipt | issue
        _f("occurred_on", "date"),
        _f("source", "text"),           # delivery_id for receipts, request_id for issues
    )),
)


def registry() -> Registry:
    reg = Registry()
    for entity in ENTITIES:
        reg.declare(entity)
    return reg
