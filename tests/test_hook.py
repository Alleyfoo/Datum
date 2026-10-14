from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from datum.intake import accepted, dispositions, hook, inbox, staging
from datum.intake.inbox import IntakeError
from datum.record import queue
from datum.record.store import REVIEW_QUEUE
from datum.schema.headers import Column, HeaderSchema, Versioned
from domains.spare_parts.exports import stock_export

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "stock_export_2026-08-21.xlsx"
VARIANT = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"
STOCK = HeaderSchema("Stock", 1, (
    Column("Item", "text"), Column("Description", "text"), Column("Warehouse", "text"),
    Column("On hand", "int"), Column("Stock date", "date"),
))
V1 = Versioned("C-100", "stock_export", 1, STOCK)


def _with(*versions):
    return lambda company_id: [v for v in versions if v.company_id == company_id]


def test_a_file_of_a_new_kind_asks_for_a_schema(data_root, store):
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with())
    ticket = store.get(arrival.ticket)
    assert arrival.outcome == "no_schema"
    assert ticket["title"] == "stock_export_2026-08-21.xlsx: new kind of file for C-100: create a schema"
    assert ticket["data"]["choices"] == ["create_schema", "drop"]
    assert ticket["status"] == "open" and queue.pending(store) == []
    [finding] = store.documents_about(arrival.ticket, "finding")
    assert finding["data"]["sheets"][0]["texts"] == ["Item", "Description", "Warehouse", "On hand", "Stock date"]


def test_the_hook_opens_the_ticket_and_the_approval_queue_answers_for_it(data_root, store):
    # the owner's decision on R6-Q2 (build-plan section 30): the hook stays the ticket's creator, and its notices
    # go to the approval queue until real identities name the company's responsible data owner
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with())
    ticket = store.get(arrival.ticket)
    assert (ticket["created_by"], ticket["recipient"], hook.RECIPIENT) == ("hook", REVIEW_QUEUE, REVIEW_QUEUE)
    assert store.journal(arrival.ticket)[0]["details"]["recipient"] == REVIEW_QUEUE


def test_a_fitting_file_waits_for_an_approver_and_the_hook_admits_nothing(data_root, store):
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1))
    ticket = store.get(arrival.ticket)
    assert (arrival.outcome, arrival.file_kind, arrival.schema_version) == ("fits", "stock_export", 1)
    assert ticket["title"] == "stock_export_2026-08-21.xlsx: fits schema stock_export v1: ready to import"
    [waiting] = queue.pending(store)
    assert (waiting["number"], waiting["action"], waiting["proposed_by"], waiting["proposed_role"]) == (
        arrival.ticket, "import", "hook", "system")
    finding = store.get(arrival.finding)
    assert finding["data"]["verification"]["trial_reproduced"]
    assert finding["data"]["verification"]["fingerprints_reproduced"]
    assert accepted.files(store, "C-100", "stock_export") == []

    dispositions.admit(store, arrival.ticket, "anna", "19 rows, zero refusals; this week's stock")
    [row] = accepted.files(store, "C-100", "stock_export")
    assert (row["source_id"], row["schema_version"], row["admitted_by"]) == (arrival.source_id, 1, "anna")


def test_a_renamed_header_opens_a_ticket_with_the_verified_difference(data_root, store):
    arrival = hook.trigger(data_root, "C-100", VARIANT, store=store, schemas=_with(V1))
    ticket = store.get(arrival.ticket)
    assert arrival.outcome == "structural_change"
    assert ticket["title"].endswith("does not fit schema stock_export v1: structural change: "
                                    "1 difference(s) in sheet, header row or headers")
    assert ticket["data"]["choices"] == ["create_schema", "drop"]
    finding = store.get(arrival.finding)
    assert "c004: expected 'On hand', found 'Quantity on hand' (type code s)" in finding["body"]
    assert finding["data"]["verification"]["trial_reproduced"]
    assert queue.pending(store) == []


def test_unrelated_headers_are_a_wrong_file(data_root, store, tmp_path, workbook):
    path = workbook(tmp_path / "orders.xlsx", {"Orders": [["Order", "Customer", "Total"], ["O-1", "C-100", 5]]})
    arrival = hook.trigger(data_root, "C-100", path, store=store, schemas=_with(V1))
    assert arrival.outcome == "wrong_file"
    assert store.get(arrival.ticket)["title"] == ("orders.xlsx: wrong file: its headers do not match "
                                                  "schema stock_export v1 of C-100")


def test_refused_values_are_a_value_problem(data_root, store, tmp_path, workbook):
    rows = [list(STOCK.names), ["SP-1", "Part", "FI", 7.5, datetime(2026, 8, 21)]]
    arrival = hook.trigger(data_root, "C-100", workbook(tmp_path / "bad.xlsx", {"Stock": rows}),
                           store=store, schemas=_with(V1))
    assert arrival.outcome == "value_problem"
    finding = store.get(arrival.finding)
    assert finding["data"]["refusals"][0]["reason"] == "not_integer"
    assert "row 2, c004 'On hand': not_integer (rule C4)" in finding["body"]


