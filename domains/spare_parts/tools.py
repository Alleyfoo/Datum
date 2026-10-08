"""Service rules: the facts and the plan behind the availability, lead-time and service answers.

Ported from Parts-Service-Desk desk/tools.py at 46c859a (blob 01979c9, the same file the views port
read from Predictive-Spare-Parts-Lab at fa3836f; origin in docs/provenance.md). The text of every
fact is the lab's, checked brief by brief against tests/golden/cs/lab_reference/.

Every tool returns ``Fact`` lines. A fact is a sentence the expert may repeat, plus the tool that
produced it, so the person checking the answer can see where each claim came from. The expert
never computes a date or a quantity itself: if it needs one, a tool states it.

A question is a recipe: a fixed list of tools. "Availability" always runs the same tools, so two
people asking about the same part see the same facts.

No model, no randomness, no clock: the date is the company's as-of date, ``AS_OF`` (the lab's
``TODAY``), and weekday names come from a fixed table, so the text does not follow the locale.
Records are named tuples where the lab had frozen dataclasses; the values are the same.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from .data import TRANSFER_DAYS, WAREHOUSES, BomLine, ServiceData
from .world import AS_OF

#: weekday names as the lab printed them, fixed here so the text does not follow the locale
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class Fact(NamedTuple):
    tool: str
    text: str


class Brief(NamedTuple):
    """Everything the expert is allowed to know for one question."""

    question: str
    customer: str
    machine: str
    part: str
    tools_run: Tuple[str, ...]
    facts: Tuple[Fact, ...]
    #: names and machine ids of *other* customers: must not reach the customer answer
    confidential: Tuple[str, ...] = ()
    #: the company rule the recommended plan applied, in a few words (not in the lab)
    rule: str = ""
    #: what the rules do not weigh for this answer, said instead of hidden (not in the lab)
    not_known: Tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"QUESTION: {self.question}",
                 f"CUSTOMER: {self.customer}",
                 f"MACHINE: {self.machine}",
                 f"PART: {self.part}",
                 f"TODAY: {_d(AS_OF)}",
                 "", "FACTS:"]
        lines += [f"- [{f.tool}] {f.text}" for f in self.facts]
        return "\n".join(lines)


def _d(day: date) -> str:
    """``Fri 2026-10-02``: the lab's ``f"{day:%a} {day.isoformat()}"`` in the C locale."""
    return f"{WEEKDAYS[day.weekday()]} {day.isoformat()}"


def home_warehouse(data: ServiceData, customer_id: str) -> str:
    """Finnish customers are served from FI, Swedish from SE (assumed)."""
    return "SE" if data.customers[customer_id].country == "Sweden" else "FI"


# -- tools -------------------------------------------------------------------


def machine_context(data: ServiceData, machine_id: str, part_no: str) -> List[Fact]:
    m = data.machines[machine_id]
    line = next(b for b in data.bom_of(machine_id) if b.part_no == part_no)
    crit = {"A": "stops production", "B": "degrades production", "C": "minor impact"}[m.criticality]
    facts = [Fact("machine_context",
                  f"{m.machine_id} {m.name} is criticality {m.criticality} ({crit} if it stops).")]
    facts.append(Fact("machine_context",
                      f"It uses {line.qty_installed} x {part_no}"
                      f"{' and the part is marked critical for this machine' if line.critical else ''}."))
    if line.last_replaced:
        facts.append(Fact("machine_context", f"Last replaced on {_d(line.last_replaced)}."))
    else:
        facts.append(Fact("machine_context", "No replacement date is recorded for this part on this machine."))
    return facts


def stock_by_warehouse(data: ServiceData, part_no: str) -> List[Fact]:
    p = data.parts[part_no]
    counts = ", ".join(f"{w} {data.on_hand(part_no, w)}" for w in WAREHOUSES)
    return [Fact("stock_by_warehouse", f"{part_no} {p.description}: on hand {counts}.")]


def incoming_orders(data: ServiceData, part_no: str) -> List[Fact]:
    orders = [o for o in data.incoming if o.part_no == part_no and o.due >= AS_OF]
    if not orders:
        return [Fact("incoming_orders", f"No open purchase orders for {part_no}.")]
    return [Fact("incoming_orders",
                 f"Purchase order {o.po}: {o.qty} x {part_no} due in {o.warehouse} on {_d(o.due)}.")
            for o in orders]


def lead_time(data: ServiceData, part_no: str) -> List[Fact]:
    p = data.parts[part_no]
    eta = AS_OF + timedelta(days=p.lead_time_days)
    return [Fact("lead_time",
                 f"Supplier lead time for {part_no} is {p.lead_time_days} days; "
                 f"ordered today it would arrive on {_d(eta)}.")]


