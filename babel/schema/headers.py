"""A file kind's schema: the header declaration of one kind of file for one company.

The owner's decision: a schema is the set of a file's column headers (names, order, types) for
one file kind, per company. What a header means is the Map stage, not the schema. The declaration
also says where its headers are: the sheet and the header row.

Headers are compared exactly, whitespace included. No similarity, synonym or position is used to
make a file fit. The rule list below is the full statement of what the trial checks; it is what an
approver confirms, so it is written out in full and never summarised.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List, NamedTuple, Tuple

TYPES = ("text", "int", "decimal", "bool", "date", "datetime")
TYPE_RULES = {
    "text": "a string with at least one non-space character, kept exactly as written",
    "int": "a number cell holding a whole number",
    "decimal": "a number cell holding a finite number",
    "bool": "a TRUE or FALSE cell",
    "date": "a date cell with no time of day",
    "datetime": "a date cell, with or without a time of day",
}


class HeaderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    required: bool = True


@dataclass(frozen=True)
class HeaderSchema:
    sheet: str
    header_row: int
    columns: Tuple[Column, ...]

    def __post_init__(self):
        if not isinstance(self.sheet, str) or not self.sheet:
            raise HeaderError("bad_schema", "a schema names its sheet")
        if not isinstance(self.header_row, int) or isinstance(self.header_row, bool) or self.header_row < 1:
            raise HeaderError("bad_schema", "the header row is a row number from 1")
        if not self.columns:
            raise HeaderError("bad_schema", "a schema declares at least one column")
        names = [c.name for c in self.columns]
        if any(not isinstance(n, str) or n == "" for n in names):
            raise HeaderError("bad_schema", "every column has a header name")
        if len(set(names)) != len(names):
            raise HeaderError("bad_schema", "a header name is declared twice")
        for column in self.columns:
            if column.type not in TYPES:
                raise HeaderError("bad_schema", f"{column.name!r}: unknown type {column.type!r}")

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def rules(self) -> List[Tuple[str, str]]:
        """Every rule the trial applies, as (rule id, statement)."""
        listed = ", ".join(f'"{n}"' for n in self.names)
        rules = [
            ("R1", f'the headers are on the sheet named "{self.sheet}"'),
            ("R2", f"the headers are on row {self.header_row}"),
            ("R3", f"the header row holds exactly these {len(self.columns)} headers, in this order, "
                   f"compared exactly (whitespace included): {listed}"),
        ]
        for ordinal, column in enumerate(self.columns, start=1):
            need = "required" if column.required else "may be empty"
            rules.append((f"C{ordinal}", f'c{ordinal:03d} "{column.name}": {column.type}, {need}; '
                                         f"{TYPE_RULES[column.type]}"))
        rules += [
            ("R4", f"every row below row {self.header_row} is a data row; a blank row is refused"),
            ("R5", "no cell outside the declared columns holds a value"),
            ("R6", "no cell under a declared header is a formula, even with a cached value, "
                   "or an Excel error"),
            ("R7", "the file fits only with zero refusals"),
        ]
        return rules

    def rule_text(self) -> str:
        return "\n".join(f"{rule_id}  {statement}" for rule_id, statement in self.rules())

    def to_dict(self) -> dict:
        return {"sheet": self.sheet, "header_row": self.header_row,
                "columns": [{"name": c.name, "type": c.type, "required": c.required} for c in self.columns]}

    @classmethod
    def from_dict(cls, data: dict) -> "HeaderSchema":
        try:
            columns = tuple(Column(c["name"], c["type"], bool(c.get("required", True))) for c in data["columns"])
            return cls(data["sheet"], data["header_row"], columns)
        except (KeyError, TypeError) as error:
            raise HeaderError("bad_schema", f"incomplete declaration: {error}") from None

    def digest(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Versioned(NamedTuple):
    """One version of one company's schema for one file kind."""

    company_id: str
    file_kind: str
    version: int
    schema: HeaderSchema
