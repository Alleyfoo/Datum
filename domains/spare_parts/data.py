"""The company as the desk sees it: the ServiceData shape the views read, built from the tables.

Ported from Predictive-Spare-Parts-Lab desk/data.py (origin in docs/provenance.md). The record
classes and ServiceData are the lab's, field for field. The lab's demo() wrote the company out as
literals; here from_tables() reads it from the schema's tables, so the company is defined once,
in world.snapshot().

    customers      who they are
    machines       what each customer has installed, where, how critical
    parts          the item master: description, lead time, substitutes
    stock          on hand per warehouse (FI, SE)
    bom            which parts each machine uses, and when each was last replaced
    incoming       purchase orders already on the way, with due dates
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from .world import build

#: the warehouses the desk draws, in column order
WAREHOUSES = ("FI", "SE")
#: days to move stock between the FI and SE warehouses: the lab's assumption, kept as it is
TRANSFER_DAYS = 3


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    site: str
    country: str


@dataclass(frozen=True)
class Machine:
    machine_id: str
    customer_id: str
    name: str
    type: str
    area: str
    criticality: str          # A = stops production, B = degrades it, C = minor
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Part:
    part_no: str
    description: str
    category: str
    wear_part: bool
    lead_time_days: int
    #: interval for a wear part, in months; None for parts replaced on failure
    service_interval_months: Optional[int] = None
    substitutes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BomLine:
    machine_id: str
    part_no: str
    qty_installed: int
    critical: bool
    last_replaced: Optional[date] = None


@dataclass(frozen=True)
class Incoming:
    po: str
    part_no: str
    qty: int
    warehouse: str
    due: date


@dataclass
class ServiceData:
    customers: Dict[str, Customer]
    machines: Dict[str, Machine]
    parts: Dict[str, Part]
    stock: Dict[Tuple[str, str], int]          # (part_no, warehouse) -> qty
    bom: List[BomLine]
    incoming: List[Incoming] = field(default_factory=list)

    def machines_of(self, customer_id: str) -> List[Machine]:
        return [m for m in self.machines.values() if m.customer_id == customer_id]

    def bom_of(self, machine_id: str) -> List[BomLine]:
        return [b for b in self.bom if b.machine_id == machine_id]

    def on_hand(self, part_no: str, warehouse: str) -> int:
        return self.stock.get((part_no, warehouse), 0)


def from_tables(tables: Dict[str, List[dict]]) -> ServiceData:
    """ServiceData from the schema's tables, every record in table order.

    The views draw exactly the FI and SE columns, so tables with other warehouses are
    refused rather than shown without them.
    """
    codes = tuple(row["code"] for row in tables["warehouse"])
    if codes != WAREHOUSES:
        raise ValueError(f"the desk draws warehouses {WAREHOUSES}; the tables hold {codes}")
    substitutes: Dict[str, List[str]] = {}
    for row in tables["substitute"]:
        substitutes.setdefault(row["part_no"], []).append(row["substitute_no"])

    customers = [Customer(customer_id=r["customer_id"], name=r["name"], site=r["site"], country=r["country"])
                 for r in tables["customer"]]
    machines = [Machine(machine_id=r["machine_id"], customer_id=r["customer_id"], name=r["name"],
                        type=r["type"], area=r["area"], criticality=r["criticality"],
                        x0=r["x0"], y0=r["y0"], x1=r["x1"], y1=r["y1"])
                for r in tables["machine"]]
    parts = [Part(part_no=r["part_no"], description=r["description"], category=r["category"],
                  wear_part=r["wear_part"], lead_time_days=r["lead_time_days"],
                  service_interval_months=r["service_interval_months"],
                  substitutes=tuple(substitutes.get(r["part_no"], ())))
             for r in tables["part"]]
    bom = [BomLine(machine_id=r["machine_id"], part_no=r["part_no"], qty_installed=r["qty_installed"],
                   critical=r["critical"], last_replaced=r["last_replaced"])
           for r in tables["bom_line"]]
    incoming = [Incoming(po=r["po"], part_no=r["part_no"], qty=r["qty"], warehouse=r["warehouse"], due=r["due"])
                for r in tables["purchase_order"]]
    return ServiceData(
        customers={c.customer_id: c for c in customers},
        machines={m.machine_id: m for m in machines},
        parts={p.part_no: p for p in parts},
        stock={(r["part_no"], r["warehouse"]): r["on_hand"] for r in tables["stock_level"]},
        bom=bom,
        incoming=incoming,
    )


def demo() -> ServiceData:
    """The synthetic company, as the lab's demo() gave it: build() read through from_tables()."""
    return from_tables(build())
