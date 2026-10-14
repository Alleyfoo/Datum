import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from openpyxl import Workbook

from datum.record.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_root(tmp_path):
    """A data root with one established customer, C-100."""
    root = tmp_path / "data"
    (root / "customers" / "C-100").mkdir(parents=True)
    return root


class Clock:
    """A clock the test moves by hand, so leases run out when the test says so."""

    def __init__(self):
        self.at = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.at

    def advance(self, **delta):
        self.at += timedelta(**delta)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    """A record with an approver (anna), a worker (ville), one person holding both (pia) and the hook."""
    s = Store(tmp_path / "state" / "datum.sqlite", clock=clock)
    s.add_user("anna", ["approver"])
    s.add_user("ville", ["worker"])
    s.add_user("pia", ["approver", "worker"])
    s.add_user("hook", kind="service")
    return s


@pytest.fixture
def workbook():
    """The workbook writer below, as a fixture."""
    return write_workbook


def write_workbook(path, sheets, cached=None):
    """Write {sheet name: [rows]} to an .xlsx.

    `cached` maps (sheet name, cell) to a number or a text stored as that formula cell's cached
    value, the way Excel saves a calculated workbook (a text result is marked t="str"); openpyxl
    itself never writes one. openpyxl writes the empty value as <v></v> with lxml installed, as <v/>
    without it, or leaves it out, so all three are accepted.
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
            kind = ' t="str"' if isinstance(value, str) else ""
            xml, count = re.subn(rf'(<c r="{cell}"[^>]*)(><f>[^<]*</f>)(?:<v></v>|<v\s*/>)?(?=</c>)',
                                 lambda found: f"{found[1]}{kind}{found[2]}<v>{escape(str(value))}</v>",
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
