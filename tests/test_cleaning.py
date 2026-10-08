from dataclasses import asdict, replace
from datetime import datetime

import pytest

from babel.intake import cleaning, hook, inbox, schemas, staging, trial
from babel.intake.cleaning import CleaningError
from babel.schema.headers import Column, HeaderError, HeaderSchema, Versioned

STOCK = HeaderSchema("Stock", 1, (
    Column("Item", "text"), Column("Description", "text"), Column("Warehouse", "text"),
    Column("On hand", "int"), Column("Stock date", "date"),
))
DAY = datetime(2026, 8, 21)


def _staged(root, path):
    source = inbox.preserve(root, "C-100", path)
    return source.source_id, staging.stage_all(root, "C-100", source.source_id)


def _messy(tmp_path, workbook):
    """The stock export's layout with stray whitespace in three headers and three values."""
    return workbook(tmp_path / "messy.xlsx", {"Stock": [
        [" Item", "Description ", "Warehouse", "On hand\t", "Stock date"],
        ["SP-1001 ", "  Conveyor belt", "FI", 57, DAY],
        ["SP-1002", "Bearing 6204", " SE ", 3, DAY],
    ]})


def _changes(cleaned):
    return [(c.row, c.column, c.rule, c.transform, c.original, c.transformed) for c in cleaned.changes]


def test_whitespace_in_headers_and_values_is_trimmed_and_recorded(data_root, tmp_path, workbook):
    source_id, sheets = _staged(data_root, _messy(tmp_path, workbook))
    cleaned = cleaning.clean(sheets, STOCK)
    assert _changes(cleaned) == [
        (1, "c001", "T1", "trim", " Item", "Item"),
        (1, "c002", "T1", "trim", "Description ", "Description"),
        (1, "c004", "T1", "trim", "On hand\t", "On hand"),
        (2, "c001", "T1", "trim", "SP-1001 ", "SP-1001"),
        (2, "c002", "T1", "trim", "  Conveyor belt", "Conveyor belt"),
        (3, "c003", "T1", "trim", " SE ", "SE"),
    ]
    # P21: a header with stray whitespace matches its declared header, after cleaning only
    assert trial.run(sheets, STOCK).outcome == "wrong_file"
    result = trial.run(cleaned.datasets, STOCK)
    assert (result.outcome, result.refusals) == ("fits", [])
    assert {c.header: c.value for c in result.cells if c.row == 2}["Item"] == "SP-1001"

    folder = cleaning.record(data_root, "C-100", cleaned)
    assert folder == data_root / "customers" / "C-100" / "cleaning" / source_id / STOCK.digest()[:16]
    manifest, stored = cleaning.stored(data_root, "C-100", source_id, STOCK)
    assert stored == [asdict(c) for c in cleaned.changes]
    assert (manifest["changes"], manifest["by_rule"], manifest["digest"]) == (6, {"T1": 6}, cleaned.digest())
    assert manifest["fingerprints"]["Stock"]["staged"] == sheets[0].fingerprint != cleaned.datasets[0].fingerprint


def test_a_declared_upper_case_field_is_upper_cased_and_recorded(data_root, tmp_path, workbook):
    upper = HeaderSchema("Stock", 1, (Column("Item", "text", case="upper"),) + STOCK.columns[1:])
    rows = [list(STOCK.names), ["sp-1001", "conveyor belt", "FI", 57, DAY], [" sp-1002 ", "Bearing", "SE", 3, DAY]]
    _, sheets = _staged(data_root, workbook(tmp_path / "lower.xlsx", {"Stock": rows}))
    cleaned = cleaning.clean(sheets, upper)
    assert _changes(cleaned) == [
        (2, "c001", "T2", "upper", "sp-1001", "SP-1001"),
        (3, "c001", "T1", "trim", " sp-1002 ", "sp-1002"),  # two rules on one cell: two records, in order
        (3, "c001", "T2", "upper", "sp-1002", "SP-1002"),
    ]
    result = trial.run(cleaned.datasets, upper)
    assert [c.value for c in result.cells if c.header == "Item"] == ["SP-1001", "SP-1002"]
    # a field with no declaration gets only the default
    assert [c.value for c in result.cells if c.header == "Description"] == ["conveyor belt", "Bearing"]
    assert cleaned.datasets[0].rows[0].texts[0] == "Item"  # the header itself is not upper-cased


def test_staging_is_byte_identical_before_and_after_cleaning(data_root, tmp_path, workbook):
    source_id, sheets = _staged(data_root, _messy(tmp_path, workbook))
    folder = staging.staging_dir(data_root, "C-100", source_id)

    def staged_bytes():
        return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

    before = staged_bytes()
    cleaning.record(data_root, "C-100", cleaning.clean(sheets, STOCK))
    assert before and staged_bytes() == before
    assert staging.datasets(data_root, "C-100", source_id) == sheets
    assert sheets[0].rows[0].texts[0] == " Item"  # the staged header keeps its space
    [dataset] = sheets
    assert staging.verify(data_root, "C-100", source_id, dataset.dataset_id)["reproducible"]


