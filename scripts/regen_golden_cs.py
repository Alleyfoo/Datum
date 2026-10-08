"""Regenerate the customer-service scenario's golden files in tests/golden/cs/. Run by hand; pytest never does.

The texts are the scenario in tests/cs_scenario.py: the call "CH-02 has stopped. The customer needs
SP-1601" through the role's tools, on a fresh record in a temporary directory, and the tickets after
it by status. Each is written as UTF-8 with LF line endings, exactly as the tools return it; a file
whose text is unchanged is not rewritten, and a golden that has left the scenario is removed. The
lab's own output in tests/golden/cs/lab_reference/ is evidence and is never touched.

A changed golden is a changed answer: review the diff before committing it.

    python scripts/regen_golden_cs.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "cs"

sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from cs_scenario import scenario  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cs-scenario-") as tmp:
        out = scenario(Path(tmp))
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

    print(f"{len(out)} texts in {GOLDEN.relative_to(ROOT).as_posix()}: "
          f"{len(written)} written, {len(out) - len(written)} unchanged, {len(removed)} removed")
    for name in written:
        print(f"  written  {name}")
    for name in removed:
        print(f"  removed  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
