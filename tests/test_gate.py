import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from babel.intake import accepted, dispositions, hook, schemas, staging
from babel.record import queue
from babel.record.store import RecordError
from babel.schema.headers import Column, HeaderSchema
from domains.spare_parts.exports import stock_export

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


def _drafted(data_root, store, path=EXPORT, by="ville", schema=None):
    """A file of a new kind arrives; `by` drafts a stock_export version from it."""
    arrival = hook.trigger(data_root, "C-100", path, store=store)
    store.claim(arrival.ticket, by)
    if schema is None:
        [sheet] = staging.datasets(data_root, "C-100", arrival.source_id)
        schema, _ = schemas.suggest(sheet)
    schemas.draft(store, arrival.ticket, by, "stock_export", schema, "Drafted from the file on this ticket")
    return arrival


def _admitted_v1(data_root, store):
    arrival = _drafted(data_root, store)
    schemas.confirm(store, data_root, arrival.ticket, "anna", "These are the ERP stock export's headers")
    dispositions.admit(store, arrival.ticket, "anna", "First export, zero refusals")
    return arrival


def test_a_new_kind_of_file_becomes_a_schema_and_then_an_accepted_file(data_root, store, tmp_path):
    arrival = _drafted(data_root, store)
    assert [q["action"] for q in queue.pending(store)] == ["create_schema"]

    item = schemas.confirm(store, data_root, arrival.ticket, "anna", "These are the ERP stock export's headers")
    assert item["status"] == "needs_input"
    assert item["title"] == "stock_export_2026-08-21.xlsx: fits schema stock_export v1: ready to import"
    [version] = schemas.versions(store, "C-100", "stock_export")
    assert (version["status"], version["decided_by"], version["reason"]) == (
        "active", "anna", "These are the ERP stock export's headers")
    [confirmed] = store.documents_about(arrival.ticket, "decision")
    gate = confirmed["data"]["gate"]
    assert (gate["rules_on_ticket"], gate["drafted_from"], gate["drafted_from_refusals"]) == (
        True, arrival.source_id, 0)
    [waiting] = queue.pending(store)
    assert (waiting["action"], waiting["proposed_by"]) == ("import", "anna")

    dispositions.admit(store, arrival.ticket, "anna", "First export, zero refusals")
    assert [r["source_id"] for r in accepted.files(store, "C-100", "stock_export")] == [arrival.source_id]
    assert store.get(arrival.ticket)["data"]["resolution"] == "imported"

    later = stock_export(tmp_path / "stock_export_2026-08-28.xlsx", week_ending=date(2026, 8, 28))
    nxt = hook.trigger(data_root, "C-100", later, store=store)
    assert (nxt.outcome, nxt.schema_version) == ("fits", 1)
    assert [q["number"] for q in queue.pending(store)] == [nxt.ticket]


def test_the_gate_refuses_a_draft_that_its_own_file_does_not_pass(data_root, store):
    wrong = HeaderSchema("Stock", 1, STOCK.columns[:3] + (Column("On hand", "bool"),) + STOCK.columns[4:])
    arrival = _drafted(data_root, store, schema=wrong)
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "anna", "confirm") == "draft_refuses_its_file"
    assert schemas.get(store, "C-100", "stock_export", 1)["status"] == "draft"
    assert store.get(arrival.ticket)["status"] == "needs_input"
    refused = store.journal(arrival.ticket)[-1]
    assert (refused["action"], refused["details"]["code"]) == ("approval_refused", "draft_refuses_its_file")


def test_the_gate_refuses_a_draft_whose_rules_are_not_on_the_ticket(data_root, store):
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store)
    schemas.ready(store)
    db = sqlite3.connect(store.path)
    try:  # a draft made outside draft(), so no rule list was written on the ticket
        db.execute("INSERT INTO schema_versions (company_id, file_kind, version, declaration, digest, status,"
                   " ticket, drafted_from, drafted_by, drafted_at) VALUES"
                   " ('C-100', 'stock_export', 1, ?, ?, 'draft', ?, ?, 'ville', '2026-10-08T09:00:00+00:00')",
                   (json.dumps(STOCK.to_dict()), STOCK.digest(), arrival.ticket, arrival.source_id))
        db.commit()
    finally:
        db.close()
    store.claim(arrival.ticket, "ville")
    queue.propose(store, arrival.ticket, "ville", "create_schema", "drafted elsewhere",
                  payload={"company_id": "C-100", "file_kind": "stock_export", "version": 1})
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "anna", "confirm") == "rules_not_on_ticket"
    assert schemas.active(store, "C-100") == []


