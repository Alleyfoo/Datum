"""Synthetic weekly stock export: the Excel file the ERP would send each week.

Adapted from mcp-messy-data's fixtures/synthetic/make_fixtures.py (origin in
docs/provenance.md): the same plain openpyxl workbook building, filled from this
company's stock instead of a supplier sheet. On hand is the quantity at the end of the
export's week, replayed back from today's stock through the ledger, so the history's
seed decides the values. The same seed and week always give the same bytes: the
document times and the zip entry times are fixed.

Run as a module to regenerate the committed test fixtures:

    python -m domains.spare_parts.exports tests/fixtures
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Sequence

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

from .world import AS_OF, SEED, build

SHEET = "Stock"
HEADERS = ("Item", "Description", "Warehouse", "On hand", "Stock date")
RENAMED_FROM, RENAMED_TO = "On hand", "Quantity on hand"  # the one header the variant changes
# Six Fridays before the desk's "today": the latest week where seed 2026's history has
# changed the stock (in the five later weeks nothing moved, so the seed would not show).
WEEK_ENDING = AS_OF - timedelta(weeks=6)
FIXED_TIME = datetime(2026, 1, 1)


def stock_rows(tables: Dict[str, List[dict]], week_ending: date) -> List[tuple]:
    """One row per stock line: today's on hand minus every movement after the week ended."""
    if week_ending > AS_OF:
        raise ValueError(f"week ending {week_ending} is after today ({AS_OF})")
    descriptions = {p["part_no"]: p["description"] for p in tables["part"]}
    later: Dict[tuple, int] = {}
    for m in tables["stock_movement"]:
        if m["occurred_on"] > week_ending:
            key = (m["part_no"], m["warehouse"])
            later[key] = later.get(key, 0) + m["qty"]
    rows = []
    for line in sorted(tables["stock_level"], key=lambda r: (r["part_no"], r["warehouse"])):
        key = (line["part_no"], line["warehouse"])
        on_hand = line["on_hand"] - later.get(key, 0)
        if on_hand < 0:  # the ledger's conservation check makes this impossible
            raise ValueError(f"{key}: on hand {on_hand} at {week_ending}")
        rows.append((line["part_no"], descriptions[line["part_no"]], line["warehouse"],
                     on_hand, week_ending))
    return rows


def workbook_bytes(header: Sequence[str], rows: Sequence[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    wb.properties.creator = "Babel Tower synthetic data"
    wb.properties.created = wb.properties.modified = FIXED_TIME
    raw = io.BytesIO()
    # ExcelWriter directly: save_workbook would stamp the current time as "modified"
    ExcelWriter(wb, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED)).save()
    return _with_fixed_entry_times(raw.getvalue())


def _with_fixed_entry_times(data: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=FIXED_TIME.timetuple()[:6])
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 0  # otherwise the platform decides
            dst.writestr(entry, src.read(info.filename))
    return out.getvalue()


def stock_export(path, *, seed: int = SEED, week_ending: date = WEEK_ENDING,
                 renamed: bool = False) -> Path:
    header = list(HEADERS)
    if renamed:
        header[header.index(RENAMED_FROM)] = RENAMED_TO
    path = Path(path)
    path.write_bytes(workbook_bytes(header, stock_rows(build(seed), week_ending)))
    return path


def write_fixtures(target, *, seed: int = SEED, week_ending: date = WEEK_ENDING) -> Dict[str, Path]:
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    stem = f"stock_export_{week_ending.isoformat()}"
    return {
        "base": stock_export(target / f"{stem}.xlsx", seed=seed, week_ending=week_ending),
        "renamed": stock_export(target / f"{stem}_renamed.xlsx", seed=seed,
                                week_ending=week_ending, renamed=True),
    }


if __name__ == "__main__":
    for name, written in write_fixtures(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures").items():
        print(f"{name}: {written}")
