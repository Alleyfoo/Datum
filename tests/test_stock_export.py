from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from domains.spare_parts import build
from domains.spare_parts.exports import (
    HEADERS, RENAMED_FROM, RENAMED_TO, SHEET, WEEK_ENDING, stock_export, write_fixtures,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FIXTURES / "stock_export_2026-08-21.xlsx"
RENAMED = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"


def _cells(path):
    wb = load_workbook(path, read_only=True)
    try:
        return {ws.title: [list(row) for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()


def test_the_same_seed_gives_the_same_bytes(tmp_path):
    first = stock_export(tmp_path / "first.xlsx")
    second = stock_export(tmp_path / "second.xlsx")
    assert first.read_bytes() == second.read_bytes()


def test_the_committed_fixtures_are_what_the_generator_makes(tmp_path):
    made = write_fixtures(tmp_path)
    assert _cells(made["base"]) == _cells(BASE)
    assert _cells(made["renamed"]) == _cells(RENAMED)


def test_the_variant_differs_from_the_export_in_one_header_only():
    base, renamed = _cells(BASE)[SHEET], _cells(RENAMED)[SHEET]
    assert len(base) == len(renamed)
    differences = [(row, col, a, b)
                   for row, (left, right) in enumerate(zip(base, renamed), start=1)
                   for col, (a, b) in enumerate(zip(left, right), start=1) if a != b]
    assert all(len(left) == len(right) for left, right in zip(base, renamed))
    assert differences == [(1, HEADERS.index(RENAMED_FROM) + 1, RENAMED_FROM, RENAMED_TO)]


def test_the_export_is_every_stock_line_at_the_end_of_its_week():
    rows = _cells(BASE)[SHEET]
    assert rows[0] == list(HEADERS)
    world = build()
    today = {(r["part_no"], r["warehouse"]): r["on_hand"] for r in world["stock_level"]}
    later = {}
    for m in world["stock_movement"]:
        if m["occurred_on"] > WEEK_ENDING:
            later[(m["part_no"], m["warehouse"])] = later.get((m["part_no"], m["warehouse"]), 0) + m["qty"]
    assert len(rows) - 1 == len(today)
    for item, _description, warehouse, on_hand, stock_date in rows[1:]:
        assert on_hand + later.get((item, warehouse), 0) == today[(item, warehouse)]
        assert stock_date == datetime(2026, 8, 21)
    # the seeded history moved stock after this week, so the export is not just today's stock
    assert any(row[3] != today[(row[0], row[2])] for row in rows[1:])


def test_another_seed_gives_other_quantities(tmp_path):
    ours = _cells(stock_export(tmp_path / "ours.xlsx"))[SHEET]
    other = _cells(stock_export(tmp_path / "other.xlsx", seed=7))[SHEET]
    assert ours[0] == other[0]
    assert [row[3] for row in ours] != [row[3] for row in other]
