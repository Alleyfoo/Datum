import hashlib
import os
import stat
from pathlib import Path

import pytest

from babel.intake import inbox
from babel.intake.inbox import IntakeError

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "stock_export_2026-08-21.xlsx"
VARIANT = FIXTURES / "stock_export_2026-08-21_renamed.xlsx"
NOW = "2026-10-08T09:00:00+00:00"


@pytest.fixture
def root(tmp_path):
    data = tmp_path / "data"
    (data / "customers" / "C-100").mkdir(parents=True)
    return data


def test_the_copy_is_named_by_its_content_and_verified(root):
    got = inbox.preserve(root, "C-100", EXPORT, now=NOW)
    sha = hashlib.sha256(EXPORT.read_bytes()).hexdigest()
    assert (got.source_id, got.sha256, got.repeated, got.ledger_seq) == ("src_" + sha[:16], sha, False, 1)
    assert got.path == root / "customers" / "C-100" / "inbox" / got.source_id / EXPORT.name
    assert got.path.read_bytes() == EXPORT.read_bytes()
    assert inbox.manifest(root, "C-100", got.source_id) == {
        "source_id": got.source_id, "sha256": sha, "size": EXPORT.stat().st_size,
        "company_id": "C-100", "original_name": EXPORT.name, "preserved_at": NOW, "read_only": True,
    }
    assert inbox.verify(root, "C-100", got.source_id)["matches"]


def test_the_same_bytes_give_one_id_and_one_copy(root, tmp_path):
    first = inbox.preserve(root, "C-100", EXPORT, now=NOW)
    renamed_copy = tmp_path / "copy of this week.xlsx"
    renamed_copy.write_bytes(EXPORT.read_bytes())
    second = inbox.preserve(root, "C-100", renamed_copy, now=NOW)
    assert (second.source_id, second.path, second.repeated) == (first.source_id, first.path, True)

    folder = root / "customers" / "C-100" / "inbox"
    assert sorted(p.name for p in folder.iterdir()) == ["ledger.jsonl", first.source_id]
    assert sorted(p.name for p in (folder / first.source_id).iterdir()) == ["manifest.json", EXPORT.name]
    ledger = inbox.read_ledger(root, "C-100")
    assert [(e["seq"], e["event"]) for e in ledger] == [(1, "preserved"), (2, "repeated")]
    assert (ledger[1]["first_seq"], ledger[1]["original_name"]) == (1, renamed_copy.name)


def test_different_bytes_get_their_own_id(root):
    export = inbox.preserve(root, "C-100", EXPORT, now=NOW)
    variant = inbox.preserve(root, "C-100", VARIANT, now=NOW)
    assert export.source_id != variant.source_id
    assert not variant.repeated


def test_a_write_to_an_inbox_file_raises(root):
    got = inbox.preserve(root, "C-100", EXPORT, now=NOW)
    for mode in ("wb", "ab", "r+b"):
        with pytest.raises(PermissionError):
            open(got.path, mode)
    with pytest.raises(PermissionError):
        open(got.path.parent / "manifest.json", "w")
    assert inbox.verify(root, "C-100", got.source_id)["read_only"]
    assert got.path.read_bytes() == EXPORT.read_bytes()


def test_a_changed_copy_is_caught_when_the_file_arrives_again(root):
    got = inbox.preserve(root, "C-100", EXPORT, now=NOW)
    os.chmod(got.path, stat.S_IREAD | stat.S_IWRITE)  # tampering from outside the system
    with open(got.path, "ab") as handle:
        handle.write(b"x")
    assert not inbox.verify(root, "C-100", got.source_id)["matches"]
    with pytest.raises(IntakeError) as error:
        inbox.preserve(root, "C-100", EXPORT, now=NOW)
    assert error.value.code == "inbox_corrupt"


def test_the_ledger_is_only_appended_to(root):
    inbox.preserve(root, "C-100", EXPORT, now=NOW)
    ledger = root / "customers" / "C-100" / "inbox" / "ledger.jsonl"
    before = ledger.read_bytes()
    inbox.preserve(root, "C-100", VARIANT, now=NOW)
    inbox.preserve(root, "C-100", EXPORT, now=NOW)
    after = ledger.read_bytes()
    assert after.startswith(before)
    assert [e["event"] for e in inbox.read_ledger(root, "C-100")] == ["preserved", "preserved", "repeated"]


def test_a_rewritten_ledger_is_refused(root):
    inbox.preserve(root, "C-100", EXPORT, now=NOW)
    inbox.preserve(root, "C-100", VARIANT, now=NOW)
    ledger = root / "customers" / "C-100" / "inbox" / "ledger.jsonl"
    second_line = ledger.read_text(encoding="utf-8").splitlines()[1]
    ledger.write_text(second_line + "\n", encoding="utf-8")  # the first arrival removed
    with pytest.raises(IntakeError) as error:
        inbox.preserve(root, "C-100", EXPORT, now=NOW)
    assert error.value.code == "ledger_corrupt"


@pytest.mark.parametrize("company, code", [("../C-100", "bad_company_id"), ("C-999", "unknown_company")])
def test_unsafe_or_unestablished_companies_are_refused(root, company, code):
    with pytest.raises(IntakeError) as error:
        inbox.preserve(root, company, EXPORT, now=NOW)
    assert error.value.code == code
    assert sorted(p.name for p in (root / "customers").iterdir()) == ["C-100"]


def test_a_missing_file_is_refused(root, tmp_path):
    with pytest.raises(IntakeError) as error:
        inbox.preserve(root, "C-100", tmp_path / "nothing.xlsx", now=NOW)
    assert error.value.code == "not_a_file"
