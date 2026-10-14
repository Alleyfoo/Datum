"""Entities, fields and the cleaning rules every table must pass.

A table is never guessed into shape. Each row is either accepted as declared or
refused with a code and its row number: unknown columns, missing required values,
wrong types, duplicate keys and references to nothing. Units are recorded so people
can read them; they are not converted here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

TYPES = ("text", "int", "decimal", "bool", "date")


class SchemaError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = True
    unit: Optional[str] = None
    #: name of the entity whose single key this value must match
    ref: Optional[str] = None

    def __post_init__(self):
        if self.type not in TYPES:
            raise SchemaError("unknown_type", f"{self.name}: unknown type {self.type!r}")


@dataclass(frozen=True)
class Entity:
    name: str
    key: Tuple[str, ...]
    fields: Tuple[Field, ...]

    def __post_init__(self):
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise SchemaError("duplicate_field", f"{self.name}: a field is declared twice")
        for key in self.key:
            field = self.field(key)
            if field is None or not field.required:
                raise SchemaError("bad_key", f"{self.name}: key {key!r} must be a required field")

    def field(self, name: str) -> Optional[Field]:
        return next((f for f in self.fields if f.name == name), None)


@dataclass(frozen=True)
class Refusal:
    table: str
    row_no: int
    code: str
    message: str


def _matches(field: Field, value: Any) -> bool:
    if field.type == "text":
        return isinstance(value, str) and value.strip() != ""
    if field.type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if field.type == "decimal":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field.type == "bool":
        return isinstance(value, bool)
    # date: a plain date, not a datetime
    return isinstance(value, date) and not isinstance(value, datetime)


class Registry:
    def __init__(self):
        self._entities: Dict[str, Entity] = {}

    def declare(self, entity: Entity) -> None:
        if entity.name in self._entities:
            raise SchemaError("duplicate_entity", f"{entity.name} is already declared")
        self._entities[entity.name] = entity

    def entity(self, name: str) -> Entity:
        if name not in self._entities:
            raise SchemaError("unknown_entity", f"no entity named {name!r}")
        return self._entities[name]

    def names(self) -> Tuple[str, ...]:
        return tuple(self._entities)

    def clean_row(self, entity: Entity, row: Dict[str, Any]) -> Dict[str, Any]:
        known = {f.name for f in entity.fields}
        unknown = sorted(set(row) - known)
        if unknown:
            raise SchemaError("unknown_field", f"unknown field(s): {', '.join(unknown)}")
        out: Dict[str, Any] = {}
        for field in entity.fields:
            value = row.get(field.name)
            if value is None:
                if field.required:
                    raise SchemaError("missing_field", f"{field.name} is required")
                out[field.name] = None
                continue
            if not _matches(field, value):
                raise SchemaError("wrong_type", f"{field.name} must be {field.type}")
            if isinstance(value, float) and not math.isfinite(value):
                raise SchemaError("non_finite", f"{field.name} must be a finite number, not {value!r}")
            out[field.name] = value.strip() if field.type == "text" else value
        return out

    def clean(self, name: str, rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Refusal]]:
        """Return the accepted rows and a refusal for every row that does not fit."""
        entity = self.entity(name)
        accepted: List[Dict[str, Any]] = []
        refusals: List[Refusal] = []
        seen = set()
        for row_no, row in enumerate(rows, start=1):
            try:
                clean = self.clean_row(entity, row)
            except SchemaError as error:
                refusals.append(Refusal(name, row_no, error.code, str(error)))
                continue
            key = tuple(clean[k] for k in entity.key)
            if key in seen:
                refusals.append(Refusal(name, row_no, "duplicate_key", f"key {key} already present"))
                continue
            seen.add(key)
            accepted.append(clean)
        return accepted, refusals

    def check_refs(self, tables: Dict[str, List[Dict[str, Any]]]) -> List[Refusal]:
        """Every reference must match an existing key in the table it names."""
        refusals: List[Refusal] = []
        for name in self.names():
            entity = self.entity(name)
            for field in entity.fields:
                if field.ref is None:
                    continue
                target = self.entity(field.ref)
                if len(target.key) != 1:
                    raise SchemaError("composite_ref", f"{name}.{field.name} points at a composite key")
                known = {row[target.key[0]] for row in tables.get(field.ref, [])}
                for row_no, row in enumerate(tables.get(name, []), start=1):
                    value = row.get(field.name)
                    if value is not None and value not in known:
                        refusals.append(Refusal(name, row_no, "unknown_reference",
                                                f"{field.name} {value!r} is not in {field.ref}"))
        return refusals
