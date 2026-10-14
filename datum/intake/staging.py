"""Reveal: one sheet of a preserved workbook, staged as text cells with type codes.

Staging decides no meaning. Every cell is kept as its text plus a one-character code:

    e  empty        s  string       n  number       b  boolean
    d  date, time or duration (ISO text; a duration is written PT<seconds>S)
    f  formula: the text is its cached value ("" when the file holds none); the formula
       and the cached value's own code are kept beside the row
    x  Excel error literal (#N/A, #REF!, ...)

Staging decides nothing about a formula: it keeps the formula and the value the file saved for
it, as raw evidence. Taking that value as the cell's calculated value is the first step of the
cleaning stage (cleaning.py, F1, owner answer P20), which never writes staging.

Nothing is trimmed, parsed, coerced, de-duplicated or renamed. Column ids are mechanical
(c001, c002, ...), and a header is only the text of a row. Every row keeps its source id,
sheet, source row and ordinal; a row of empty cells is kept and flagged blank. Only the empty
rows after the last row with content are left out: they hold no value and appear only where
the producing software wrote formatting.

The workbook is read twice with openpyxl in read-only mode, once for cached values and once for
formulas. The sheet's own dimension record is ignored, because a stale one would silently cut
rows. The fingerprint covers the logical content (sheet, width, every row's codes, texts and
formulas), not the file's bytes or ids; verify() rebuilds the rows from the raw file and compares.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import zip_longest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import load_workbook

from .inbox import customer_dir, inbox_file

VERSION = 1
MANIFEST = "manifest.json"
ROWS = "rows.jsonl"


class StagingError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Row:
    source_row: int
    codes: str
    texts: Tuple[str, ...]
    #: column id -> (formula text, code of the cached value)
    formulas: Dict[str, Tuple[str, str]]

    @property
    def blank(self) -> bool:
        return set(self.codes) <= {"e"}


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    source_id: str
    sheet: str
    sheet_index: int
    width: int
    rows: Tuple[Row, ...]
    fingerprint: str

    @property
    def columns(self) -> List[str]:
        return [column_id(i) for i in range(1, self.width + 1)]

    def row(self, source_row: int) -> Optional[Row]:
        return self.rows[source_row - 1] if 1 <= source_row <= len(self.rows) else None


def column_id(ordinal: int) -> str:
    return f"c{ordinal:03d}"


def dataset_id_for(source_id: str, sheet: str) -> str:
    return "ds_" + hashlib.sha256(f"{source_id}\x1f{sheet}".encode("utf-8")).hexdigest()[:16]


def _duration(value: timedelta) -> str:
    return f"PT{value.total_seconds()!r}S"


def _render(value, data_type) -> Tuple[str, str]:
    if value is None:
        return "", "e"
    if data_type == "e":
        return str(value), "x"
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), "b"
    if isinstance(value, int):
        return str(value), "n"
    if isinstance(value, float):
        return repr(value), "n"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(), "d"
    if isinstance(value, timedelta):
        return _duration(value), "d"
    if isinstance(value, str):
        return value, "s"
    raise StagingError("unknown_cell_value", f"a cell holds a {type(value).__name__}, which staging cannot render")


def _formula(value) -> str:
    return value if isinstance(value, str) else (getattr(value, "text", None) or str(value))


def _unreadable(error: Exception) -> StagingError:
    return StagingError("unreadable_workbook", f"{type(error).__name__}: {error}")


def _open(path: Path, data_only: bool):
    try:
        return load_workbook(path, read_only=True, data_only=data_only)
    except Exception as error:  # any failure to open is "unreadable"; its message is the evidence
        raise _unreadable(error) from None


def sheet_names(path) -> List[str]:
    book = _open(Path(path), data_only=True)
    try:
        return list(book.sheetnames)
    finally:
        book.close()


def _grid(values, formulas, sheet: str) -> List[list]:
    """Cells as (text, code, formula) per row: cached values from one pass, formulas from the other."""
    if sheet not in values.sheetnames:
        raise StagingError("unknown_sheet", f"no sheet named {sheet!r}; sheets: {values.sheetnames}")
    value_sheet, formula_sheet = values[sheet], formulas[sheet]
    value_sheet.reset_dimensions()
    formula_sheet.reset_dimensions()
    grid = []
    for value_row, formula_row in zip_longest(value_sheet.iter_rows(), formula_sheet.iter_rows(), fillvalue=()):
        cells = []
        for value_cell, formula_cell in zip_longest(value_row, formula_row, fillvalue=None):
            text, code = _render(getattr(value_cell, "value", None), getattr(value_cell, "data_type", "n"))
            formula = None
            if getattr(formula_cell, "data_type", None) == "f":
                formula = (_formula(formula_cell.value), code)
                code = "f"
            cells.append((text, code, formula))
        grid.append(cells)
    return grid


def read_sheet(path, sheet: str) -> Tuple[int, Tuple[Row, ...], int]:
    """Return (width, rows, rows the reader yielded) for one sheet of a workbook."""
    values = _open(Path(path), True)
    try:
        formulas = _open(Path(path), False)
        try:
            grid = _grid(values, formulas, sheet)
        except StagingError:
            raise
        except Exception as error:  # a malformed sheet part is unreadable too
            raise _unreadable(error) from None
        finally:
            formulas.close()
    finally:
        values.close()

    width = max((i + 1 for cells in grid for i, cell in enumerate(cells) if cell[1] != "e"), default=0)
    last = max((n for n, cells in enumerate(grid, start=1) if any(c[1] != "e" for c in cells)), default=0)
    rows = []
    for number, cells in enumerate(grid[:last], start=1):
        cells = cells + [("", "e", None)] * (width - len(cells))
        rows.append(Row(
            source_row=number,
            codes="".join(c[1] for c in cells[:width]),
            texts=tuple(c[0] for c in cells[:width]),
            formulas={column_id(i): c[2] for i, c in enumerate(cells[:width], start=1) if c[2] is not None},
        ))
    return width, tuple(rows), len(grid)


def _line(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def fingerprint(sheet: str, width: int, rows) -> str:
    digest = hashlib.sha256()
    digest.update(_line(["babel-staging", VERSION, sheet, width]))
    for row in rows:
        digest.update(_line([row.source_row, row.codes, list(row.texts),
                             {k: list(v) for k, v in row.formulas.items()}]))
    return digest.hexdigest()


def staging_dir(root, company_id: str, source_id: str) -> Path:
    return customer_dir(root, company_id) / "staging" / source_id


def stage(root, company_id: str, source_id: str, sheet: str) -> Dataset:
    """Stage one sheet of a preserved file. Staging the same sheet again returns the stored dataset."""
    dataset_id = dataset_id_for(source_id, sheet)
    folder = staging_dir(root, company_id, source_id) / dataset_id
    if (folder / MANIFEST).exists():
        return load(root, company_id, source_id, dataset_id)
    path = inbox_file(root, company_id, source_id)
    names = sheet_names(path)
    if sheet not in names:
        raise StagingError("unknown_sheet", f"no sheet named {sheet!r}; sheets: {names}")
    width, rows, rows_read = read_sheet(path, sheet)
    dataset = Dataset(dataset_id, source_id, sheet, names.index(sheet) + 1, width, rows,
                      fingerprint(sheet, width, rows))
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ROWS, "wb") as handle:
        for ordinal, row in enumerate(rows, start=1):
            handle.write(_line({
                "row_uid": f"{dataset_id}:{row.source_row}", "source_id": source_id, "sheet": sheet,
                "source_row": row.source_row, "row_ordinal": ordinal, "codes": row.codes,
                "texts": list(row.texts), "formulas": {k: list(v) for k, v in row.formulas.items()},
                "blank": row.blank,
            }))
    record = {
        "dataset_id": dataset_id, "source_id": source_id, "company_id": company_id, "sheet": sheet,
        "sheet_index": dataset.sheet_index, "width": width, "columns": dataset.columns,
        "row_count": len(rows), "rows_read": rows_read,
        "blank_rows": [r.source_row for r in rows if r.blank], "fingerprint": dataset.fingerprint,
        "staging_version": VERSION,
    }
    (folder / MANIFEST).write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True),
                                   encoding="utf-8", newline="\n")
    return dataset


def stage_all(root, company_id: str, source_id: str) -> List[Dataset]:
    """Every sheet of a preserved file, in workbook order."""
    return [stage(root, company_id, source_id, name)
            for name in sheet_names(inbox_file(root, company_id, source_id))]


def _stored(root, company_id: str, source_id: str, dataset_id: str) -> Tuple[dict, Tuple[Row, ...]]:
    folder = staging_dir(root, company_id, source_id) / dataset_id
    if not (folder / MANIFEST).exists():
        raise StagingError("unknown_dataset", f"{dataset_id} is not staged for {source_id}")
    record = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    rows = []
    for line in (folder / ROWS).read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        rows.append(Row(item["source_row"], item["codes"], tuple(item["texts"]),
                        {k: tuple(v) for k, v in item["formulas"].items()}))
    return record, tuple(rows)


def load(root, company_id: str, source_id: str, dataset_id: str) -> Dataset:
    """A stored dataset. Rows that no longer hash to the recorded fingerprint are refused."""
    record, rows = _stored(root, company_id, source_id, dataset_id)
    if fingerprint(record["sheet"], record["width"], rows) != record["fingerprint"]:
        raise StagingError("staging_corrupt", f"stored rows of {dataset_id} do not match its fingerprint")
    return Dataset(dataset_id, source_id, record["sheet"], record["sheet_index"], record["width"],
                   rows, record["fingerprint"])


def datasets(root, company_id: str, source_id: str) -> List[Dataset]:
    folder = staging_dir(root, company_id, source_id)
    found = [load(root, company_id, source_id, p.name)
             for p in (folder.iterdir() if folder.exists() else ()) if (p / MANIFEST).exists()]
    return sorted(found, key=lambda d: d.sheet_index)


def rebuild(root, company_id: str, source_id: str, sheet: str) -> Dataset:
    """The dataset as the raw file gives it now, without reading or writing staging."""
    path = inbox_file(root, company_id, source_id)
    names = sheet_names(path)
    width, rows, _ = read_sheet(path, sheet)
    return Dataset(dataset_id_for(source_id, sheet), source_id, sheet, names.index(sheet) + 1, width,
                   rows, fingerprint(sheet, width, rows))


def verify(root, company_id: str, source_id: str, dataset_id: str) -> dict:
    """Rebuild from the raw file and compare with the recorded and the stored fingerprints."""
    record, rows = _stored(root, company_id, source_id, dataset_id)
    stored = fingerprint(record["sheet"], record["width"], rows)
    rebuilt = rebuild(root, company_id, source_id, record["sheet"]).fingerprint
    return {"dataset_id": dataset_id, "recorded": record["fingerprint"], "stored": stored,
            "rebuilt": rebuilt, "reproducible": record["fingerprint"] == stored == rebuilt}
