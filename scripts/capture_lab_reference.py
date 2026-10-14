"""Maintainer only: needs the private research repository named below; not runnable without it.

Capture the lab's desk views as reference text. Run once; never by pytest, never by the port.

The lab is frozen, so nothing is run inside it. The five files the views need are read from
one lab commit with `git show`, written to a temporary directory and imported from there in a
child Python with PYTHONDONTWRITEBYTECODE=1 and -B. The screens are the ones listed in
tests/view_screens.py, the same catalogue the port is tested with.

The output directory must be new or empty: committed references are never overwritten. To
check them, capture into an empty directory and compare the two.

    python scripts/capture_lab_reference.py --lab <path to Predictive-Spare-Parts-Lab> \\
        --out tests/golden/views/lab_reference
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
REV = "fa3836f68242fc2ce200f78e66374d1e673edb44"  # lab HEAD when the reference was captured
FILES = ("desk/__init__.py", "desk/data.py", "desk/tools.py", "desk/views.py", "desk/desk_widget.html")

CHILD = """
import sys
from pathlib import Path

copy, tests, out = sys.argv[1:4]
sys.path[:0] = [copy, tests]
import desk.data
import desk.views
assert Path(desk.views.__file__).resolve().parent == (Path(copy) / "desk").resolve(), desk.views.__file__
from view_screens import screens

for name, text in screens(desk.views, desk.data.demo()).items():
    (Path(out) / f"{name}.txt").write_text(text, encoding="utf-8", newline="\\n")
"""


def _git(lab: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(lab), *args], capture_output=True, check=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lab", required=True, type=Path, help="the lab repository (read only)")
    parser.add_argument("--rev", default=REV, help=f"lab commit to read (default {REV[:7]})")
    parser.add_argument("--out", required=True, type=Path, help="a new or empty directory")
    args = parser.parse_args()

    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        print(f"refused: {out} is not empty; references are captured once", file=sys.stderr)
        return 2
    commit = _git(args.lab, "rev-parse", f"{args.rev}^{{commit}}").decode().strip()

    with tempfile.TemporaryDirectory(prefix="lab-desk-") as tmp:
        copy = Path(tmp)
        (copy / "desk").mkdir()
        blobs = []
        for name in FILES:
            (copy / name).write_bytes(_git(args.lab, "show", f"{commit}:{name}"))
            blobs.append((name, _git(args.lab, "rev-parse", f"{commit}:{name}").decode().strip()))
        out.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([sys.executable, "-B", "-c", CHILD, str(copy), str(TESTS), str(out)],
                       env=env, cwd=copy, check=True)

    print(f"lab commit {commit}, Python {platform.python_version()}")
    for name, blob in blobs:
        print(f"  {name}  blob {blob}")
    print(f"{len(list(out.glob('*.txt')))} files written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
