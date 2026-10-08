import json
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from babel.intake import cleaning, inbox, staging
from babel.intake.staging import StagingError
from domains.spare_parts.exports import HEADERS

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "stock_export_2026-08-21.xlsx"
VARIANT = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"

# Recorded from the committed fixture; any change in what staging keeps changes it.
GOLDEN = "287b2b7f9d7cdf5d9d1b07064f272ec2e252d29797a7b7d30bd81fb6b610c6fc"


def _staged(root, path, sheet="Stock"):
    source = inbox.preserve(root, "C-100", path)
    return source.source_id, staging.stage(root, "C-100", source.source_id, sheet)


def test_the_stock_export_stages_to_its_golden_fingerprint(data_root):
    source_id, dataset = _staged(data_root, EXPORT)
    assert dataset.fingerprint == GOLDEN
    assert (dataset.width, len(dataset.rows), dataset.columns[-1]) == (5, 20, "c005")
    assert dataset.rows[0].texts == HEADERS
    assert dataset.rows[0].codes == "sssss"
    assert {row.codes for row in dataset.rows[1:]} == {"sssnd"}  # numbers keep n, dates d
    assert dataset.rows[1].texts == ("SP-1001", "Conveyor belt EP630/4, 800 mm, per m", "FI", "57",
                                     "2026-08-21T00:00:00")
    assert staging.verify(data_root, "C-100", source_id, dataset.dataset_id)["reproducible"]


def test_staging_gives_the_same_files_on_every_run(tmp_path):
    outputs = []
    for run in ("first", "second"):
        root = tmp_path / run
        (root / "customers" / "C-100").mkdir(parents=True)
        source_id, dataset = _staged(root, EXPORT)
        folder = staging.staging_dir(root, "C-100", source_id) / dataset.dataset_id
        outputs.append(((folder / "rows.jsonl").read_bytes(), (folder / "manifest.json").read_bytes()))
    assert outputs[0] == outputs[1]


def test_staging_again_returns_the_stored_dataset(data_root):
    source_id, first = _staged(data_root, EXPORT)
    assert staging.stage(data_root, "C-100", source_id, "Stock") == first


def test_the_renamed_variant_differs_only_in_its_header_row(data_root):
    _, export = _staged(data_root, EXPORT)
    _, variant = _staged(data_root, VARIANT)
    assert export.fingerprint != variant.fingerprint
    assert export.rows[1:] == variant.rows[1:]
    assert variant.rows[0].texts[3] == "Quantity on hand"


def _awkward(path, workbook):
    """Spaces, a blank row, every type code, formulas with and without a cached value."""
    return workbook(path, {
        "Data": [
            ["Code", "Name", "Qty", "Flag", "When", "Doubled", "Check"],
            ["A-100", "  Bolt  ", 12, True, datetime(2026, 1, 2, 3, 4, 5), "=C2*2", "#N/A"],
            [],
            ["A-101", "Nut", 7.5, False, date(2026, 1, 3), "=C4*2", "#REF!"],
            [" A-102", "Washer", "0012"],
        ],
        "Notes": [["Exported by the test"]],
    }, cached={("Data", "F2"): 24})


def test_nothing_is_trimmed_coerced_or_dropped(data_root, tmp_path, workbook):
    _, dataset = _staged(data_root, _awkward(tmp_path / "awkward.xlsx", workbook), sheet="Data")
    header, bolt, gap, nut, washer = dataset.rows
    assert dataset.width == 7
    assert bolt.texts == ("A-100", "  Bolt  ", "12", "TRUE", "2026-01-02T03:04:05", "24", "#N/A")
    assert bolt.codes == "ssnbdfx"
    assert bolt.formulas == {"c006": ("=C2*2", "n")}  # the formula, and its cached value is a number
    assert gap.blank and gap.codes == "eeeeeee" and gap.source_row == 3
    assert nut.texts == ("A-101", "Nut", "7.5", "FALSE", "2026-01-03T00:00:00", "", "#REF!")
    assert nut.codes == "ssnbdfx"
    assert nut.formulas == {"c006": ("=C4*2", "e")}  # no cached value in the file
    assert washer.texts[:3] == (" A-102", "Washer", "0012") and washer.codes == "sss" + "e" * 4
    assert not any(row.blank for row in (header, bolt, nut, washer))


