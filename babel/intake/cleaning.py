"""Cleaning: a stage of its own, between staging (Reveal) and the trial, driven by the schema.

The owner's decisions (intake.md, "Cleaning: a stage of its own, driven by the schema"; build-plan
section 7, P21 and D-clean; build-plan section 20, P20):

- F1, the calculation, for every source and before every other rule: a formula cell's value is
  calculated first, and the value is then processed like any other value (P20). Nothing here
  calculates a formula and no formula engine is used: the calculated value is the one the file
  saved for the cell (its cached value), which staging keeps beside the row with the value's own
  type code. The cell takes that code, so the rules below and the trial treat it as that value,
  and the formula stays beside the row. The change is recorded with the formula as the original
  text and the saved value as the transformed one. A formula the file saved no value for keeps
  code f and no value: nothing is guessed, and the trial refuses it as formula_not_calculated
  (R6). openpyxl reads an empty saved text the same as no saved value, so a formula whose result
  is an empty text is refused the same way.
- T1, the default for every source: leading and trailing whitespace is trimmed from every text
  cell and every header, on every sheet. A text of only whitespace becomes an empty cell and is
  handled as empty from then on: a required value is missing, an optional one is empty, and a row
  of nothing else is a blank row. A header is a text cell of its row, so a header with a stray
  space matches its declared name (P21).
- A field may declare a transformation in the schema; a field with none gets only the defaults, F1
  and T1. The one declaration built is case (upper or lower), numbered T2, T3, ... in column order.
  It is applied after T1 to the text cells under the field's header, below the declared header row
  of the declared sheet.
- Every change is recorded against its cell: sheet, row and column, the original text, the
  transformed text and the rule that made the change. A cell changed by two rules has two
  records, in the order the rules ran.

Only these rules change a value; nothing is guessed. Text cells are the cells coded `s` once F1 has
run, so a formula that saved a text is trimmed like any text; numbers, dates, booleans, errors and
formulas with no saved value are left alone, and no row or column is added or removed. Cleaning
reads staged datasets and returns cleaned copies: staging is never written. A cleaned dataset keeps
the staged ids, provenance and formulas, and its fingerprint is taken over the cleaned rows, so a
dataset that cleaning left alone keeps its staged fingerprint.

The records are stored beside staging, in customers/<company>/cleaning/<source id>/<key>/ as
changes.jsonl and manifest.json. The key is the first 16 hex digits of the schema's digest, since
the schema decides what cleaning does ("default" with no schema). They are written once: cleaning
the same file for the same schema again gives the same records, and other records under the same
key are refused.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from babel.schema.headers import CALCULATION_RULE, DEFAULT_RULES, TRIM_RULE, Column, HeaderSchema

from .inbox import customer_dir
from .staging import Dataset, Row, column_id, fingerprint

VERSION = 1
CHANGES = "changes.jsonl"
MANIFEST = "manifest.json"


class CleaningError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Change:
    sheet: str
    row: int
    column: str
    rule: str  # F1 (the calculation), T1 (the default trim) or a field's declared rule, T2, T3, ...
    transform: str  # calculated | trim | upper | lower
    original: str  # the text before the change; for F1, the formula
    transformed: str  # the text after it; for F1, the value the file saved for the formula
    code: str  # the cell's type code after the change: "e" once a text is empty


@dataclass(frozen=True)
class Cleaned:
    source_id: str
    schema_digest: Optional[str]
    rules: Tuple[Tuple[str, str], ...]
    datasets: Tuple[Dataset, ...]
    changes: Tuple[Change, ...]
    #: sheet -> its dataset id, staged fingerprint and cleaned fingerprint
    fingerprints: Dict[str, dict]

    @property
    def key(self) -> str:
        return self.schema_digest[:16] if self.schema_digest else "default"

    def by_rule(self) -> Dict[str, int]:
        return dict(sorted(Counter(c.rule for c in self.changes).items()))

    def digest(self) -> str:
        """Covers the rules, the fingerprints and every change."""
        whole = {"version": VERSION, "schema_digest": self.schema_digest, "rules": [list(r) for r in self.rules],
                 "fingerprints": self.fingerprints, "changes": [asdict(c) for c in self.changes]}
        canonical = json.dumps(whole, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def summary(self) -> dict:
        """What a finding keeps: the counts, where the records are, and their digest."""
        return {"changes": len(self.changes), "by_rule": self.by_rule(),
                "stored": f"cleaning/{self.source_id}/{self.key}", "digest": self.digest()}


def _turned(case: str, text: str) -> str:
    return text.upper() if case == "upper" else text.lower()


def _clean(dataset: Dataset, schema: Optional[HeaderSchema]) -> Tuple[Dataset, List[Change]]:
    changes: List[Change] = []
    rows: List[Row] = []
    declared: Dict[int, Tuple[str, Column]] = {}  # column index -> (rule id, field); set at the header row
    for row in dataset.rows:
        texts, codes = list(row.texts), list(row.codes)
        for i, code in enumerate(row.codes):
            where = (dataset.sheet, row.source_row, column_id(i + 1))
            if code == "f":
                formula, saved = row.formulas[where[2]]
                if saved == "e":
                    continue  # no saved value: nothing is calculated here, and the trial refuses it (R6)
                codes[i] = saved  # F1: the saved value, with its own type; staging already holds its text
                changes.append(Change(*where, CALCULATION_RULE[0], "calculated", formula, texts[i], saved))
            if codes[i] != "s":
                continue
            trimmed = texts[i].strip()
            if trimmed != texts[i]:
                codes[i] = "s" if trimmed else "e"
                changes.append(Change(*where, TRIM_RULE[0], "trim", texts[i], trimmed, codes[i]))
                texts[i] = trimmed
            if i in declared and codes[i] == "s":
                rule_id, field = declared[i]
                turned = _turned(field.case, texts[i])
                if turned != texts[i]:
                    changes.append(Change(*where, rule_id, field.case, texts[i], turned, "s"))
                    texts[i] = turned
        if schema is not None and dataset.sheet == schema.sheet and row.source_row == schema.header_row:
            for rule_id, field in schema.transforms():
                declared.update({i: (rule_id, field) for i, (text, code) in enumerate(zip(texts, codes))
                                 if code == "s" and text == field.name})
        rows.append(Row(row.source_row, "".join(codes), tuple(texts), dict(row.formulas)))
    cleaned = Dataset(dataset.dataset_id, dataset.source_id, dataset.sheet, dataset.sheet_index, dataset.width,
                      tuple(rows), fingerprint(dataset.sheet, dataset.width, rows))
    return cleaned, changes


def clean(datasets: Sequence[Dataset], schema: Optional[HeaderSchema] = None) -> Cleaned:
    """Clean one file's staged sheets for a schema; with no schema, only the defaults (F1, T1) run."""
    if not datasets:
        raise CleaningError("nothing_to_clean", "cleaning needs the staged sheets of one file")
    sources = {d.source_id for d in datasets}
    if len(sources) != 1:
        raise CleaningError("mixed_sources", f"the sheets come from more than one file: {sorted(sources)}")
    cleaned, changes, prints = [], [], {}
    for dataset in datasets:
        result, found = _clean(dataset, schema)
        cleaned.append(result)
        changes += found
        prints[dataset.sheet] = {"dataset_id": dataset.dataset_id, "staged": dataset.fingerprint,
                                 "cleaned": result.fingerprint}
    rules = schema.cleaning_rules() if schema is not None else list(DEFAULT_RULES)
    return Cleaned(sources.pop(), schema.digest() if schema is not None else None, tuple(rules),
                   tuple(cleaned), tuple(changes), prints)