def substitutes(data: ServiceData, part_no: str, qty: int) -> List[Fact]:
    p = data.parts[part_no]
    if not p.substitutes:
        return [Fact("substitutes", f"No approved substitute is recorded for {part_no}.")]
    out = []
    for s in p.substitutes:
        counts = ", ".join(f"{w} {data.on_hand(s, w)}" for w in WAREHOUSES)
        best = max(data.on_hand(s, w) for w in WAREHOUSES)
        cover = ("enough for the full set" if best >= qty
                 else f"not enough for the full set: at most {best} of the {qty} pcs needed from one warehouse")
        out.append(Fact("substitutes",
                        f"Approved substitute {s} {data.parts[s].description}: on hand {counts}; {cover}."))
    return out


def where_used(data: ServiceData, part_no: str, exclude_machine: str) -> List[Fact]:
    lines = [b for b in data.bom if b.part_no == part_no and b.machine_id != exclude_machine]
    if not lines:
        return [Fact("where_used", f"No other machine uses {part_no}.")]
    crit_a = [b for b in lines if data.machines[b.machine_id].criticality == "A"]
    names = ", ".join(f"{b.machine_id} ({data.customers[data.machines[b.machine_id].customer_id].name}, "
                      f"criticality {data.machines[b.machine_id].criticality}, {b.qty_installed} installed)"
                      for b in lines)
    return [Fact("where_used",
                 f"{part_no} is also used on {len(lines)} other machine{'' if len(lines) == 1 else 's'}, "
                 f"{len(crit_a)} of them criticality A: {names}.")]


def _due(data: ServiceData, part_no: str, exclude_machine: str, horizon_days: int):
    """(due date, bom line) for every other machine whose replacement falls due."""
    p = data.parts[part_no]
    horizon = AS_OF + timedelta(days=horizon_days)
    due = []
    for b in data.bom:
        if b.part_no != part_no or b.machine_id == exclude_machine or not b.last_replaced:
            continue
        when = b.last_replaced + timedelta(days=round(p.service_interval_months * 30.4))
        if when <= horizon:
            due.append((when, b))
    return due


def due_soon(data: ServiceData, part_no: str, exclude_machine: str, horizon_days: int = 60) -> List[Fact]:
    p = data.parts[part_no]
    if not p.service_interval_months:
        return [Fact("due_soon", f"{part_no} is replaced on failure, not on a schedule.")]
    due = _due(data, part_no, exclude_machine, horizon_days)
    if not due:
        return [Fact("due_soon", f"No other machine is due to replace {part_no} within {horizon_days} days.")]
    total = sum(b.qty_installed for _, b in due)
    detail = "; ".join(f"{b.machine_id} {'overdue since' if w < AS_OF else 'due'} {_d(w)} ({b.qty_installed} pcs)"
                       for w, b in sorted(due, key=lambda x: x[0]))
    return [Fact("due_soon",
                 f"Planned replacements of {part_no} on other machines within {horizon_days} days "
                 f"need {total} pcs: {detail}.")]


class Option(NamedTuple):
    arrives: date
    text: str
    #: the warehouse whose stock this option uses up, if any
    draws_from: Optional[str] = None
    #: the part whose stock it uses up, when that is an approved substitute and not the part asked about
    part_no: Optional[str] = None
    #: the purchase order it takes, if any: the rules do not weigh other claims on it (not_known)
    po: Optional[str] = None


def _options(data: ServiceData, part_no: str, customer_id: str, qty: int) -> List[Option]:
    """Ways to get ``qty`` to this customer, earliest first. All dates computed here.

    A substitute's option draws on the home warehouse's stock of the substitute, so it is checked
    for conflicts like any other stock (backlog C13); the lab left it unchecked.
    """
    home = home_warehouse(data, customer_id)
    other = next(w for w in WAREHOUSES if w != home)
    options: List[Option] = []
    if data.on_hand(part_no, home) >= qty:
        options.append(Option(AS_OF, f"from {home} stock, available today ({_d(AS_OF)})", home))
    if data.on_hand(part_no, other) >= qty:
        arrive = AS_OF + timedelta(days=TRANSFER_DAYS)
        options.append(Option(arrive, f"transfer from {other} stock, {TRANSFER_DAYS} days, arrives {_d(arrive)}", other))
    for sub in data.parts[part_no].substitutes:
        if data.on_hand(sub, home) >= qty:
            options.append(Option(AS_OF, f"approved substitute {sub} from {home} stock, available today ({_d(AS_OF)})",
                                  home, sub))
    for o in data.incoming:
        if o.part_no == part_no and o.qty >= qty and o.due >= AS_OF:
            arrive = o.due + timedelta(days=0 if o.warehouse == home else TRANSFER_DAYS)
            options.append(Option(arrive, f"from purchase order {o.po}, arrives {_d(arrive)}", po=o.po))
    eta = AS_OF + timedelta(days=data.parts[part_no].lead_time_days)
    options.append(Option(eta, f"new supplier order, arrives {_d(eta)}"))
    return sorted(options, key=lambda o: o.arrives)


