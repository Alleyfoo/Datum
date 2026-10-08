"""The trial: a staged file tried strictly against one header schema.

These are the Reveal and Map stages for one file. Every cell under a declared header gets a
result: accepted with its typed value, or refused with a reason and the rule it broke. A file fits
only with zero refusals. Header similarity, a guessed synonym or a position match never makes a
file fit, and nothing is trimmed or coerced to make a value pass.

A file that does not fit is classified by deterministic checks, in this order:

1. wrong_file: fewer than half of the declared headers appear on any row of any sheet. The file is
   not this company's file of this kind, and its values are not compared at all.
2. structural_change: enough headers appear to know the file, but the sheet, the header row or the
   header list differs (a header renamed, added, removed or moved). Values are not compared.
3. schema_defect: the structure matches and cells are refused, and the same schema also refuses a
   file the company already accepted. The schema is suspect, not the file.
4. value_problem: the structure matches, cells are refused, and the accepted files still pass.

The half-of-the-headers line is mcp-messy-data's recognition rule (DRIFT versus UNKNOWN).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from babel.schema.headers import Column, HeaderSchema

from .staging import Dataset, Row, column_id

OUTCOMES = ("fits", "wrong_file", "structural_change", "schema_defect", "value_problem")
INTEGER = re.compile(r"-?\d+")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(T00:00:00)?")
DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?)?")


@dataclass(frozen=True)
class Cell:
    sheet: str
    row: int
    column: str
    header: Optional[str]
    text: str
    code: str
    status: str  # accepted | refused
    rule: str
    reason: Optional[str] = None
    value: object = None  # the typed value of an accepted cell; a decimal stays its exact text


@dataclass
class Result:
    outcome: str
    schema_digest: str
    sheet: Optional[str] = None
    header_row: Optional[int] = None
    headers_found: int = 0
    differences: List[dict] = field(default_factory=list)
    cells: List[Cell] = field(default_factory=list)
    rows_checked: int = 0
    evidence: dict = field(default_factory=dict)
    fingerprints: Dict[str, str] = field(default_factory=dict)

    @property
    def fits(self) -> bool:
        return self.outcome == "fits"

    @property
    def refusals(self) -> List[Cell]:
        return [c for c in self.cells if c.status == "refused"]

    @property
    def rows_refused(self) -> int:
        return len({c.row for c in self.refusals})

    def to_dict(self) -> dict:
        """What a finding keeps: everything but the accepted cells' values."""
        return {
            "outcome": self.outcome, "schema_digest": self.schema_digest, "sheet": self.sheet,
            "header_row": self.header_row, "headers_found": self.headers_found,
            "differences": self.differences, "rows_checked": self.rows_checked,
            "rows_refused": self.rows_refused, "cells_checked": len(self.cells),
            "cells_refused": len(self.refusals),
            "refusals": [{k: v for k, v in asdict(c).items() if k != "value"} for c in self.refusals],
            "evidence": self.evidence, "fingerprints": self.fingerprints,
        }

    def digest(self) -> str:
        """Covers every cell result, so two runs agree only if they agree on every cell."""
        whole = {**self.to_dict(), "cells": [asdict(c) for c in self.cells]}
        canonical = json.dumps(whole, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _locate(datasets: Sequence[Dataset], schema: HeaderSchema) -> Optional[Tuple[int, Dataset, Row]]:
    """The row, on any sheet, holding the most declared headers as text cells.

    Ties go to the declared sheet, then the declared row, then the earlier sheet and row.
    """
    declared = set(schema.names)
    best, best_key = None, None
    for dataset in datasets:
        for row in dataset.rows:
            count = len({t for t, c in zip(row.texts, row.codes) if c == "s" and t in declared})
            key = (count, dataset.sheet == schema.sheet, row.source_row == schema.header_row,
                   -dataset.sheet_index, -row.source_row)
            if best_key is None or key > best_key:
                best, best_key = (count, dataset, row), key
    return best


def _structure(schema: HeaderSchema, dataset: Dataset, row: Row, sheets: List[str]) -> Tuple[List[dict], dict]:
    differences = []
    if dataset.sheet != schema.sheet:
        differences.append({"kind": "sheet", "expected": schema.sheet, "found": dataset.sheet, "sheets": sheets})
    if row.source_row != schema.header_row:
        differences.append({"kind": "header_row", "expected": schema.header_row, "found": row.source_row})
    names = schema.names
    positions: Dict[str, List[str]] = {}
    for ordinal, (text, code) in enumerate(zip(row.texts, row.codes), start=1):
        if code == "s":
            positions.setdefault(text, []).append(column_id(ordinal))
    for ordinal in range(1, max(len(names), dataset.width) + 1):
        expected = names[ordinal - 1] if ordinal <= len(names) else None
        text, code = (row.texts[ordinal - 1], row.codes[ordinal - 1]) if ordinal <= dataset.width else ("", "e")
        if (code == "s" and text == expected) or (expected is None and code == "e"):
            continue
        differences.append({"kind": "header", "column": column_id(ordinal), "expected": expected,
                            "found": None if code == "e" else text, "code": code})
    summary = {
        "missing": [n for n in names if n not in positions],
        "added": [text for text, code in zip(row.texts, row.codes)
                  if code != "e" and (code != "s" or text not in names)],
        "moved": [{"name": n, "expected": column_id(i), "found": positions[n]}
                  for i, n in enumerate(names, start=1) if n in positions and column_id(i) not in positions[n]],
    }
    return differences, summary


def _cell(sheet: str, row: int, ordinal: int, column: Column, text: str, code: str) -> Cell:
    rule, where = f"C{ordinal}", column_id(ordinal)

    def refuse(reason: str, rule_id: str = rule) -> Cell:
        return Cell(sheet, row, where, column.name, text, code, "refused", rule_id, reason)

    def accept(value) -> Cell:
        return Cell(sheet, row, where, column.name, text, code, "accepted", rule, None, value)

    if code == "f":
        return refuse("formula_cell", "R6")
    if code == "x":
        return refuse("error_cell", "R6")
    if code == "e":
        return refuse("missing_value") if column.required else accept(None)
    kind = column.type
    if kind == "text":
        if code != "s":
            return refuse("wrong_type")
        return accept(text) if text.strip() else refuse("blank_text")
    if kind == "bool":
        return accept(text == "TRUE") if code == "b" else refuse("wrong_type")
    if kind in ("int", "decimal"):
        if code != "n":
            return refuse("wrong_type")
        if kind == "int":
            return accept(int(text)) if INTEGER.fullmatch(text) else refuse("not_integer")
        return accept(text) if math.isfinite(float(text)) else refuse("non_finite")
    if code != "d":
        return refuse("wrong_type")
    if kind == "date":
        match = DATE.fullmatch(text)
        return accept(match.group(1)) if match else refuse("not_a_date")
    return accept(text) if DATETIME.fullmatch(text) else refuse("not_a_datetime")


def _values(schema: HeaderSchema, dataset: Dataset) -> Tuple[List[Cell], int]:
    cells: List[Cell] = []
    data_rows = dataset.rows[schema.header_row:]
    for row in data_rows:
        if row.blank:
            cells.append(Cell(dataset.sheet, row.source_row, "", None, "", "e" * dataset.width,
                              "refused", "R4", "blank_row"))
            continue
        for ordinal, column in enumerate(schema.columns, start=1):
            text, code = (row.texts[ordinal - 1], row.codes[ordinal - 1]) if ordinal <= dataset.width else ("", "e")
            cells.append(_cell(dataset.sheet, row.source_row, ordinal, column, text, code))
        for ordinal in range(len(schema.columns) + 1, dataset.width + 1):
            if row.codes[ordinal - 1] != "e":
                cells.append(Cell(dataset.sheet, row.source_row, column_id(ordinal), None,
                                  row.texts[ordinal - 1], row.codes[ordinal - 1], "refused", "R5",
                                  "undeclared_cell"))
    return cells, len(data_rows)


def run(datasets: Sequence[Dataset], schema: HeaderSchema, *,
        accepted: Sequence[Tuple[str, Sequence[Dataset]]] = ()) -> Result:
    """Try one file's staged sheets against a schema.

    `accepted` holds (source id, staged sheets) for each file the company already accepted as
    this kind; they are only read when the file's own values are refused (schema defect check).
    """
    result = Result("", schema.digest(), fingerprints={d.sheet: d.fingerprint for d in datasets})
    located = _locate(datasets, schema)
    names = schema.names
    if located is None or located[0] * 2 < len(names):
        result.outcome = "wrong_file"
        result.headers_found = located[0] if located else 0
        result.evidence = {"declared": list(names), "sheets": [d.sheet for d in datasets], "closest": None}
        if located:
            _, dataset, row = located
            result.evidence["closest"] = {"sheet": dataset.sheet, "row": row.source_row,
                                          "texts": [t for t, c in zip(row.texts, row.codes) if c != "e"]}
        return result

    count, dataset, row = located
    result.sheet, result.header_row, result.headers_found = dataset.sheet, row.source_row, count
    differences, summary = _structure(schema, dataset, row, [d.sheet for d in datasets])
    if differences:
        result.outcome, result.differences, result.evidence = "structural_change", differences, summary
        return result

    result.cells, result.rows_checked = _values(schema, dataset)
    if not result.refusals:
        result.outcome = "fits"
        return result
    refused_too = []
    for source_id, sheets in accepted:
        earlier = run(sheets, schema)
        if not earlier.fits:
            refused_too.append({"source_id": source_id, "outcome": earlier.outcome,
                                "rows_refused": earlier.rows_refused,
                                "first_refusals": earlier.to_dict()["refusals"][:5]})
    if refused_too:
        result.outcome, result.evidence = "schema_defect", {"accepted_files_refused": refused_too}
    else:
        result.outcome = "value_problem"
        result.evidence = {"accepted_files_checked": [source_id for source_id, _ in accepted]}
    return result


def headline(result: Result) -> str:
    """One line for a ticket title."""
    if result.outcome == "fits":
        return f"fits: {result.rows_checked} rows, 0 refusals"
    if result.outcome == "wrong_file":
        return f"wrong file: {result.headers_found} of {len(result.evidence['declared'])} headers found"
    if result.outcome == "structural_change":
        return f"structural change: {len(result.differences)} difference(s) in sheet, header row or headers"
    if result.outcome == "schema_defect":
        return (f"schema defect: {len(result.evidence['accepted_files_refused'])} accepted file(s) "
                f"refused by the same schema")
    return f"value problem: {len(result.refusals)} cell(s) refused in {result.rows_refused} row(s)"


def report(result: Result, schema: HeaderSchema) -> str:
    """The finding's text: what was checked, then every difference or refused cell."""
    lines = [f"Outcome: {headline(result)}", "", "Rules checked:", schema.rule_text(), ""]
    if result.outcome == "wrong_file":
        closest = result.evidence["closest"]
        lines.append(f"Declared headers: {', '.join(repr(n) for n in result.evidence['declared'])}")
        lines.append("Closest row: " + (f"sheet {closest['sheet']!r}, row {closest['row']}: "
                                        f"{closest['texts']}" if closest else "none (no sheet has content)"))
    elif result.outcome == "structural_change":
        for d in result.differences:
            if d["kind"] == "sheet":
                lines.append(f"sheet: expected {d['expected']!r}, found {d['found']!r} (sheets: {d['sheets']})")
            elif d["kind"] == "header_row":
                lines.append(f"header row: expected row {d['expected']}, found row {d['found']}")
            else:
                found = "nothing" if d["found"] is None else f"{d['found']!r} (type code {d['code']})"
                lines.append(f"{d['column']}: expected {d['expected']!r}, found {found}")
        lines.append(f"missing: {result.evidence['missing']}; added: {result.evidence['added']}; "
                     f"moved: {result.evidence['moved']}")
    elif result.refusals:
        for c in result.refusals:
            where = f"row {c.row}" + (f", {c.column} {c.header!r}" if c.column else "")
            lines.append(f"{where}: {c.reason} (rule {c.rule}); text {c.text!r}, type code {c.code}")
        if result.outcome == "schema_defect":
            for f in result.evidence["accepted_files_refused"]:
                lines.append(f"accepted file {f['source_id']} is refused too: {f['outcome']}, "
                             f"{f['rows_refused']} row(s)")
    else:
        lines.append(f"{result.rows_checked} rows checked, {len(result.cells)} cells accepted.")
    return "\n".join(lines)
