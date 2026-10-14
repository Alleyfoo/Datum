"""Accepted files: what an approver admitted, per company and file kind, under which schema version.

A row is written only by an admission and is never changed or removed (the database refuses
both). A file stays accepted under the version it was admitted with: a newer version of the
schema is not checked against it (owner answer P23), so an amendment never touches an accepted
file. The trial reads the files accepted under the version it tries, for its schema-defect check.
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from datum.record.store import RecordError, Store

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


def files(store: Store, company_id: str, file_kind: str, schema_version: Optional[int] = None) -> List[dict]:
    """The files a company accepted as one file kind, in the order they were admitted; with
    `schema_version`, only the files accepted under that version."""
    ready(store)
    query = "SELECT * FROM accepted_files WHERE company_id=? AND file_kind=?"
    args: tuple = (company_id, file_kind)
    if schema_version is not None:
        query, args = query + " AND schema_version=?", args + (schema_version,)
    with store.reading() as db:
        rows = db.execute(query + " ORDER BY admitted_at, ticket", args).fetchall()
    return [dict(r) for r in rows]