def _shortfall(data: ServiceData, part_no: str, machine_id: str, qty: int, warehouse: str,
               horizon_days: int = 60):
    """(shortfall, [(due date, bom line)]) if taking ``qty`` from ``warehouse`` starves planned needs."""
    if not data.parts[part_no].service_interval_months:
        return 0, []
    served = [(when, b) for when, b in _due(data, part_no, machine_id, horizon_days)
              if home_warehouse(data, data.machines[b.machine_id].customer_id) == warehouse]
    need = sum(b.qty_installed for _, b in served)
    left = data.on_hand(part_no, warehouse) - qty
    return (need - left, served) if need and left < need else (0, served)


def conflicts(data: ServiceData, part_no: str, machine_id: str, qty: int,
              horizon_days: int = 60) -> List[Fact]:
    """What taking stock for this machine would do to other customers' planned needs.

    Computed here, not left to the expert: a small model will not reliably connect
    "stock in Sweden" with "a Swedish customer is due today".

    The part's own stock is stated warehouse by warehouse, as the lab does. An approved
    substitute's stock in the home warehouse is checked too (backlog C13): a substitute whose
    use would starve planned needs adds a CONFLICT line; one that starves nobody adds nothing,
    so the facts stay the lab's wherever nothing competes for the substitute.
    """
    return (_own_conflicts(data, part_no, machine_id, qty, horizon_days)
            + _substitute_conflicts(data, part_no, machine_id, qty, horizon_days))


def _starved(data: ServiceData, served) -> str:
    """The planned needs that would go short, as the lab names them in a CONFLICT line."""
    return ", ".join(f"{b.machine_id} ({data.customers[data.machines[b.machine_id].customer_id].name}, "
                     f"{b.qty_installed} pcs due {_d(when)})" for when, b in served)


def _substitute_conflicts(data: ServiceData, part_no: str, machine_id: str, qty: int,
                          horizon_days: int) -> List[Fact]:
    home = home_warehouse(data, data.machines[machine_id].customer_id)
    facts = []
    for sub in data.parts[part_no].substitutes:
        have = data.on_hand(sub, home)
        if have < qty:
            continue
        short, served = _shortfall(data, sub, machine_id, qty, home, horizon_days)
        if short:
            facts.append(Fact("conflicts",
                              f"CONFLICT: taking {qty} pcs of approved substitute {sub} from {home} leaves "
                              f"{have - qty} there, but {_starved(data, served)} "
                              f"{'is' if len(served) == 1 else 'are'} served from {home}: a shortfall of "
                              f"{short} pcs within {horizon_days} days."))
    return facts


def _own_conflicts(data: ServiceData, part_no: str, machine_id: str, qty: int,
                   horizon_days: int) -> List[Fact]:
    if not data.parts[part_no].service_interval_months:
        return [Fact("conflicts", "No planned replacements to conflict with; the part is replaced on failure.")]
    facts = []
    for w in WAREHOUSES:
        have = data.on_hand(part_no, w)
        if have < qty:
            continue
        short, served = _shortfall(data, part_no, machine_id, qty, w, horizon_days)
        if short:
            who = _starved(data, served)
            facts.append(Fact("conflicts",
                              f"CONFLICT: taking {qty} pcs from {w} leaves {have - qty} there, but {who} "
                              f"{'is' if len(served) == 1 else 'are'} served from {w}: a shortfall of "
                              f"{short} pcs within {horizon_days} days."))
        else:
            facts.append(Fact("conflicts",
                              f"Taking {qty} pcs from {w} leaves {have - qty} there, enough for the planned needs "
                              f"of machines served from {w} within {horizon_days} days."))
    return facts or [Fact("conflicts", f"No warehouse holds a full set of {qty} pcs, so no stock conflict arises.")]


def fastest_supply(data: ServiceData, part_no: str, customer_id: str, qty: int) -> List[Fact]:
    home = home_warehouse(data, customer_id)
    facts = [Fact("fastest_supply",
                  f"The customer is served from the {home} warehouse. Options for {qty} pcs, earliest first:")]
    facts += [Fact("fastest_supply", f"Option {i}: {o.text}.")
              for i, o in enumerate(_options(data, part_no, customer_id, qty), 1)]
    return facts


