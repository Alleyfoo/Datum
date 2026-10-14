"""The daily sweep of closed tickets, as a command a scheduler runs once a day:

    python -m datum.record.sweep --store PATH --today YYYY-MM-DD

It runs Store.sweep on the store at PATH for the date given, which deletes the closed tickets no person
has reacted to for more than CLOSED_RETENTION_DAYS, each with its audit line, and prints their numbers.
It reads no clock: the date is an argument, and the store is opened with that date's midnight (UTC) as
its clock, so whatever the run writes (the audit lines, and any migration step an older store needs) is
stamped with it, and a run on the same store and date does the same. A store that does not exist is
not created.

Every failure is reported, never swallowed: the exit code is not 0, and the error is on stderr, with its
traceback when the store or the sweep failed. Exit codes: 0, done; 1, there is no store at PATH, or the
store or the sweep failed; 2, the arguments are wrong. Which scheduler runs it, and when, is not set up
here (the owner's review of round six, build-plan section 30).
"""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import List, Optional

from .store import Store, _moment


def _day(value: str) -> date:
    """A date written YYYY-MM-DD, and nothing else."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a date written YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date: {error}") from None


def main(argv: Optional[List[str]] = None) -> int:
    """Run the sweep once, as the command line asks; return the exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m datum.record.sweep",
        description="Delete the closed tickets no person has reacted to for more than the retention period, "
                    "on the date given.")
    parser.add_argument("--store", required=True, type=Path, help="the ticket store, a SQLite file")
    parser.add_argument("--today", required=True, type=_day,
                        help="the date the sweep runs on, YYYY-MM-DD, taken at midnight UTC")
    args = parser.parse_args(argv)  # wrong arguments: the usage and the error on stderr, exit code 2
    day = args.today.isoformat()
    if not args.store.is_file():
        print(f"sweep failed on {day}: there is no store at {args.store}", file=sys.stderr)
        return 1
    moment = _moment(args.today)
    try:
        deleted = Store(args.store, clock=lambda: moment).sweep(args.today)
    except Exception as error:  # reported, not swallowed: the traceback and the error on stderr, exit code 1
        traceback.print_exc()
        print(f"sweep failed on {day}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(f"sweep {day}: " + (f"deleted {', '.join(f'#{n}' for n in deleted)}" if deleted else "nothing to delete"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
