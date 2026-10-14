import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from datum.intake import hook, inbox, schemas, staging
from datum.record import queue
from datum.record.store import RecordError
from datum.schema.headers import Column, HeaderSchema

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "stock_export_2026-08-21.xlsx"
VARIANT = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"
STOCK = HeaderSchema("Stock", 1, (
    Column("Item", "text"), Column("Description", "text"), Column("Warehouse", "text"),
    Column("On hand", "int"), Column("Stock date", "date"),
))


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _claimed_ticket(data_root, store, path=EXPORT, by="ville"):
    arrival = hook.trigger(data_root, "C-100", path, store=store)
    store.claim(arrival.ticket, by)
    return arrival


def test_with_no_stored_version_the_hook_asks_for_a_schema(data_root, store):
    assert schemas.active(store, "C-100") == []
    assert hook.trigger(data_root, "C-100", EXPORT, store=store).outcome == "no_schema"


def test_a_draft_takes_the_next_number_lists_its_rules_and_waits_for_an_approver(data_root, store):
    arrival = _claimed_ticket(data_root, store)
    drafted = schemas.draft(store, arrival.ticket, "ville", "stock_export", STOCK, "Drafted from this export")
    assert (drafted.company_id, drafted.file_kind, drafted.version, drafted.schema) == ("C-100", "stock_export", 1, STOCK)
    [row] = schemas.versions(store, "C-100", "stock_export")
    assert (row["status"], row["drafted_from"], row["drafted_by"], row["ticket"]) == (
        "draft", arrival.source_id, "ville", arrival.ticket)
    assert row["schema"] == STOCK and row["digest"] == STOCK.digest()
    [listed] = [e for e in store.journal(arrival.ticket) if e["action"] == "rules_listed"]
    assert listed["details"]["rules"] == STOCK.rule_text()  # the full list, not a summary
    assert (listed["actor"], listed["role"]) == ("ville", "worker")
    [waiting] = queue.pending(store)
    assert (waiting["number"], waiting["action"]) == (arrival.ticket, "create_schema")
    assert waiting["payload"] == {"company_id": "C-100", "file_kind": "stock_export", "version": 1}
    assert schemas.active(store, "C-100") == []  # a draft is not active


def test_versions_are_numbered_per_company_and_kind(data_root, store):
    first = _claimed_ticket(data_root, store)
    schemas.draft(store, first.ticket, "ville", "stock_export", STOCK, "first draft")
    second = _claimed_ticket(data_root, store, path=VARIANT)
    assert schemas.draft(store, second.ticket, "ville", "stock_export", STOCK, "second draft").version == 2
    (data_root / "customers" / "C-200").mkdir()
    other = hook.trigger(data_root, "C-200", EXPORT, store=store)
    store.claim(other.ticket, "pia")
    assert schemas.draft(store, other.ticket, "pia", "stock_export", STOCK, "another company").version == 1
    assert [v["version"] for v in schemas.versions(store, "C-100", "stock_export")] == [1, 2]


def test_a_version_is_never_rewritten_never_deleted_and_moves_only_forward(data_root, store):
    arrival = _claimed_ticket(data_root, store)
    schemas.draft(store, arrival.ticket, "ville", "stock_export", STOCK, "draft")
    other = HeaderSchema("Stock", 1, STOCK.columns[:4])
    db = sqlite3.connect(store.path)
    try:
        refused = [
            ("UPDATE schema_versions SET declaration=?", (json.dumps(other.to_dict()),)),
            ("UPDATE schema_versions SET version=7", ()),
            ("DELETE FROM schema_versions", ()),
            ("UPDATE schema_versions SET status='superseded'", ()),  # a draft cannot skip to superseded
        ]
        for statement, args in refused:
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(statement, args)
        db.execute("UPDATE schema_versions SET status='active'")  # forward is allowed
        db.commit()
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("UPDATE schema_versions SET status='draft'")
        with pytest.raises(sqlite3.DatabaseError):  # two active versions of one kind
            db.execute("INSERT INTO schema_versions SELECT company_id, file_kind, 2, declaration, digest,"
                       " 'active', ticket, drafted_from, drafted_by, drafted_at, NULL, NULL, NULL"
                       " FROM schema_versions")
    finally:
        db.close()
    assert schemas.get(store, "C-100", "stock_export", 1)["schema"] == STOCK
    [active] = schemas.active(store, "C-100")
    assert (active.file_kind, active.version, active.schema) == ("stock_export", 1, STOCK)