def test_a_value_of_only_spaces_becomes_empty_and_is_handled_as_empty(data_root, tmp_path, workbook):
    optional = HeaderSchema("Stock", 1, STOCK.columns[:2] + (Column("Warehouse", "text", required=False),)
                            + STOCK.columns[3:])
    rows = [list(STOCK.names), ["SP-1", "   ", "FI", 1, DAY], ["SP-2", "Part two", "  ", 2, DAY], [" ", "\t"]]
    _, sheets = _staged(data_root, workbook(tmp_path / "spaces.xlsx", {"Stock": rows}))
    cleaned = cleaning.clean(sheets, optional)
    assert [(c.row, c.column, c.original, c.transformed, c.code) for c in cleaned.changes] == [
        (2, "c002", "   ", "", "e"), (3, "c003", "  ", "", "e"), (4, "c001", " ", "", "e"), (4, "c002", "\t", "", "e"),
    ]
    assert sheets[0].rows[1].codes[1] == "s" and cleaned.datasets[0].rows[1].codes[1] == "e"
    result = trial.run(cleaned.datasets, optional)
    # required: a missing value, not a blank text; optional: empty; a row of nothing else: a blank row
    assert [(c.row, c.column, c.reason) for c in result.refusals] == [(2, "c002", "missing_value"), (4, "", "blank_row")]
    assert [c.value for c in result.cells if c.header == "Warehouse"] == ["FI", None]


def test_the_hook_cleans_before_the_trial_and_the_finding_names_the_records(data_root, store, tmp_path, workbook):
    v1 = Versioned("C-100", "stock_export", 1, STOCK)
    arrival = hook.trigger(data_root, "C-100", _messy(tmp_path, workbook), store=store, schemas=lambda company: [v1])
    assert (arrival.outcome, arrival.schema_version) == ("fits", 1)
    finding = store.get(arrival.finding)
    summary = finding["data"]["cleaning"]
    assert (summary["changes"], summary["by_rule"]) == (6, {"T1": 6})
    assert summary["stored"] == f"cleaning/{arrival.source_id}/{STOCK.digest()[:16]}"
    assert f"Cleaning: 6 change(s) (T1: 6)" in finding["body"]
    assert finding["data"]["verification"]["trial_reproduced"]
    manifest, stored = cleaning.stored(data_root, "C-100", arrival.source_id, STOCK)
    assert manifest["digest"] == summary["digest"] and len(stored) == 6


def test_a_schema_drafted_from_a_messy_file_passes_it_after_cleaning(data_root, store, tmp_path, workbook):
    arrival = hook.trigger(data_root, "C-100", _messy(tmp_path, workbook), store=store)
    assert arrival.outcome == "no_schema"
    [sheet] = staging.datasets(data_root, "C-100", arrival.source_id)
    drafted, evidence = schemas.suggest(sheet)
    assert drafted == STOCK  # names are read as cleaning leaves them
    assert evidence[0]["header"] == "Item"
    store.claim(arrival.ticket, "ville")
    schemas.draft(store, arrival.ticket, "ville", "stock_export", drafted, "Drafted from this export")
    item = schemas.confirm(store, data_root, arrival.ticket, "anna", "Headers checked against the ERP")
    assert item["title"] == "messy.xlsx: fits schema stock_export v1: ready to import"
    [finding] = [d for d in store.documents_about(arrival.ticket, "finding") if d["data"].get("schema_version") == 1]
    assert finding["data"]["cleaning"]["changes"] == 6


def test_a_field_declares_case_or_nothing_and_the_rule_list_shows_it():
    upper = HeaderSchema("Stock", 1, (Column("Item", "text", case="upper"),) + STOCK.columns[1:])
    assert HeaderSchema.from_dict(upper.to_dict()) == upper
    assert upper.to_dict()["columns"][0]["case"] == "upper"
    assert "case" not in STOCK.to_dict()["columns"][0]  # an undeclared field's declaration is unchanged
    defaults = [rule_id for rule_id, _ in STOCK.cleaning_rules()]  # what every source gets
    assert defaults[-1] == "T1" and STOCK.transforms() == []
    rules = dict(upper.cleaning_rules())
    assert list(rules) == defaults + ["T2"] and "upper case" in rules["T2"] and '"Item"' in rules["T2"]
    text = upper.rule_text()
    assert text.startswith(defaults[0] + "  ") and "\nT2  " in text and text.index("\nT2  ") < text.index("\nR1  ")
    for bad in (Column("Item", "text", case="title"), Column("Item", "int", case="upper"), Column(" Item", "text")):
        with pytest.raises(HeaderError):
            HeaderSchema("Stock", 1, (bad,))


def test_records_are_written_once(data_root, tmp_path, workbook):
    _, sheets = _staged(data_root, _messy(tmp_path, workbook))
    cleaned = cleaning.clean(sheets, STOCK)
    folder = cleaning.record(data_root, "C-100", cleaned)
    written = (folder / "changes.jsonl").read_bytes()
    assert cleaning.record(data_root, "C-100", cleaning.clean(sheets, STOCK)) == folder
    assert (folder / "changes.jsonl").read_bytes() == written
    with pytest.raises(CleaningError) as error:
        cleaning.record(data_root, "C-100", replace(cleaned, changes=cleaned.changes[1:]))
    assert error.value.code == "cleaning_conflict"
    assert (folder / "changes.jsonl").read_bytes() == written