def test_the_staging_output_keeps_each_formula_and_the_value_the_file_saved(data_root, tmp_path, workbook):
    # P20: staging keeps the raw evidence; the calculation (cleaning, F1) reads it and never writes it
    source_id, dataset = _staged(data_root, _awkward(tmp_path / "awkward.xlsx", workbook), sheet="Data")
    rows_file = staging.staging_dir(data_root, "C-100", source_id) / dataset.dataset_id / "rows.jsonl"
    before = rows_file.read_bytes()
    stored = [json.loads(line) for line in before.decode("utf-8").splitlines()]
    bolt, nut = stored[1], stored[3]
    assert (bolt["codes"][5], bolt["texts"][5], bolt["formulas"]) == ("f", "24", {"c006": ["=C2*2", "n"]})
    assert (nut["codes"][5], nut["texts"][5], nut["formulas"]) == ("f", "", {"c006": ["=C4*2", "e"]})
    cleaned = cleaning.clean([dataset]).datasets[0]
    assert (cleaned.rows[1].codes[5], cleaned.rows[1].formulas) == ("n", {"c006": ("=C2*2", "n")})
    assert (cleaned.rows[3].codes[5], cleaned.rows[3].texts[5]) == ("f", "")  # nothing saved, nothing taken
    assert rows_file.read_bytes() == before
    assert staging.verify(data_root, "C-100", source_id, dataset.dataset_id)["reproducible"]


def test_blank_rows_are_flagged_in_the_stored_rows(data_root, tmp_path, workbook):
    source_id, dataset = _staged(data_root, _awkward(tmp_path / "awkward.xlsx", workbook), sheet="Data")
    folder = staging.staging_dir(data_root, "C-100", source_id) / dataset.dataset_id
    stored = [json.loads(line) for line in (folder / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["source_row"] for r in stored if r["blank"]] == [3]
    assert stored[1]["row_uid"] == f"{dataset.dataset_id}:2"
    assert {k: stored[1][k] for k in ("source_id", "sheet", "source_row", "row_ordinal")} == {
        "source_id": source_id, "sheet": "Data", "source_row": 2, "row_ordinal": 2}
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["blank_rows"] == [3] and manifest["columns"] == [f"c00{i}" for i in range(1, 8)]


def test_formatted_empty_rows_after_the_table_are_not_rows(data_root, tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append(["Code", "Qty"])
    sheet.append(["A-1", 3])
    sheet["A9"].font = Font(bold=True)  # formatting only: row 9 exists in the file, with no value
    book.save(tmp_path / "formatted.xlsx")
    source_id, dataset = _staged(data_root, tmp_path / "formatted.xlsx", sheet="Data")
    assert len(dataset.rows) == 2
    folder = staging.staging_dir(data_root, "C-100", source_id) / dataset.dataset_id
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["rows_read"] == 9


def test_verify_catches_a_changed_staging_file(data_root):
    source_id, dataset = _staged(data_root, EXPORT)
    rows_file = staging.staging_dir(data_root, "C-100", source_id) / dataset.dataset_id / "rows.jsonl"
    rows_file.write_text(rows_file.read_text(encoding="utf-8").replace('"57"', '"58"', 1), encoding="utf-8")
    result = staging.verify(data_root, "C-100", source_id, dataset.dataset_id)
    assert (result["recorded"], result["rebuilt"]) == (GOLDEN, GOLDEN)
    assert result["stored"] != GOLDEN and not result["reproducible"]
    with pytest.raises(StagingError) as error:
        staging.load(data_root, "C-100", source_id, dataset.dataset_id)
    assert error.value.code == "staging_corrupt"


def test_every_sheet_is_staged_in_workbook_order(data_root, tmp_path, workbook):
    source = inbox.preserve(data_root, "C-100", _awkward(tmp_path / "awkward.xlsx", workbook))
    staged = staging.stage_all(data_root, "C-100", source.source_id)
    assert [(d.sheet, d.sheet_index) for d in staged] == [("Data", 1), ("Notes", 2)]
    assert len({d.dataset_id for d in staged}) == 2
    assert staging.datasets(data_root, "C-100", source.source_id) == staged


def test_an_unknown_sheet_is_refused(data_root):
    source = inbox.preserve(data_root, "C-100", EXPORT)
    with pytest.raises(StagingError) as error:
        staging.stage(data_root, "C-100", source.source_id, "Products")
    assert error.value.code == "unknown_sheet"


def test_a_file_that_is_not_a_workbook_is_unreadable(data_root, tmp_path):
    fake = tmp_path / "not really.xlsx"
    fake.write_bytes(b"this is not a zip file")
    source = inbox.preserve(data_root, "C-100", fake)
    with pytest.raises(StagingError) as error:
        staging.stage_all(data_root, "C-100", source.source_id)
    assert error.value.code == "unreadable_workbook"