def test_a_repeat_is_linked_to_its_first_arrival(data_root, store, tmp_path):
    first = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1))
    copy = tmp_path / "dragged in again.xlsx"
    copy.write_bytes(EXPORT.read_bytes())
    again = hook.trigger(data_root, "C-100", copy, store=store, schemas=_with(V1))
    assert (again.ticket, again.repeated, again.outcome) == (first.ticket, True, "fits")
    assert len(store.items("task")) == 1
    assert "arrived again as dragged in again.xlsx" in store.journal(first.ticket)[-1]["details"]["body"]
    assert [e["event"] for e in inbox.read_ledger(data_root, "C-100")] == ["preserved", "repeated"]


def test_a_file_that_cannot_be_read_is_unclassified_with_raw_evidence(data_root, store, tmp_path):
    fake = tmp_path / "broken.xlsx"
    fake.write_bytes(b"not a workbook")
    arrival = hook.trigger(data_root, "C-100", fake, store=store, schemas=_with(V1))
    assert arrival.outcome == "unclassified"
    ticket = store.get(arrival.ticket)
    assert ticket["title"] == "broken.xlsx: unclassified: the file could not be staged"
    assert ticket["data"]["choices"] == ["drop", "create_schema"]
    finding = store.get(arrival.finding)
    assert finding["data"]["evidence"]["code"] == "unreadable_workbook"
    assert "No cause is suggested" in finding["body"]


def test_only_excel_is_accepted_and_nothing_is_written_for_other_files(data_root, store, tmp_path):
    csv = tmp_path / "stock.csv"
    csv.write_text("Item,On hand\nSP-1,3\n", encoding="utf-8")
    with pytest.raises(IntakeError) as error:
        hook.trigger(data_root, "C-100", csv, store=store, schemas=_with(V1))
    assert error.value.code == "unsupported_format"
    assert not (data_root / "customers" / "C-100" / "inbox").exists()
    assert store.items() == []


def test_a_result_that_does_not_reproduce_is_unclassified(data_root, store, monkeypatch):
    real = staging.rebuild

    def drifting(root, company_id, source_id, sheet):
        return replace(real(root, company_id, source_id, sheet), fingerprint="0" * 64)

    monkeypatch.setattr(staging, "rebuild", drifting)
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1))
    assert arrival.outcome == "unclassified"
    assert store.get(arrival.ticket)["title"].endswith("unclassified: the trial did not reproduce from the raw file")
    assert queue.pending(store) == []


def test_the_fitting_kind_is_chosen_among_several(data_root, store):
    orders = Versioned("C-100", "orders", 3, HeaderSchema("Orders", 1, (Column("Order", "text"),)))
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(orders, V1))
    assert (arrival.outcome, arrival.file_kind) == ("fits", "stock_export")
    tried = store.get(arrival.finding)["data"]["tried"]
    assert {(t["file_kind"], t["outcome"]) for t in tried} == {("orders", "wrong_file"), ("stock_export", "fits")}


def test_two_kinds_with_the_same_headers_cannot_be_told_apart(data_root, store):
    twin = Versioned("C-100", "stock_copy", 1, STOCK)
    arrival = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1, twin))
    assert arrival.outcome == "unclassified"
    assert "fits more than one file kind" in store.get(arrival.ticket)["title"]


def test_a_schema_that_refuses_an_accepted_file_is_reported_as_a_schema_defect(data_root, store, tmp_path):
    first = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1))
    dispositions.admit(store, first.ticket, "anna", "fits")
    # A provider serving another declaration under the version the file was accepted with. The
    # store's versions never change, so only another provider (or a changed trial) can do this.
    strict = Versioned("C-100", "stock_export", 1, HeaderSchema("Stock", 1, STOCK.columns[:3] + (
        Column("On hand", "bool"),) + STOCK.columns[4:]))
    later = stock_export(tmp_path / "stock_export_2026-08-28.xlsx", week_ending=date(2026, 8, 28))
    arrival = hook.trigger(data_root, "C-100", later, store=store, schemas=_with(strict))
    assert arrival.outcome == "schema_defect"
    refused = store.get(arrival.finding)["data"]["evidence"]["accepted_files_refused"]
    assert [r["source_id"] for r in refused] == [first.source_id]


def test_files_accepted_under_an_earlier_version_do_not_make_a_schema_defect(data_root, store, tmp_path, workbook):
    first = hook.trigger(data_root, "C-100", EXPORT, store=store, schemas=_with(V1))
    dispositions.admit(store, first.ticket, "anna", "fits")
    renamed = HeaderSchema("Stock", 1, STOCK.columns[:3] + (Column("Quantity on hand", "int"),) + STOCK.columns[4:])
    v2 = Versioned("C-100", "stock_export", 2, renamed)
    rows = [list(renamed.names), ["SP-1", "Part", "FI", 7.5, datetime(2026, 8, 21)]]
    arrival = hook.trigger(data_root, "C-100", workbook(tmp_path / "bad.xlsx", {"Stock": rows}),
                           store=store, schemas=_with(v2))
    # the file accepted under v1 keeps v1 and is not tried against v2, so the refusal is the file's
    assert arrival.outcome == "value_problem"
    assert store.get(arrival.finding)["data"]["evidence"] == {"accepted_files_checked": []}


def test_an_unestablished_company_gets_no_inbox(data_root, store):
    with pytest.raises(IntakeError) as error:
        hook.trigger(data_root, "C-999", EXPORT, store=store, schemas=_with(V1))
    assert error.value.code == "unknown_company"
