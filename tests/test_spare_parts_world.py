import copy
from datetime import timedelta

import pytest

from domains.spare_parts import build
from domains.spare_parts import world as world_module
from domains.spare_parts.world import AS_OF, HISTORY_DAYS, conservation, snapshot


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