def recommended_plan(data: ServiceData, machine_id: str, part_no: str, qty: int,
                     situation: str) -> List[Fact]:
    """The decision, made by rules the company can read and change. The expert explains it.

    breakdown: the earliest option; if it starves another warehouse's planned
               needs, also order replacement stock for that warehouse today.
    planned:   the earliest option that starves nobody.

    An approved substitute's option is weighed against the planned needs for the substitute
    (backlog C13), and a breakdown that takes it restocks the substitute, with its own lead time.
    """
    return [Fact("recommended_plan", _choose(data, machine_id, part_no, qty, situation)[1])]


#: the company rule each situation applies, in a few words, for the receipt
PLAN_RULES = {
    "breakdown": "breakdown → fastest option",
    "planned": "planned service → earliest option that leaves no other planned need short",
}


def _choose(data: ServiceData, machine_id: str, part_no: str, qty: int, situation: str) -> Tuple[Option, str]:
    """The option the rules choose, and the plan's text."""
    m = data.machines[machine_id]
    options = _options(data, part_no, m.customer_id, qty)

    def short(o: Option) -> int:
        return _shortfall(data, o.part_no or part_no, machine_id, qty, o.draws_from)[0] if o.draws_from else 0

    if situation == "breakdown":
        chosen = options[0]
        text = f"RECOMMENDED PLAN (company rule for a breakdown: fastest option): {chosen.text}."
        gap = short(chosen)
        if gap:
            lead = data.parts[chosen.part_no or part_no].lead_time_days
            which = f" of {chosen.part_no}" if chosen.part_no else ""
            text += (f" Because this leaves {chosen.draws_from} short for planned needs, also order "
                     f"{gap} pcs{which} today to restock {chosen.draws_from}; with the {lead}-day lead time they "
                     f"arrive {_d(AS_OF + timedelta(days=lead))}.")
        return chosen, text

    chosen = next(o for o in options if not short(o))
    text = (f"RECOMMENDED PLAN (company rule for planned service: earliest option that leaves "
            f"no other planned need short): {chosen.text}.")
    skipped = [o for o in options if o.arrives < chosen.arrives and short(o)]
    if skipped:
        text += (f" The faster option ({skipped[0].text}) is not used because it would leave "
                 f"{skipped[0].draws_from} short for planned needs.")
    return chosen, text


def competing_claims(data: ServiceData, po: str, part_no: str, machine_id: str,
                     horizon_days: int = 60) -> str:
    """What the rules do not weigh when a plan takes an incoming order: the other planned needs.

    The conflict check covers stock on hand, not incoming orders, so a plan that takes a purchase
    order hands it over without weighing the other machines whose planned replacement of the same
    part falls due within the horizon and is served from the order's warehouse. They are named
    here, so the receipt says what the answer did not weigh instead of hiding it.
    """
    order = next(o for o in data.incoming if o.po == po)
    planned = data.parts[part_no].service_interval_months
    served = sorted(((when, b) for when, b in (_due(data, part_no, machine_id, horizon_days) if planned else [])
                     if home_warehouse(data, data.machines[b.machine_id].customer_id) == order.warehouse),
                    key=lambda x: x[0])
    if not served:
        return (f"competing claims on {order.po} are not modelled; no other planned need for {part_no} "
                f"is served from {order.warehouse} within {horizon_days} days")
    claims = [f"{b.machine_id} is {'overdue' if when < AS_OF else 'due on ' + _d(when)} for {b.qty_installed} pcs"
              for when, b in served]
    if home_warehouse(data, data.machines[machine_id].customer_id) == order.warehouse:
        where = f"{'also' if len(claims) == 1 else 'all also'} served from {order.warehouse}"
    else:
        where = f"served from {order.warehouse}, where the order arrives"
    return f"competing claims on {order.po} are not modelled: {' and '.join(claims)}, {where}"


# -- questions -----------------------------------------------------------------


SITUATIONS = {
    "breakdown": "the machine has stopped and is waiting for this part (breakdown)",
    "planned": "the part is needed for planned service; the machine is running",
}


