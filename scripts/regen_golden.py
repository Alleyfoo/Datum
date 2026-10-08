"""Regenerate the port's golden screens in tests/golden/views/. Run by hand; pytest never does.

The screens are the catalogue in tests/view_screens.py, drawn by domains/spare_parts/views.py from
the synthetic company. Each is written as UTF-8 with LF line endings, exactly as the view returns
it; a file whose text is unchanged is not rewritten, and a golden whose screen has left the
catalogue is removed. The lab's own output in tests/golden/views/lab_reference/ is evidence and is
never touched.

A changed golden is a changed view: review the diff before committing it.

    python scripts/regen_golden.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "views"

sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from domains.spare_parts import views  # noqa: E402
from domains.spare_parts.data import demo  # noqa: E402
from view_screens import screens  # noqa: E402


def main() -> int:
    out = screens(views, demo())
    GOLDEN.mkdir(parents=True, exist_ok=True)
    written, removed = [], []
    for name, text in out.items():
        path = GOLDEN / f"{name}.txt"
        if path.exists() and path.read_bytes() == text.encode("utf-8"):
            continue
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path.name)
    for path in sorted(GOLDEN.glob("*.txt")):
        if path.stem not in out:
            path.unlink()
            removed.append(path.name)

    print(f"{len(out)} screens in {GOLDEN.relative_to(ROOT).as_posix()}: "
          f"{len(written)} written, {len(out) - len(written)} unchanged, {len(removed)} removed")
    for name in written:
        print(f"  written  {name}")
    for name in removed:
        print(f"  removed  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