def test_a_closed_ticket_a_schema_version_was_drafted_on_is_never_deleted(data_root, store, clock):
    # the owner's review of round six (build-plan section 30): a ticket a kept record refers to is kept
    arrival = _claimed_ticket(data_root, store)
    schemas.draft(store, arrival.ticket, "ville", "stock_export", STOCK, "Drafted from this export")
    schemas.refuse(store, arrival.ticket, "anna", "The supplier is changing the export's columns")
    store.claim(arrival.ticket, "ville")
    store.close(arrival.ticket, "ville", "The supplier withdrew this export")
    assert store.sweep(clock() + timedelta(days=3650)) == []
    assert _code(store.delete, arrival.ticket, "anna") == "still_referred_to"  # anna answers for the queue's ticket
    assert store.get(arrival.ticket)["status"] == "closed"
    [version] = schemas.versions(store, "C-100", "stock_export")
    assert (version["ticket"], version["status"], version["schema"]) == (arrival.ticket, "rejected", STOCK)


def test_drafting_needs_the_claim_a_role_and_a_plain_file_kind(data_root, store):
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store)
    assert _code(schemas.draft, store, arrival.ticket, "ville", "stock_export", STOCK, "draft") == "claim_required"
    store.claim(arrival.ticket, "hook")  # a service account holds no role
    assert _code(schemas.draft, store, arrival.ticket, "hook", "stock_export", STOCK, "draft") == "role_missing"
    store.release(arrival.ticket, "hook")
    store.claim(arrival.ticket, "ville")
    assert _code(schemas.draft, store, arrival.ticket, "ville", "Stock Export", STOCK, "draft") == "invalid_argument"
    assert schemas.versions(store, "C-100", "stock_export") == []


def test_anyone_who_holds_the_ticket_in_a_role_drafts_and_is_recorded(data_root, store):
    # folder access is enough to draft (build-plan section 7); anna holds only the approver role
    arrival = _claimed_ticket(data_root, store, by="anna")
    schemas.draft(store, arrival.ticket, "anna", "stock_export", STOCK, "Drafted from this export")
    [row] = schemas.versions(store, "C-100", "stock_export")
    assert (row["status"], row["drafted_by"]) == ("draft", "anna")
    [listed] = [e for e in store.journal(arrival.ticket) if e["action"] == "rules_listed"]
    assert (listed["actor"], listed["role"]) == ("anna", "approver")


def test_a_draft_can_be_read_off_the_staged_export(data_root):
    source = inbox.preserve(data_root, "C-100", EXPORT)
    [sheet] = staging.stage_all(data_root, "C-100", source.source_id)
    suggested, evidence = schemas.suggest(sheet)
    assert suggested == STOCK
    assert evidence[3] == {"column": "c004", "header": "On hand", "codes": {"n": 19}, "proposed": "int"}


def test_a_column_of_mixed_kinds_gets_no_proposal(data_root, tmp_path, workbook):
    path = workbook(tmp_path / "mixed.xlsx", {"Stock": [["Item", "Qty"], ["A", 1], ["B", "two"], ["C", None]]})
    source = inbox.preserve(data_root, "C-100", path)
    [sheet] = staging.stage_all(data_root, "C-100", source.source_id)
    suggested, evidence = schemas.suggest(sheet)
    assert suggested is None
    assert evidence[1] == {"column": "c002", "header": "Qty", "codes": {"e": 1, "n": 1, "s": 1}, "proposed": None}
