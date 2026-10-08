from datetime import date, datetime
from pathlib import Path

import pytest

from babel.intake import inbox, staging, trial
from babel.schema.headers import Column, HeaderError, HeaderSchema
from domains.spare_parts.exports import stock_export

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "stock_export_2026-08-21.xlsx"
VARIANT = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"
STOCK = HeaderSchema("Stock", 1, (
    Column("Item", "text"), Column("Description", "text"), Column("Warehouse", "text"),
    Column("On hand", "int"), Column("Stock date", "date"),
))
HEADER = ["Item", "Description", "Warehouse", "On hand", "Stock date"]
DAY = datetime(2026, 8, 21)


def _sheets(root, path):
    source = inbox.preserve(root, "C-100", path)
    return source.source_id, staging.stage_all(root, "C-100", source.source_id)


def _write(tmp_path, workbook, rows, name="stock.xlsx", sheet="Stock", cached=None):
    return workbook(tmp_path / name, {sheet: rows}, cached=cached)


def test_the_weekly_export_fits_its_schema(data_root):
    _, sheets = _sheets(data_root, EXPORT)
    result = trial.run(sheets, STOCK)
    assert (result.outcome, result.rows_checked, result.refusals) == ("fits", 19, [])
    assert len(result.cells) == 19 * 5 and {c.status for c in result.cells} == {"accepted"}
    first = {c.header: c.value for c in result.cells if c.row == 2}
    assert first == {"Item": "SP-1001", "Description": "Conveyor belt EP630/4, 800 mm, per m",
                     "Warehouse": "FI", "On hand": 57, "Stock date": "2026-08-21"}
    assert trial.headline(result) == "fits: 19 rows, 0 refusals"


def test_the_renamed_header_is_a_structural_change_and_values_are_not_compared(data_root):
    _, sheets = _sheets(data_root, VARIANT)
    result = trial.run(sheets, STOCK)
    assert result.outcome == "structural_change"
    assert result.differences == [{"kind": "header", "column": "c004", "expected": "On hand",
                                   "found": "Quantity on hand", "code": "s"}]
    assert result.evidence == {"missing": ["On hand"], "added": ["Quantity on hand"], "moved": []}
    assert result.cells == []
    assert "c004: expected 'On hand', found 'Quantity on hand' (type code s)" in trial.report(result, STOCK)


def test_unrelated_headers_are_a_wrong_file(data_root, tmp_path, workbook):
    path = _write(tmp_path, workbook, [["Code", "Name", "Qty Sold"], ["A-100", "Bolt", 12]], sheet="Data")
    _, sheets = _sheets(data_root, path)
    result = trial.run(sheets, STOCK)
    assert (result.outcome, result.headers_found, result.cells) == ("wrong_file", 0, [])
    assert result.evidence["closest"]["texts"] == ["Code", "Name", "Qty Sold"]


def test_two_of_five_headers_is_still_a_wrong_file_three_is_a_change(data_root, tmp_path, workbook):
    two = _write(tmp_path, workbook, [["Item", "Description", "Qty", "Site", "When"]], name="two.xlsx")
    three = _write(tmp_path, workbook, [["Item", "Description", "Warehouse", "Qty", "When"]], name="three.xlsx")
    assert trial.run(_sheets(data_root, two)[1], STOCK).outcome == "wrong_file"
    assert trial.run(_sheets(data_root, three)[1], STOCK).outcome == "structural_change"


def test_a_preamble_row_and_a_renamed_sheet_are_structural_changes(data_root, tmp_path, workbook):
    path = _write(tmp_path, workbook, [["Stock report, week 34"], HEADER, ["SP-1", "Part", "FI", 1, DAY]],
                  sheet="Products")
    result = trial.run(_sheets(data_root, path)[1], STOCK)
    assert result.outcome == "structural_change"
    assert result.differences == [
        {"kind": "sheet", "expected": "Stock", "found": "Products", "sheets": ["Products"]},
        {"kind": "header_row", "expected": 1, "found": 2},
    ]


