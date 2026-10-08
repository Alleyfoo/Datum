"""Synthetic spare-parts company: a snapshot of today, plus a generated year of history.

The snapshot is ported from Predictive-Spare-Parts-Lab desk/data.py (origin recorded in
docs/provenance.md). The history is generated from a seed, so the same seed always gives
the same company. Nothing here belongs to a real company or supplier.

Stock is a ledger: each stock line's history replays to today's on-hand quantity from an
opening balance that is never negative. `conservation()` checks that.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Dict, List

from babel.schema import Refusal

from .schema import registry

AS_OF = date(2026, 10, 2)  # the desk's fixed "today", a Friday
HISTORY_DAYS = 365
SEED = 2026


class WorldError(ValueError):
    pass


def _ago(months: int) -> date:
    return AS_OF - timedelta(days=round(months * 30.4))


def snapshot() -> Dict[str, List[dict]]:
    warehouses = [
        {"code": "FI", "name": "Finnish warehouse", "country": "Finland"},
        {"code": "SE", "name": "Swedish warehouse", "country": "Sweden"},
    ]
    customers = [
        {"customer_id": "C-100", "name": "Sawmill customer", "site": "Sawmill, Central Finland", "country": "Finland"},
        {"customer_id": "C-200", "name": "Power plant customer", "site": "CHP plant, Western Sweden", "country": "Sweden"},
        {"customer_id": "C-300", "name": "Pulp mill customer", "site": "Pulp mill, Eastern Finland", "country": "Finland"},
    ]

    def m(mid, cust, name, typ, area, crit, x0, y0, x1, y1):
        return {"machine_id": mid, "customer_id": cust, "name": name, "type": typ, "area": area,
                "criticality": crit, "x0": x0, "y0": y0, "x1": x1, "y1": y1}

    machines = [
        m("BC-01", "C-100", "Bark conveyor", "Belt conveyor", "Debarking", "A", 0.5, 4, 3.5, 4),
        m("CR-01", "C-100", "Bark crusher", "Crusher", "Crushing", "A", 5.2, 4, 6.2, 4),
        m("BC-02", "C-100", "Crusher discharge conveyor", "Belt conveyor", "Crushing", "A", 6.9, 4, 8.8, 2),
        m("SC-01", "C-100", "Screen feed screw", "Screw conveyor", "Screening", "B", 10.3, 2, 11.7, 2),
        m("BC-03", "C-100", "Chip return conveyor", "Belt conveyor", "Screening", "B", 12.3, 2, 13.7, 4.6),
        m("BC-04", "C-100", "Stockpile conveyor", "Belt conveyor", "Storage", "B", 15.3, 2, 17.7, 0.6),
        m("BE-01", "C-100", "Boiler feed elevator", "Bucket elevator", "Boiler feed", "A", 19.5, 0.6, 19.5, 4.6),
        m("BC-05", "C-100", "Boiler day-bin conveyor", "Belt conveyor", "Boiler feed", "A", 20.2, 4.6, 22.8, 4.6),
        m("FR-01", "C-200", "Fuel reception conveyor", "Belt conveyor", "Reception", "A", 0.5, 3, 4.5, 3),
        m("SC-11", "C-200", "Fuel screen screw", "Screw conveyor", "Screening", "B", 6, 3, 8, 3),
        m("BC-11", "C-200", "Silo feed conveyor", "Belt conveyor", "Storage", "A", 9.5, 3, 13.5, 5),
        m("BC-12", "C-200", "Boiler feed conveyor", "Belt conveyor", "Boiler feed", "A", 15, 5, 19, 5),
        m("CH-01", "C-300", "Chip unloading conveyor", "Belt conveyor", "Chip yard", "B", 0.5, 2, 4.5, 2),
        m("CH-02", "C-300", "Chip pile reclaim screw", "Screw conveyor", "Chip yard", "A", 5.5, 2, 7.5, 2),
        m("CH-03", "C-300", "Digester feed conveyor", "Belt conveyor", "Digester feed", "A", 9, 2, 13, 4.5),
    ]

    def p(no, desc, cat, wear, lead, interval=None):
        return {"part_no": no, "description": desc, "category": cat, "wear_part": wear,
                "lead_time_days": lead, "service_interval_months": interval}

    parts = [
        p("SP-1001", "Conveyor belt EP630/4, 800 mm, per m", "Belt", True, 42, 36),
        p("SP-1002", "Conveyor belt EP800/4, 1000 mm, per m", "Belt", True, 49, 36),
        p("SP-1101", "Carrying idler 3-roll set, 800 mm", "Idler", True, 14, 24),
        p("SP-1102", "Return idler, 800 mm", "Idler", True, 14, 24),
        p("SP-1104", "Impact idler set, 1000 mm", "Idler", True, 28, 18),
        p("SP-1201", "Drive pulley, lagged, 500 mm", "Pulley", False, 70),
        p("SP-1202", "Tail pulley, 400 mm", "Pulley", False, 56),
        p("SP-1203", "Drive pulley, lagged, 630 mm", "Pulley", False, 84),
        p("SP-1301", "Spherical roller bearing 22216", "Bearing", True, 7, 24),
        p("SP-1311", "Spherical roller bearing 22216, alternative make", "Bearing", True, 10, 24),
        p("SP-1303", "Spherical roller bearing 22220", "Bearing", True, 7, 24),
        p("SP-1401", "Primary belt scraper blade, 800 mm", "Scraper", True, 10, 6),
        p("SP-1402", "Primary belt scraper blade, 1000 mm", "Scraper", True, 10, 6),
        p("SP-1501", "Helical bevel gearbox, 15 kW", "Drive", False, 98),
        p("SP-1502", "Electric motor 15 kW IE3", "Drive", False, 35),
        p("SP-1503", "Flexible coupling, size 5", "Drive", True, 14, 36),
        p("SP-1601", "Screw flight section, 400 mm", "Screw", True, 45, 18),
        p("SP-1701", "Elevator bucket, 300 mm", "Elevator", True, 30, 30),
        p("SP-1801", "Crusher hammer set", "Crusher", True, 63, 12),
    ]

    substitutes = [
        {"part_no": "SP-1301", "substitute_no": "SP-1311"},
        {"part_no": "SP-1311", "substitute_no": "SP-1301"},
    ]

    stock = [
        ("SP-1001", "FI", 60), ("SP-1002", "SE", 25),
        ("SP-1101", "FI", 18), ("SP-1101", "SE", 6),
        ("SP-1102", "FI", 4), ("SP-1102", "SE", 2),
        ("SP-1104", "FI", 2), ("SP-1202", "FI", 1), ("SP-1203", "SE", 1),
        ("SP-1301", "FI", 2), ("SP-1301", "SE", 4), ("SP-1311", "FI", 3),
        ("SP-1401", "FI", 3), ("SP-1402", "SE", 2), ("SP-1502", "FI", 1),
        ("SP-1503", "FI", 2), ("SP-1503", "SE", 2), ("SP-1701", "FI", 40),
        ("SP-1801", "FI", 1),
    ]

    def b(mid, part, qty, critical, last=None):
        return {"machine_id": mid, "part_no": part, "qty_installed": qty, "critical": critical,
                "last_replaced": _ago(last) if last is not None else None}

    bom = [
        b("BC-01", "SP-1001", 18, False, 30), b("BC-01", "SP-1101", 12, False, 20),
        b("BC-01", "SP-1201", 1, True), b("BC-01", "SP-1301", 4, True, 23),
        b("BC-01", "SP-1401", 1, False, 7), b("BC-01", "SP-1501", 1, True),
        b("CR-01", "SP-1801", 1, True, 11), b("CR-01", "SP-1303", 2, True, 26),
        b("BC-02", "SP-1002", 14, False, 12), b("BC-02", "SP-1104", 4, False, 17),
        b("BC-02", "SP-1203", 1, True), b("BC-02", "SP-1301", 4, True, 10),
        b("BC-02", "SP-1402", 1, False, 5), b("BC-02", "SP-1502", 1, True),
        b("SC-01", "SP-1601", 3, False, 19),
        b("BC-03", "SP-1001", 12, False, 8), b("BC-03", "SP-1102", 3, False, 25),
        b("BC-03", "SP-1202", 1, False), b("BC-03", "SP-1301", 2, True, 22),
        b("BC-04", "SP-1001", 9, False, 14), b("BC-04", "SP-1503", 1, True, 30),
        b("BE-01", "SP-1701", 60, False, 28),
        b("BC-05", "SP-1001", 8, False, 4), b("BC-05", "SP-1401", 1, False, 6),
        b("BC-05", "SP-1301", 2, True, 15),
        b("FR-01", "SP-1002", 20, False, 20), b("FR-01", "SP-1301", 4, True, 24),
        b("FR-01", "SP-1402", 1, False, 6),
        b("SC-11", "SP-1601", 4, False, 16),
        b("BC-11", "SP-1002", 16, False, 9), b("BC-11", "SP-1203", 1, True),
        b("BC-11", "SP-1301", 2, True, 21),
        b("BC-12", "SP-1001", 10, False, 33), b("BC-12", "SP-1503", 1, True, 35),
        b("CH-01", "SP-1002", 12, False, 28), b("CH-01", "SP-1402", 1, False, 2),
        b("CH-02", "SP-1601", 4, True, 17), b("CH-02", "SP-1502", 1, True),
        b("CH-03", "SP-1002", 18, False, 34), b("CH-03", "SP-1203", 1, True),
        b("CH-03", "SP-1301", 2, True, 12),
    ]

    orders = [
        {"po": "PO-4711", "part_no": "SP-1301", "warehouse": "FI", "qty": 6, "due": AS_OF + timedelta(days=12)},
        {"po": "PO-4718", "part_no": "SP-1601", "warehouse": "FI", "qty": 4, "due": AS_OF + timedelta(days=20)},
        {"po": "PO-4720", "part_no": "SP-1203", "warehouse": "FI", "qty": 1, "due": AS_OF + timedelta(days=55)},
    ]

    return {
        "warehouse": warehouses,
        "customer": customers,
        "machine": machines,
        "part": parts,
        "substitute": substitutes,
        "bom_line": bom,
        "stock_level": [{"part_no": pn, "warehouse": wh, "on_hand": q} for pn, wh, q in stock],
        "purchase_order": orders,
    }


def generate_history(tables: Dict[str, List[dict]], seed: int = SEED) -> Dict[str, List[dict]]:
    """Requests, deliveries and stock movements for the past year, from one seed.

    Requests are drawn forward in time. Each stock line is then replayed backwards from
    today's on-hand quantity: issues add stock back, receipts are only added where the
    balance can cover them, so the opening balance can never go negative.
    """
    rng = random.Random(seed)
    start = AS_OF - timedelta(days=HISTORY_DAYS)
    parts = {r["part_no"]: r for r in tables["part"]}
    stock = {(r["part_no"], r["warehouse"]): r["on_hand"] for r in tables["stock_level"]}

    raw_requests = []
    for line in tables["bom_line"]:
        part = parts[line["part_no"]]
        interval = part["service_interval_months"]
        planned = bool(part["wear_part"] and interval)
        rate = 1 / interval if planned else 0.08  # per month
        for month in range(HISTORY_DAYS // 30):
            if rng.random() >= rate:
                continue
            day = start + timedelta(days=month * 30 + rng.randrange(30))
            qty = rng.randint(1, max(1, min(line["qty_installed"], 4)))
            warehouse = next((wh for wh in ("FI", "SE") if (line["part_no"], wh) in stock), None)
            raw_requests.append({
                "machine_id": line["machine_id"], "part_no": line["part_no"], "qty": qty,
                "requested_on": day, "reason": "planned" if planned else "breakdown",
                "status": "fulfilled" if warehouse else "backordered", "warehouse": warehouse,
            })

    raw_requests.sort(key=lambda r: (r["requested_on"], r["machine_id"], r["part_no"]))
    requests = []
    for n, r in enumerate(raw_requests, start=1):
        requests.append({k: v for k, v in r.items() if k != "warehouse"} | {"request_id": f"RQ-{n:04d}"})

    deliveries: List[dict] = []
    movements: List[dict] = []
    for (part_no, wh), on_hand in sorted(stock.items()):
        issues = [(r["requested_on"], -r["qty"], r) for r in raw_requests
                  if r["status"] == "fulfilled" and r["part_no"] == part_no and r["warehouse"] == wh]
        receipts = []
        day = start + timedelta(days=rng.randrange(15, 45))
        while day < AS_OF:
            receipts.append((day, rng.randint(2, 12), None))
            day += timedelta(days=rng.randrange(40, 70))
        # forward, a receipt lands before an issue on the same day; walking back, the issue comes first
        timeline = sorted(issues + [(d, q, None) for d, q, _ in receipts],
                          key=lambda e: (e[0], e[1] < 0), reverse=True)

        balance = on_hand
        for day, qty, req in timeline:
            if qty < 0:
                balance += -qty  # walking back in time, an issue had taken stock out
                movements.append({"part_no": part_no, "warehouse": wh, "qty": qty, "kind": "issue",
                                  "occurred_on": day, "source": req})
            elif balance - qty >= 0:
                balance -= qty  # walking back, a receipt had put stock in
                movements.append({"part_no": part_no, "warehouse": wh, "qty": qty, "kind": "receipt",
                                  "occurred_on": day, "source": None})
                deliveries.append({"part_no": part_no, "warehouse": wh, "qty": qty, "delivered_on": day})

    # ids are assigned in date order, after the ledger is complete
    deliveries.sort(key=lambda d: (d["delivered_on"], d["part_no"], d["warehouse"]))
    for n, d in enumerate(deliveries, start=1):
        d["delivery_id"] = f"DL-{n:04d}"

    request_ids = {id(raw): req["request_id"] for raw, req in zip(raw_requests, requests)}
    movements.sort(key=lambda m: (m["occurred_on"], m["part_no"], m["warehouse"], m["kind"] == "issue"))
    delivery_by_key = {}
    for d in deliveries:
        delivery_by_key.setdefault((d["part_no"], d["warehouse"], d["delivered_on"]), d["delivery_id"])
    rows = []
    for n, m in enumerate(movements, start=1):
        source = m["source"]
        if m["kind"] == "issue":
            source_id = request_ids[id(source)]
        else:
            source_id = delivery_by_key[(m["part_no"], m["warehouse"], m["occurred_on"])]
        rows.append({"movement_id": f"MV-{n:05d}", "part_no": m["part_no"], "warehouse": m["warehouse"],
                     "qty": m["qty"], "kind": m["kind"], "occurred_on": m["occurred_on"],
                     "source": source_id})

    return {"request": requests, "delivery": deliveries, "stock_movement": rows}


def build(seed: int = SEED) -> Dict[str, List[dict]]:
    """The whole synthetic company, cleaned by the schema. Raises if anything is refused."""
    reg = registry()
    raw = snapshot()
    raw.update(generate_history(raw, seed))

    tables: Dict[str, List[dict]] = {}
    refusals: List[Refusal] = []
    for name in reg.names():
        rows, errors = reg.clean(name, raw.get(name, []))
        tables[name] = rows
        refusals += errors
    refusals += reg.check_refs(tables)
    if refusals:
        raise WorldError("; ".join(f"{r.table}[{r.row_no}] {r.code}: {r.message}" for r in refusals[:5]))

    problems = conservation(tables)
    if problems:
        raise WorldError("; ".join(problems[:5]))
    return tables


def conservation(tables: Dict[str, List[dict]]) -> List[str]:
    """Replay each stock line's movements from its opening balance. Return any breaks."""
    problems: List[str] = []
    requests = {r["request_id"]: r for r in tables["request"]}
    deliveries = {d["delivery_id"]: d for d in tables["delivery"]}
    for line in tables["stock_level"]:
        key = (line["part_no"], line["warehouse"])
        moves = sorted((m for m in tables["stock_movement"]
                        if (m["part_no"], m["warehouse"]) == key),
                       key=lambda m: (m["occurred_on"], m["movement_id"]))
        opening = line["on_hand"] - sum(m["qty"] for m in moves)
        if opening < 0:
            problems.append(f"{key}: opening balance {opening} is negative")
            continue
        balance = opening
        for m in moves:
            balance += m["qty"]
            if balance < 0:
                problems.append(f"{key}: balance goes negative on {m['occurred_on']}")
                break
            if m["kind"] == "issue":
                req = requests.get(m["source"])
                if req is None or req["status"] != "fulfilled" or -m["qty"] != req["qty"]:
                    problems.append(f"{key}: issue {m['movement_id']} does not match its request")
            elif m["kind"] == "receipt":
                if m["source"] not in deliveries or deliveries[m["source"]]["qty"] != m["qty"]:
                    problems.append(f"{key}: receipt {m['movement_id']} does not match its delivery")
            else:
                problems.append(f"{key}: unknown movement kind {m['kind']!r}")
        if not problems and balance != line["on_hand"]:
            problems.append(f"{key}: replay ends at {balance}, stock says {line['on_hand']}")
    return problems