def availability(data: ServiceData, machine_id: str, part_no: str,
                 situation: str = "breakdown") -> Brief:
    """Can we supply this part to this machine, how fast, and what else competes for it?

    ``situation`` comes from the person asking: only they know whether the
    machine is standing still. It changes the right answer, so it is a fact.
    """
    if situation not in SITUATIONS:
        raise ValueError(f"situation must be one of {sorted(SITUATIONS)}")
    m = data.machines[machine_id]
    line = next(b for b in data.bom_of(machine_id) if b.part_no == part_no)
    steps: List[Tuple[str, Callable[[], List[Fact]]]] = [
        ("machine_context", lambda: machine_context(data, machine_id, part_no)),
        ("stock_by_warehouse", lambda: stock_by_warehouse(data, part_no)),
        ("fastest_supply", lambda: fastest_supply(data, part_no, m.customer_id, line.qty_installed)),
        ("incoming_orders", lambda: incoming_orders(data, part_no)),
        ("lead_time", lambda: lead_time(data, part_no)),
        ("substitutes", lambda: substitutes(data, part_no, line.qty_installed)),
        ("conflicts", lambda: conflicts(data, part_no, machine_id, line.qty_installed)),
        ("where_used", lambda: where_used(data, part_no, machine_id)),
        ("due_soon", lambda: due_soon(data, part_no, machine_id)),
        ("recommended_plan", lambda: recommended_plan(data, machine_id, part_no,
                                                      line.qty_installed, situation)),
    ]
    facts: List[Fact] = [Fact("reported_by_person", f"The service person reports: {SITUATIONS[situation]}.")]
    for _, run in steps:
        facts += run()
    chosen, _ = _choose(data, machine_id, part_no, line.qty_installed, situation)
    return Brief(
        question=f"Availability of {part_no} for {machine_id}: can we supply a full set "
                 f"({line.qty_installed} pcs), how fast, and what else competes for the part?",
        customer=f"{data.customers[m.customer_id].name} ({data.customers[m.customer_id].site})",
        machine=f"{m.machine_id} {m.name}",
        part=f"{part_no} {data.parts[part_no].description}",
        tools_run=tuple(name for name, _ in steps),
        facts=tuple(facts),
        confidential=confidential(data, m.customer_id),
        rule=PLAN_RULES[situation],
        not_known=(competing_claims(data, chosen.po, part_no, machine_id),) if chosen.po else (),
    )


# -- service demand and lead time ----------------------------------------------------

HORIZON_DAYS = 90       # how far ahead service demand looks
BUNDLE_DAYS = 30        # parts due within this window of the first go on one visit
SPARE_LEAD_DAYS = 30    # a critical part replaced on failure, with a longer lead time, deserves a spare


