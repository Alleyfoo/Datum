"""A file kind's schema: the header declaration of one kind of file for one company.

The owner's decision: a schema is the set of a file's column headers (names, order, types) for
one file kind, per company. What a header means is the Map stage, not the schema. The declaration
also says where its headers are: the sheet and the header row.

The cleaning stage runs before the trial (babel/intake/cleaning.py). It first takes each formula
cell as its calculated value, the value the file saved for it (F1, owner answer P20), then trims
leading and trailing whitespace from every text cell and header (T1, the owner's default for all
sources), and applies the transformations a field declares. The one declaration built is case,
upper or lower; a field with none gets only the defaults. Headers are then compared exactly:
whitespace at either end is not significant (owner answer P21), anything else is. No similarity,
synonym or position is used to make a file fit. The rule list below is the full statement of what
happens to the values before the trial and what the trial checks; it is what an approver confirms,
so it is written out in full and never summarised.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List, NamedTuple, Optional, Tuple

TYPES = ("text", "int", "decimal", "bool", "date", "datetime")
CASES = ("upper", "lower")
#: the calculation, for every source, before the cleaning rules (owner answer P20)
CALCULATION_RULE = ("F1", "calculation, before cleaning: a formula cell counts as its calculated value, the value "
                          "the file saved for it (its cached value), with that value's own type; the value is "
                          "then cleaned and checked like any other, and the formula is kept beside the row. "
                          "Nothing calculates a formula here: a formula the file saved no value for has no "
                          "value (R6)")
#: the default cleaning rule, for every source
TRIM_RULE = ("T1", "cleaning, before the checks: leading and trailing whitespace is trimmed from every "
                   "text cell and every header, on every sheet; a text of only whitespace becomes an "
                   "empty cell")
#: what every source gets before the trial, in this order; a field's declared rules follow
DEFAULT_RULES = (CALCULATION_RULE, TRIM_RULE)
TYPE_RULES = {
    "text": "a string with at least one non-space character, kept as cleaning leaves it",
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
    #: a declared cleaning transformation of a text field: "upper" or "lower" case; None for none
    case: Optional[str] = None


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
        if any(not isinstance(n, str) or n.strip() == "" for n in names):
            raise HeaderError("bad_schema", "every column has a header name")
        if any(n != n.strip() for n in names):
            raise HeaderError("bad_schema", "a header name has no whitespace at either end: cleaning trims "
                                            "the file's headers, so such a name could never match")
        if len(set(names)) != len(names):
            raise HeaderError("bad_schema", "a header name is declared twice")
        for column in self.columns:
            if column.type not in TYPES:
                raise HeaderError("bad_schema", f"{column.name!r}: unknown type {column.type!r}")
            if column.case is not None and column.case not in CASES:
                raise HeaderError("bad_schema", f"{column.name!r}: case is one of {CASES}, not {column.case!r}")
            if column.case is not None and column.type != "text":
                raise HeaderError("bad_schema", f"{column.name!r}: case is declared on text fields only")

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def transforms(self) -> List[Tuple[str, Column]]:
        """The declared cleaning transformations, as (rule id, column), in column order: T2, T3, ..."""
        return [(f"T{n}", column) for n, column in enumerate((c for c in self.columns if c.case), start=2)]

    def cleaning_rules(self) -> List[Tuple[str, str]]:
        """What the cleaning stage does before the trial, as (rule id, statement): the defaults (the
        calculation F1, then the trim T1), then each field's declared transformation."""
        rules = list(DEFAULT_RULES)
        for rule_id, column in self.transforms():
            rules.append((rule_id, f'cleaning, after T1: the text cells under the header "{column.name}", below '
                                   f'row {self.header_row} of the sheet "{self.sheet}", are turned to '
                                   f"{column.case} case"))
        return rules

    def rules(self) -> List[Tuple[str, str]]:
        """Every rule the trial applies, as (rule id, statement)."""
        listed = ", ".join(f'"{n}"' for n in self.names)
        rules = [
            ("R1", f'the headers are on the sheet named "{self.sheet}"'),
            ("R2", f"the headers are on row {self.header_row}"),
            ("R3", f"the header row holds exactly these {len(self.columns)} headers, in this order, "
                   f"compared exactly after the calculation and cleaning (F1, T1): {listed}"),
        ]
        for ordinal, column in enumerate(self.columns, start=1):
            need = "required" if column.required else "may be empty"
            rules.append((f"C{ordinal}", f'c{ordinal:03d} "{column.name}": {column.type}, {need}; '
                                         f"{TYPE_RULES[column.type]}"))
        rules += [
            ("R4", f"every row below row {self.header_row} is a data row; a blank row is refused"),
            ("R5", "no cell outside the declared columns holds a value"),
            ("R6", "no cell under a declared header is an Excel error, or a formula the file saved no "
                   "value for (F1 had nothing to take): its value is missing, so it is refused even where "
                   "the column may be empty"),
            ("R7", "the file fits only with zero refusals"),
        ]
        return rules

    def rule_text(self) -> str:
        """The full list on the ticket: the cleaning rules, then the trial's."""
        return "\n".join(f"{rule_id}  {statement}" for rule_id, statement in self.cleaning_rules() + self.rules())

    def to_dict(self) -> dict:
        """The declaration; a field's case appears only when it is declared."""
        columns = []
        for c in self.columns:
            column = {"name": c.name, "type": c.type, "required": c.required}
            if c.case is not None:
                column["case"] = c.case
            columns.append(column)
        return {"sheet": self.sheet, "header_row": self.header_row, "columns": columns}

    @classmethod
    def from_dict(cls, data: dict) -> "HeaderSchema":
        try:
            columns = tuple(Column(c["name"], c["type"], bool(c.get("required", True)), c.get("case"))
                            for c in data["columns"])
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
