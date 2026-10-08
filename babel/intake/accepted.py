"""Accepted files: what an approver admitted, per company and file kind, under which schema version.

A row is written only by an admission and is never changed or removed (the database refuses
both). The create-schema gate reads these rows: every file a company already accepted must still
pass a new schema version.
"""

from __future__ import annotations

import sqlite3
from typing import List

from babel.record.store import RecordError, Store

TABLE = """
CREATE TABLE IF NOT EXISTS accepted_files (
    company_id TEXT NOT NULL,
    file_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    ticket INTEGER NOT NULL REFERENCES items(number),
    admitted_by TEXT NOT NULL REFERENCES users(name),
    admitted_at TEXT NOT NULL,
    PRIMARY KEY (company_id, file_kind, source_id));
CREATE TRIGGER IF NOT EXISTS accepted_files_no_update BEFORE UPDATE ON accepted_files
BEGIN SELECT RAISE(ABORT, 'an accepted file stays accepted'); END;
CREATE TRIGGER IF NOT EXISTS accepted_files_no_delete BEFORE DELETE ON accepted_files
BEGIN SELECT RAISE(ABORT, 'an accepted file stays accepted'); END;
"""


def ready(store: Store) -> None:
    """Create the table; call it before opening the transaction that records an acceptance."""
    store.ensure(TABLE)


def record(store: Store, db, *, company_id: str, file_kind: str, source_id: str, schema_version: int,
           ticket: int, admitted_by: str) -> dict:
    """Write one acceptance inside the admission's transaction (after ready())."""
    row = {"company_id": company_id, "file_kind": file_kind, "source_id": source_id,
           "schema_version": schema_version, "ticket": ticket, "admitted_by": admitted_by,
           "admitted_at": store.now()}
    try:
        db.execute("INSERT INTO accepted_files VALUES (:company_id, :file_kind, :source_id,"
                   " :schema_version, :ticket, :admitted_by, :admitted_at)", row)
    except sqlite3.IntegrityError:
        raise RecordError("already_accepted",
                          f"{source_id} is already accepted as {file_kind} for {company_id}") from None
    return row


def files(store: Store, company_id: str, file_kind: str) -> List[dict]:
    """The files a company accepted as one file kind, in the order they were admitted."""
    ready(store)
    with store.reading() as db:
        rows = db.execute("SELECT * FROM accepted_files WHERE company_id=? AND file_kind=?"
                          " ORDER BY admitted_at, ticket", (company_id, file_kind)).fetchall()
    return [dict(r) for r in rows]