def next_working_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def last_working_day(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def due_date(data: ServiceData, line: BomLine) -> Optional[date]:
    """When a scheduled part falls due on this machine; None if not scheduled or no history."""
    interval = data.parts[line.part_no].service_interval_months
    if not interval or not line.last_replaced:
        return None
    return line.last_replaced + timedelta(days=round(interval * 30.4))


def _ready(data: ServiceData, part_no: str, qty: int, home: str, machine_id: str) -> Tuple[date, str]:
    """Earliest date ``qty`` can be at the home warehouse for planned work, and how.

    Planned work follows the same rule as a planned availability question: stock
    that other machines' planned replacements need is not taken.
    """
    ready, how, _ = _readiness(data, part_no, qty, home, machine_id)
    return ready, how


def _readiness(data: ServiceData, part_no: str, qty: int, home: str,
               machine_id: str) -> Tuple[date, str, Optional[str]]:
    """``_ready``, with the purchase order it takes, if any."""
    other = next(w for w in WAREHOUSES if w != home)
    if data.on_hand(part_no, home) >= qty and not _shortfall(data, part_no, machine_id, qty, home)[0]:
        return AS_OF, f"reserve {qty} from {home} stock", None
    if data.on_hand(part_no, other) >= qty and not _shortfall(data, part_no, machine_id, qty, other)[0]:
        return AS_OF + timedelta(days=TRANSFER_DAYS), f"transfer {qty} from {other} stock", None
    for o in sorted(data.incoming, key=lambda o: o.due):
        if o.part_no == part_no and o.warehouse == home and o.qty >= qty and o.due >= AS_OF:
            return o.due, f"take {qty} from purchase order {o.po}", o.po
    lead = data.parts[part_no].lead_time_days
    held = [w for w in WAREHOUSES if data.on_hand(part_no, w) >= qty]
    note = (f"; {' and '.join(held)} stock is held for other planned replacements" if held else "")
    return AS_OF + timedelta(days=lead), f"order {qty} from the supplier ({lead}-day lead time){note}", None


def service_schedule(data: ServiceData, machine_id: str) -> List[Fact]:
    horizon = AS_OF + timedelta(days=HORIZON_DAYS)
    due, later, unknown, on_failure = [], [], [], []
    for b in data.bom_of(machine_id):
        p = data.parts[b.part_no]
        when = due_date(data, b)
        if not p.service_interval_months:
            on_failure.append(b)
        elif when is None:
            unknown.append(b)
        elif when <= horizon:
            due.append((when, b))
        else:
            later.append((when, b))
    facts = []
    for when, b in sorted(due, key=lambda x: x[0]):
        state = "overdue since" if when < AS_OF else "due"
        facts.append(Fact("service_schedule",
                          f"{b.part_no} {data.parts[b.part_no].description}: {b.qty_installed} pcs {state} "
                          f"{_d(when)} (replaced every {data.parts[b.part_no].service_interval_months} months, "
                          f"last on {_d(b.last_replaced)})."))
    if not due:
        facts.append(Fact("service_schedule", f"No scheduled part falls due within {HORIZON_DAYS} days."))
    if later:
        first_when, first = min(later, key=lambda x: x[0])
        facts.append(Fact("service_schedule",
                          f"{len(later)} other scheduled part{'s are' if len(later) != 1 else ' is'} due later; "
                          f"the next is {first.part_no} on {_d(first_when)}."))
    for b in unknown:
        facts.append(Fact("service_schedule",
                          f"{b.part_no} has a service interval but no replacement date is recorded, "
                          f"so its due date is unknown."))
    if on_failure:
        facts.append(Fact("service_schedule",
                          "Replaced on failure, not on a schedule: "
                          + ", ".join(f"{b.part_no} {data.parts[b.part_no].description}" for b in on_failure) + "."))
    return facts


def service_supply(data: ServiceData, machine_id: str) -> List[Fact]:
    m = data.machines[machine_id]
    home = home_warehouse(data, m.customer_id)
    horizon = AS_OF + timedelta(days=HORIZON_DAYS)
    facts = []
    for b in data.bom_of(machine_id):
        when = due_date(data, b)
        if when is None or when > horizon:
            continue
        ready, how = _ready(data, b.part_no, b.qty_installed, home, machine_id)
        lead = data.parts[b.part_no].lead_time_days
        if how.startswith("order"):
            order_by = last_working_day(when - timedelta(days=lead))
            if order_by >= AS_OF:
                timing = f"order by {_d(order_by)} to have it by the due date"
            else:
                timing = (f"too late to have it by the due date: ordered today it arrives {_d(ready)}, "
                          f"{(ready - max(when, AS_OF)).days} days after "
                          f"{'today' if when < AS_OF else 'the due date'}")
            facts.append(Fact("service_supply", f"{b.part_no}: not in stock in a full set; {how}; {timing}."))
        else:
            facts.append(Fact("service_supply", f"{b.part_no}: {how}, ready {_d(ready)}."))
    return facts or [Fact("service_supply", "Nothing scheduled within the horizon needs supplying.")]


def critical_spares(data: ServiceData, machine_id: str) -> List[Fact]:
    facts = []
    for b in data.bom_of(machine_id):
        p = data.parts[b.part_no]
        if p.service_interval_months or not b.critical:
            continue
        total = sum(data.on_hand(b.part_no, w) for w in WAREHOUSES)
        if total:
            facts.append(Fact("critical_spares",
                              f"Critical spare {b.part_no} {p.description}: {total} on hand."))
        else:
            eta = AS_OF + timedelta(days=p.lead_time_days)
            facts.append(Fact("critical_spares",
                              f"Critical spare {b.part_no} {p.description}: none on hand anywhere; "
                              f"if it failed today a new one would arrive {_d(eta)} "
                              f"({p.lead_time_days}-day lead time)."))
    return facts or [Fact("critical_spares", "This machine has no critical parts that are replaced on failure.")]


def service_plan(data: ServiceData, machine_id: str) -> List[Fact]:
    """The rules for a service visit, readable by the people who own them.

    - The visit covers every part due within BUNDLE_DAYS of the first one due.
    - It is held on the first due date, or later if a part cannot be ready by then
      (never in the past).
    - A critical part replaced on failure, with none on hand and a lead time over
      SPARE_LEAD_DAYS, gets one spare ordered now.
    """
    m = data.machines[machine_id]
    home = home_warehouse(data, m.customer_id)
    horizon = AS_OF + timedelta(days=HORIZON_DAYS)
    due = sorted(((due_date(data, b), b) for b in data.bom_of(machine_id)
                  if due_date(data, b) and due_date(data, b) <= horizon), key=lambda x: x[0])
    facts = []
    if due:
        first = due[0][0]
        bundle = [(w, b) for w, b in due if w <= first + timedelta(days=BUNDLE_DAYS)]
        rest = [(w, b) for w, b in due if (w, b) not in bundle]
        readiness = [(_ready(data, b.part_no, b.qty_installed, home, machine_id), b) for _, b in bundle]
        visit = next_working_day(max([max(first, AS_OF)] + [r[0] for r, _ in readiness]))
        actions = "; ".join(f"{b.part_no}: {r[1]}" for r, b in readiness)
        text = (f"RECOMMENDED PLAN (company rules: bundle parts due within {BUNDLE_DAYS} days of the first, "
                f"visit on a working day when all are ready): service visit on {_d(visit)}, replacing "
                + ", ".join(f"{b.qty_installed} x {b.part_no}" for _, b in bundle)
                + f". Actions: {actions}.")
        if rest:
            text += " Left for a later visit: " + ", ".join(f"{b.part_no} (due {_d(w)})" for w, b in rest) + "."
        facts.append(Fact("service_plan", text))
    else:
        facts.append(Fact("service_plan",
                          f"RECOMMENDED PLAN: no service visit needed within {HORIZON_DAYS} days."))
    for b in data.bom_of(machine_id):
        if _needs_spare(data, b):
            eta = AS_OF + timedelta(days=data.parts[b.part_no].lead_time_days)
            facts.append(Fact("service_plan",
                              f"RECOMMENDED PLAN (company rule: a critical part with a lead time over "
                              f"{SPARE_LEAD_DAYS} days must have a spare): order 1 x {b.part_no} today "
                              f"as a spare; it arrives {_d(eta)}."))
    return facts


def service_demand(data: ServiceData, machine_id: str, part_no: Optional[str] = None,
                   situation: str = "planned") -> Brief:
    """What will this machine need in the next 90 days, and can we have it ready?"""
    m = data.machines[machine_id]
    steps: List[Tuple[str, Callable[[], List[Fact]]]] = [
        ("machine_overview", lambda: [Fact("machine_overview",
                                           f"{m.machine_id} {m.name} ({m.type}) is criticality {m.criticality}; "
                                           f"it has {len(data.bom_of(machine_id))} part{'' if len(data.bom_of(machine_id)) == 1 else 's'} on its parts list.")]),
        ("service_schedule", lambda: service_schedule(data, machine_id)),
        ("service_supply", lambda: service_supply(data, machine_id)),
        ("critical_spares", lambda: critical_spares(data, machine_id)),
        ("service_plan", lambda: service_plan(data, machine_id)),
    ]
    facts: List[Fact] = []
    for _, run in steps:
        facts += run()
    return Brief(
        question=f"Service demand for {machine_id}: which parts fall due within {HORIZON_DAYS} days, "
                 f"can we have them ready, and when should the service visit be?",
        customer=f"{data.customers[m.customer_id].name} ({data.customers[m.customer_id].site})",
        machine=f"{m.machine_id} {m.name}",
        part="all parts on the machine's parts list",
        tools_run=tuple(name for name, _ in steps),
        facts=tuple(facts),
        confidential=confidential(data, m.customer_id),
        rule=_service_rule(data, machine_id),
        not_known=_service_claims(data, machine_id),
    )


SPARE_RULE = f"a critical part with a lead time over {SPARE_LEAD_DAYS} days keeps a spare"


def _needs_spare(data: ServiceData, line: BomLine) -> bool:
    """The spare rule of the service plan: critical, replaced on failure, a long lead and none held."""
    p = data.parts[line.part_no]
    return (line.critical and not p.service_interval_months and p.lead_time_days > SPARE_LEAD_DAYS
            and not any(data.on_hand(line.part_no, w) for w in WAREHOUSES))


def _service_rule(data: ServiceData, machine_id: str) -> str:
    """The rules the service plan applied, in a few words."""
    horizon = AS_OF + timedelta(days=HORIZON_DAYS)
    lines = data.bom_of(machine_id)
    if any(due_date(data, b) and due_date(data, b) <= horizon for b in lines):
        rule = (f"service visit → bundle parts due within {BUNDLE_DAYS} days of the first, "
                f"on a working day when all are ready")
    else:
        rule = f"service visit → none needed within {HORIZON_DAYS} days"
    return rule + (f"; {SPARE_RULE}" if any(_needs_spare(data, b) for b in lines) else "")


def _service_claims(data: ServiceData, machine_id: str) -> Tuple[str, ...]:
    """The incoming orders the service supply takes, each with the claims on it the rules do not weigh."""
    home = home_warehouse(data, data.machines[machine_id].customer_id)
    horizon = AS_OF + timedelta(days=HORIZON_DAYS)
    claims: List[str] = []
    for b in data.bom_of(machine_id):
        when = due_date(data, b)
        if when is None or when > horizon:
            continue
        po = _readiness(data, b.part_no, b.qty_installed, home, machine_id)[2]
        if po:
            claim = competing_claims(data, po, b.part_no, machine_id)
            if claim not in claims:
                claims.append(claim)
    return tuple(claims)


#: the rules the lead-time plan applies, in a few words: which one decided is kept on the brief
LEAD_TIME_RULES = {
    "free": "scheduled part → take free stock or an incoming order before ordering anew",
    "order": "scheduled part → order by the last working day before the due date less the lead time",
    "spare": f"critical part replaced on failure → {SPARE_RULE}",
    "none": "part replaced on failure → no order until it is needed",
}


def lead_time_plan(data: ServiceData, machine_id: str, part_no: str) -> List[Fact]:
    """When must we order? Rules, not judgement."""
    return [Fact("lead_time_plan", f"RECOMMENDED PLAN: {_lead_time_decision(data, machine_id, part_no)[0]}.")]


def _lead_time_decision(data: ServiceData, machine_id: str, part_no: str) -> Tuple[str, str, Optional[str]]:
    """The lead-time plan's text, the rule that decided it, and the purchase order it takes, if any."""
    m = data.machines[machine_id]
    line = next(b for b in data.bom_of(machine_id) if b.part_no == part_no)
    p = data.parts[part_no]
    home = home_warehouse(data, m.customer_id)
    total = sum(data.on_hand(part_no, w) for w in WAREHOUSES)
    eta = AS_OF + timedelta(days=p.lead_time_days)
    when = due_date(data, line)
    po = None
    if when is not None:
        ready, how, po = _readiness(data, part_no, line.qty_installed, home, machine_id)
        need = (f"the replacement overdue since {_d(when)}" if when < AS_OF
                else f"the next replacement due {_d(when)}")
        if not how.startswith("order"):
            text, rule = f"no new order needed for {need}: {how}, ready {_d(ready)}", "free"
        else:
            order_by = last_working_day(when - timedelta(days=p.lead_time_days))
            text = (f"order {line.qty_installed} pcs by {_d(order_by)} for the replacement due {_d(when)}"
                    if order_by >= AS_OF else
                    f"order {line.qty_installed} pcs today; they arrive {_d(eta)}, after the due date {_d(when)}")
            rule = "order"
    elif line.critical and total == 0 and p.lead_time_days > SPARE_LEAD_DAYS:
        text = (f"keep a spare (company rule: critical, lead time over {SPARE_LEAD_DAYS} days): "
                f"order 1 pc today, it arrives {_d(eta)}")
        rule = "spare"
    else:
        text, rule = "no order needed now; the part is replaced on failure and the spare rule does not apply", "none"
    return text, LEAD_TIME_RULES[rule], po


def lead_time_question(data: ServiceData, machine_id: str, part_no: str,
                       situation: str = "planned") -> Brief:
    """How long does this part take to get, and when must we order it?"""
    m = data.machines[machine_id]
    line = next(b for b in data.bom_of(machine_id) if b.part_no == part_no)

    def next_need() -> List[Fact]:
        when = due_date(data, line)
        if when:
            return [Fact("next_need", f"The next planned replacement on {machine_id} is "
                                      f"{'overdue since' if when < AS_OF else 'due'} {_d(when)}.")]
        return [Fact("next_need", f"{part_no} is not replaced on a schedule on {machine_id}; "
                                  f"it is needed when it fails.")]

    def transfer() -> List[Fact]:
        return [Fact("transfer", f"Moving stock between the FI and SE warehouses takes {TRANSFER_DAYS} days.")]

    steps: List[Tuple[str, Callable[[], List[Fact]]]] = [
        ("machine_context", lambda: machine_context(data, machine_id, part_no)),
        ("stock_by_warehouse", lambda: stock_by_warehouse(data, part_no)),
        ("lead_time", lambda: lead_time(data, part_no)),
        ("incoming_orders", lambda: incoming_orders(data, part_no)),
        ("transfer", transfer),
        ("next_need", next_need),
        ("lead_time_plan", lambda: lead_time_plan(data, machine_id, part_no)),
    ]
    facts: List[Fact] = []
    for _, run in steps:
        facts += run()
    _, rule, po = _lead_time_decision(data, machine_id, part_no)
    return Brief(
        question=f"Lead time of {part_no} for {machine_id}: how long does it take to get, "
                 f"and when must we order it?",
        customer=f"{data.customers[m.customer_id].name} ({data.customers[m.customer_id].site})",
        machine=f"{m.machine_id} {m.name}",
        part=f"{part_no} {data.parts[part_no].description}",
        tools_run=tuple(name for name, _ in steps),
        facts=tuple(facts),
        confidential=confidential(data, m.customer_id),
        rule=rule,
        not_known=(competing_claims(data, po, part_no, machine_id),) if po else (),
    )


def confidential(data: ServiceData, customer_id: str) -> Tuple[str, ...]:
    """Names and machine ids of every other customer: they must not reach this customer's answer."""
    return tuple(term for other in data.customers.values() if other.customer_id != customer_id
                 for term in [other.name] + [x.machine_id for x in data.machines_of(other.customer_id)])


#: question name -> (recipe, needs a part selected)
QUESTIONS: Dict[str, Tuple[Callable[..., Brief], bool]] = {
    "Availability": (availability, True),
    "Lead time": (lead_time_question, True),
    "Service demand": (service_demand, False),
}
