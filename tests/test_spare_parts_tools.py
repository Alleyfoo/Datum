"""due_date, the service rule the views read, ported from the lab's desk/tools.py."""

from datetime import date

from domains.spare_parts.data import BomLine, demo
from domains.spare_parts.tools import due_date


def _line(data, machine_id: str, part_no: str) -> BomLine:
    return next(b for b in data.bom_of(machine_id) if b.part_no == part_no)


def test_a_scheduled_part_falls_due_one_interval_after_its_last_replacement():
    data = demo()
    assert due_date(data, _line(data, "BC-01", "SP-1301")) == date(2026, 11, 2)  # every 24 months
    assert due_date(data, _line(data, "BC-01", "SP-1401")) == date(2026, 9, 1)   # every 6 months, overdue


def test_no_due_date_without_a_schedule_or_a_replacement_date():
    data = demo()
    assert due_date(data, _line(data, "BC-01", "SP-1201")) is None  # replaced on failure
    assert due_date(data, BomLine("BC-01", "SP-1301", 4, True, last_replaced=None)) is None
