import io
import re
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_root(tmp_path):
    """A data root with one established customer, C-100."""
    root = tmp_path / "data"
    (root / "customers" / "C-100").mkdir(parents=True)
    return root


@pytest.fixture
def workbook():
    """The workbook writer below, as a fixture."""
    return write_workbook


def write_workbook(path, sheets, cached=None):
    """Write {sheet name: [rows]} to an .xlsx.

    `cached` maps (sheet name, cell) to a number stored as that formula cell's cached
    value, the way Excel saves a calculated workbook; openpyxl itself never writes one.
    """
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    data = buffer.getvalue()
    if cached:
        names = list(sheets)
        with zipfile.ZipFile(io.BytesIO(data)) as src:
            parts = {info.filename: src.read(info.filename) for info in src.infolist()}
        for (name, cell), value in cached.items():
            part = f"xl/worksheets/sheet{names.index(name) + 1}.xml"
            xml, count = re.subn(rf'(<c r="{cell}"[^>]*><f>[^<]*</f>)<v></v>', rf"\g<1><v>{value}</v>",
                                 parts[part].decode("utf-8"))
            assert count == 1, f"no empty formula value at {name}!{cell}"
            parts[part] = xml.encode("utf-8")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for filename, content in parts.items():
                dst.writestr(filename, content)
        data = out.getvalue()
    Path(path).write_bytes(data)
    return Path(path)
