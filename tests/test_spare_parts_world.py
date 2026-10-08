import copy
import random
from datetime import date, timedelta

import pytest

from domains.spare_parts import build
from domains.spare_parts import world as world_module
from domains.spare_parts.world import AS_OF, HISTORY_DAYS, conservation, draw, generate_history, ledger, snapshot


@pytest.fixture(scope="module")
def world():
    return build()


def test_snapshot_matches_the_desk_company(world):
    # counts ported from Predictive-Spare-Parts-Lab desk/data.py
    assert len(world["customer"]) == 3
    assert len(world["machine"]) == 15
    assert len(world["part"]) == 19
    assert len(world["bom_line"]) == 41
    assert len(world["purchase_order"]) == 3


def test_every_reference_resolves(world):
    from domains.spare_parts.schema import registry

    assert registry().check_refs(world) == []


def test_stock_is_a_ledger_that_replays_to_today(world):
    assert conservation(world) == []
    # every stock line has movements, so the replay is not trivially empty
    lines = {(m["part_no"], m["warehouse"]) for m in world["stock_movement"]}
    assert len(lines) > 10


def test_history_covers_the_last_year_and_stays_before_today(world):
    dates = [r["requested_on"] for r in world["request"]]
    assert min(dates) >= AS_OF - timedelta(days=HISTORY_DAYS)
    assert max(dates) < AS_OF
    assert world["request"], "a company with no requests has no history to analyse"


def test_requests_are_fulfilled_or_backordered_and_issues_match(world):
    statuses = {r["status"] for r in world["request"]}
    assert statuses <= {"fulfilled", "backordered"}
    issued = {m["source"] for m in world["stock_movement"] if m["kind"] == "issue"}
    fulfilled = {r["request_id"] for r in world["request"] if r["status"] == "fulfilled"}
    assert issued == fulfilled


def test_same_seed_gives_the_same_company():
    assert build(7) == build(7)


def test_different_seed_gives_a_different_history():
    assert build(7)["request"] != build(8)["request"]


def test_a_broken_ledger_is_caught(world):
    broken = dict(world)
    moves = [dict(m) for m in world["stock_movement"]]
    moves[0] = dict(moves[0], qty=moves[0]["qty"] + 1)
    broken["stock_movement"] = moves
    assert conservation(broken)


def _one_line_company():
    """One part on one machine, stocked on one line that ends the year at zero.

    With seed 41 the history has a receipt and an issue on the same day, and the
    balance before that day is smaller than the issue (found by searching seeds).
    """
    return {
        "part": [{"part_no": "SP-X", "description": "Test part", "category": "Test",
                  "wear_part": True, "lead_time_days": 7, "service_interval_months": 1}],
        "bom_line": [{"machine_id": "M-1", "part_no": "SP-X", "qty_installed": 4,
                      "critical": True, "last_replaced": None}],
        "stock_level": [{"part_no": "SP-X", "warehouse": "FI", "on_hand": 0}],
    }


def test_same_day_receipt_and_issue_replays_without_going_negative():
    # B5: a same-day issue replayed before its receipt made the balance negative
    company = _one_line_company()
    history = generate_history(company, seed=41)
    moves = sorted(history["stock_movement"], key=lambda m: (m["occurred_on"], m["movement_id"]))
    opening = company["stock_level"][0]["on_hand"] - sum(m["qty"] for m in moves)

    same_day = sorted({m["occurred_on"] for m in moves if m["kind"] == "receipt"}
                      & {m["occurred_on"] for m in moves if m["kind"] == "issue"})
    assert same_day, "the fixture must keep a receipt and an issue on one day"
    day = same_day[0]
    before = opening + sum(m["qty"] for m in moves if m["occurred_on"] < day)
    issued = -sum(m["qty"] for m in moves if m["occurred_on"] == day and m["kind"] == "issue")
    assert before - issued < 0, "issue-first on that day would go negative"

    assert opening >= 0
    assert conservation({**company, **history}) == []
    kinds_that_day = [m["kind"] for m in moves if m["occurred_on"] == day]
    assert kinds_that_day == sorted(kinds_that_day, key=lambda k: k == "issue")