def test_a_draft_for_a_renamed_header_can_be_refused(data_root, store):
    _admitted_v1(data_root, store)
    variant = _drafted(data_root, store, path=VARIANT)
    assert (variant.outcome, variant.schema_version) == ("structural_change", 1)
    assert [v["status"] for v in schemas.versions(store, "C-100", "stock_export")] == ["active", "draft"]

    item = schemas.refuse(store, variant.ticket, "anna", "Not this week: the ERP change is not announced yet")
    assert item["status"] == "open"
    assert [v["status"] for v in schemas.versions(store, "C-100", "stock_export")] == ["active", "rejected"]


def test_only_a_named_person_holding_the_approver_role_confirms(data_root, store):
    arrival = _drafted(data_root, store)
    store.add_user("schema-assistant", ["worker"], kind="agent")
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "ville", "fine") == "role_missing"
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "schema-assistant", "fine") == "agent_approver"
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "hook", "fine") == "agent_approver"
    assert _code(schemas.confirm, store, data_root, arrival.ticket, "anna", " ") == "invalid_argument"
    assert schemas.active(store, "C-100") == []
    assert schemas.get(store, "C-100", "stock_export", 1)["status"] == "draft"


def test_the_drafter_may_confirm_their_own_draft_with_a_reason(data_root, store):
    arrival = _drafted(data_root, store, by="pia")
    schemas.confirm(store, data_root, arrival.ticket, "pia", "I drafted it from the ERP export and checked it")
    version = schemas.get(store, "C-100", "stock_export", 1)
    assert (version["status"], version["drafted_by"], version["decided_by"]) == ("active", "pia", "pia")


def test_nothing_activates_by_timeout_or_by_the_hook(data_root, store, clock):
    arrival = _drafted(data_root, store)
    clock.advance(days=30)
    again = hook.trigger(data_root, "C-100", VARIANT, store=store)
    assert again.outcome == "no_schema"
    assert schemas.get(store, "C-100", "stock_export", 1)["status"] == "draft"
    assert [q["number"] for q in queue.pending(store)] == [arrival.ticket]
    assert schemas.active(store, "C-100") == []


def test_a_new_version_supersedes_the_old_and_a_stale_fit_is_not_admitted(data_root, store, tmp_path):
    _admitted_v1(data_root, store)
    stale = hook.trigger(data_root, "C-100", stock_export(tmp_path / "w35.xlsx", week_ending=date(2026, 8, 28)),
                         store=store)
    change = hook.trigger(data_root, "C-100", stock_export(tmp_path / "w36.xlsx", week_ending=date(2026, 9, 4)),
                          store=store)
    assert (stale.outcome, change.outcome) == ("fits", "fits")
    dispositions.reject(store, change.ticket, "anna", "Change the schema first: descriptions may be empty")
    relaxed = HeaderSchema("Stock", 1, STOCK.columns[:1] + (Column("Description", "text", required=False),)
                           + STOCK.columns[2:])
    store.claim(change.ticket, "ville")
    schemas.draft(store, change.ticket, "ville", "stock_export", relaxed, "Descriptions may be empty")
    schemas.confirm(store, data_root, change.ticket, "anna", "The ERP leaves new items without a description")
    assert [v["status"] for v in schemas.versions(store, "C-100", "stock_export")] == ["superseded", "active"]
    [active] = schemas.active(store, "C-100")
    assert (active.version, active.schema) == (2, relaxed)

    assert _code(dispositions.admit, store, stale.ticket, "anna", "fits") == "schema_superseded"
    assert store.get(stale.ticket)["status"] == "needs_input"
    assert dispositions.admit(store, change.ticket, "anna", "fits v2")["data"]["resolution"] == "imported"


def test_a_rejected_draft_keeps_its_number(data_root, store):
    arrival = _drafted(data_root, store)
    schemas.refuse(store, arrival.ticket, "anna", "Item should be the first column of a stock export")
    store.claim(arrival.ticket, "ville")
    redrafted = schemas.draft(store, arrival.ticket, "ville", "stock_export", STOCK, "Second attempt")
    assert redrafted.version == 2
    schemas.confirm(store, data_root, arrival.ticket, "anna", "Confirmed")
    assert [v["status"] for v in schemas.versions(store, "C-100", "stock_export")] == ["rejected", "active"]