def cleaning_dir(root, company_id: str, source_id: str, key: str) -> Path:
    return customer_dir(root, company_id) / "cleaning" / source_id / key


def _line(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def record(root, company_id: str, cleaned: Cleaned) -> Path:
    """Store the change records beside staging, once. Staging is not touched."""
    folder = cleaning_dir(root, company_id, cleaned.source_id, cleaned.key)
    if (folder / MANIFEST).exists():
        kept = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if kept.get("digest") != cleaned.digest():
            raise CleaningError("cleaning_conflict", f"{folder} already holds other cleaning records "
                                                     f"for {cleaned.source_id}; a person must look at it")
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / CHANGES, "wb") as handle:
        for change in cleaned.changes:
            handle.write(_line(asdict(change)))
    manifest = {
        "company_id": company_id, "source_id": cleaned.source_id, "schema_digest": cleaned.schema_digest,
        "rules": [list(r) for r in cleaned.rules], "fingerprints": cleaned.fingerprints,
        "changes": len(cleaned.changes), "by_rule": cleaned.by_rule(), "digest": cleaned.digest(),
        "cleaning_version": VERSION,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
                                   encoding="utf-8", newline="\n")
    return folder


def stored(root, company_id: str, source_id: str, schema: Optional[HeaderSchema] = None) -> Tuple[dict, List[dict]]:
    """The stored manifest and change records of one file cleaned for one schema."""
    folder = cleaning_dir(root, company_id, source_id, schema.digest()[:16] if schema is not None else "default")
    if not (folder / MANIFEST).exists():
        raise CleaningError("not_cleaned", f"{source_id} has no cleaning records for this schema")
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    changes = [json.loads(line) for line in (folder / CHANGES).read_text(encoding="utf-8").splitlines()]
    return manifest, changes


def report(cleaned: Cleaned) -> str:
    """The paragraph a finding carries: how many cells cleaning changed, by rule, and where every
    change is recorded."""
    if not cleaned.changes:
        return "Cleaning: no cell changed."
    counts = ", ".join(f"{rule}: {n}" for rule, n in cleaned.by_rule().items())
    return (f"Cleaning: {len(cleaned.changes)} change(s) ({counts}); each is recorded against its cell, "
            f"with the original and the transformed text, in {cleaned.summary()['stored']}/{CHANGES}.")