def test_moved_and_extra_headers_are_listed(data_root, tmp_path, workbook):
    moved = ["Item", "Description", "On hand", "Warehouse", "Stock date", "Batch"]
    result = trial.run(_sheets(data_root, _write(tmp_path, workbook, [moved]))[1], STOCK)
    assert result.outcome == "structural_change"
    assert [d["column"] for d in result.differences] == ["c003", "c004", "c006"]
    assert result.evidence["moved"] == [{"name": "Warehouse", "expected": "c003", "found": ["c004"]},
                                        {"name": "On hand", "expected": "c004", "found": ["c003"]}]
    assert result.evidence["added"] == ["Batch"]


def test_every_refused_cell_is_listed_with_its_rule(data_root, tmp_path, workbook):
    rows = [
        HEADER,
        ["SP-1", "Part one", "FI", 7.5, DAY],             # not a whole number
        ["SP-2", "Part two", "FI", "12", DAY],            # numeric text is text
        [],                                              # blank row
        ["SP-3", "   ", "SE", 2, DAY],                    # blank text
        ["SP-4", "Part four", "SE", 3, datetime(2026, 8, 21, 14, 30), "extra"],  # a time; a stray value
        ["SP-5", "Part five", None, 2, DAY],               # missing required value
    ]
    _, accepted_sheets = _sheets(data_root, EXPORT)
    source_id, sheets = _sheets(data_root, _write(tmp_path, workbook, rows))
    result = trial.run(sheets, STOCK, accepted=[("src_export", accepted_sheets)])
    assert result.outcome == "value_problem"
    assert [(c.row, c.column, c.reason, c.rule) for c in result.refusals] == [
        (2, "c004", "not_integer", "C4"),
        (3, "c004", "wrong_type", "C4"),
        (4, "", "blank_row", "R4"),
        (5, "c002", "blank_text", "C2"),
        (6, "c005", "not_a_date", "C5"),
        (6, "c006", "undeclared_cell", "R5"),
        (7, "c003", "missing_value", "C3"),
    ]
    assert (result.rows_checked, result.rows_refused) == (6, 6)
    assert result.evidence == {"accepted_files_checked": ["src_export"]}
    text = trial.report(result, STOCK)
    assert "row 5, c002 'Description': blank_text (rule C2); text '   ', type code s" in text


def test_an_optional_column_may_be_empty(data_root, tmp_path, workbook):
    schema = HeaderSchema("Stock", 1, STOCK.columns[:2] + (Column("Warehouse", "text", required=False),)
                          + STOCK.columns[3:])
    path = _write(tmp_path, workbook, [HEADER, ["SP-5", "Part five", None, 2, DAY]])
    result = trial.run(_sheets(data_root, path)[1], schema)
    assert result.outcome == "fits"
    assert [c.value for c in result.cells if c.header == "Warehouse"] == [None]


def test_a_schema_that_refuses_accepted_files_is_a_schema_defect(data_root, tmp_path):
    wrong = HeaderSchema("Stock", 1, STOCK.columns[:3] + (Column("On hand", "bool"),) + STOCK.columns[4:])
    _, accepted_sheets = _sheets(data_root, EXPORT)
    later = stock_export(tmp_path / "stock_export_2026-08-28.xlsx", week_ending=date(2026, 8, 28))
    result = trial.run(_sheets(data_root, later)[1], wrong, accepted=[("src_export", accepted_sheets)])
    assert result.outcome == "schema_defect"
    [refused] = result.evidence["accepted_files_refused"]
    assert (refused["source_id"], refused["outcome"], refused["rows_refused"]) == ("src_export", "value_problem", 19)


def test_the_trial_is_deterministic(data_root):
    _, sheets = _sheets(data_root, EXPORT)
    assert trial.run(sheets, STOCK).digest() == trial.run(sheets, STOCK).digest()


def test_the_rule_list_is_complete_and_the_declaration_is_checked():
    rules = dict(STOCK.rules())
    assert list(rules) == ["R1", "R2", "R3", "C1", "C2", "C3", "C4", "C5", "R4", "R5", "R6", "R7"]
    assert rules["C4"].startswith('c004 "On hand": int, required')
    assert HeaderSchema.from_dict(STOCK.to_dict()) == STOCK
    assert len(STOCK.digest()) == 64
    with pytest.raises(HeaderError):
        HeaderSchema("Stock", 1, (Column("Item", "text"), Column("Item", "int")))
    with pytest.raises(HeaderError):
        HeaderSchema("Stock", 0, (Column("Item", "text"),))
    with pytest.raises(HeaderError):
        HeaderSchema("Stock", 1, (Column("Item", "float"),))