def _stock(tables):
    return {(r["part_no"], r["warehouse"]): r["on_hand"] for r in tables["stock_level"]}


def test_each_issue_points_to_its_own_request_whatever_the_order_of_the_requests():
    # B2: the link was found by id() of the request dict and the order of two lists; it is now the request's id
    tables = snapshot()
    requests, receipts = draw(tables)
    expected = ledger(_stock(tables), requests, receipts)
    for seed in (1, 2, 3):
        shuffled = copy.deepcopy(requests)
        random.Random(seed).shuffle(shuffled)
        assert ledger(_stock(tables), shuffled, receipts) == expected
    by_id = {r["request_id"]: r for r in requests}
    issues = [m for m in expected[1] if m["kind"] == "issue"]
    assert len({m["source"] for m in issues}) == len(issues) == sum(r["status"] == "fulfilled" for r in requests)
    for m in issues:
        r = by_id[m["source"]]
        assert (r["status"], r["part_no"], r["warehouse"], -r["qty"], r["requested_on"]) == (
            "fulfilled", m["part_no"], m["warehouse"], m["qty"], m["occurred_on"])


def test_two_requests_on_one_line_and_day_keep_their_own_issues_in_either_order():
    day = date(2026, 6, 1)
    small = {"request_id": "RQ-0001", "machine_id": "M-1", "part_no": "SP-X", "qty": 1, "requested_on": day,
             "reason": "breakdown", "status": "fulfilled", "warehouse": "FI"}
    large = dict(small, request_id="RQ-0002", machine_id="M-2", qty=3)
    for order in ([small, large], [large, small]):
        _, movements = ledger({("SP-X", "FI"): 5}, order, {})
        assert [(m["movement_id"], m["source"], m["qty"]) for m in movements] == [
            ("MV-00001", "RQ-0001", -1), ("MV-00002", "RQ-0002", -3)]


def test_two_receipts_on_one_line_and_day_each_point_to_their_own_delivery():
    # B3: the delivery was found by (part, warehouse, date), so both receipts pointed to the first one
    day = date(2026, 6, 1)
    for offered in ([(day, 3), (day, 5)], [(day, 5), (day, 3)]):
        deliveries, movements = ledger({("SP-X", "FI"): 10}, [], {("SP-X", "FI"): offered})
        assert [(d["delivery_id"], d["qty"], d["delivered_on"]) for d in deliveries] == [
            ("DL-0001", 3, day), ("DL-0002", 5, day)]
        assert [(m["kind"], m["source"], m["qty"], m["occurred_on"]) for m in movements] == [
            ("receipt", "DL-0001", 3, day), ("receipt", "DL-0002", 5, day)]
        tables = {"stock_level": [{"part_no": "SP-X", "warehouse": "FI", "on_hand": 10}],
                  "request": [], "delivery": deliveries, "stock_movement": movements}
        assert conservation(tables) == []


def _build_on(monkeypatch, held, history=None):
    """Run build() on one snapshot object the test keeps hold of."""
    monkeypatch.setattr(world_module, "snapshot", lambda: held)
    if history is not None:
        monkeypatch.setattr(world_module, "generate_history", history)
    return world_module.build()


def _changed_tables(held, before):
    return sorted(name for name in before if held.get(name) != before[name])


def test_snapshot_is_not_mutated_by_build(monkeypatch):
    held = snapshot()
    before = copy.deepcopy(held)
    _build_on(monkeypatch, held)
    assert _changed_tables(held, before) == []
    # build adds the generated history to its working tables and nothing else
    assert set(held) - set(before) == {"request", "delivery", "stock_movement"}


def test_the_snapshot_check_catches_a_mutation(monkeypatch):
    real_history = world_module.generate_history

    def mutating_history(tables, seed):
        tables["part"][0]["lead_time_days"] += 1
        return real_history(tables, seed)

    held = snapshot()
    before = copy.deepcopy(held)
    _build_on(monkeypatch, held, history=mutating_history)
    assert _changed_tables(held, before) == ["part"]
