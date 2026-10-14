"""Answer checks: every number and date in an answer comes from the facts; no other customer is named.

Ported from Parts-Service-Desk desk/expert.py at 46c859a (blob 22f12ed): ``numbers_in``,
``customer_part`` and ``check_answer`` (origin in docs/provenance.md). Here they are core and know
no domain: the facts are text, and the names that must not reach the customer are given by the
domain pack (for spare parts, ``domains.spare_parts.tools.confidential``).

Fixed while porting (backlog C13): the lab split every date into its numbers and compared the
pieces, so a date rebuilt from the pieces of a fact's date passed (2026-10-02 written as
2026-02-10). A date is now one token, compared whole with the dates in the facts, and the numbers
are taken from the text outside dates. A day written apart from its date ("October 22") is a
number the facts do not state, so it fails too: dates are copied as the facts write them.

No model, no clock: the same answer and facts give the same result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple

#: a date as the facts write it (ISO), taken whole
_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Check:
    #: numbers in the answer that appear nowhere in the facts
    unsupported: Tuple[str, ...]
    #: other customers' names or machines mentioned in the customer answer
    leaks: Tuple[str, ...] = ()
    #: dates in the answer that are not dates of the facts, compared whole
    dates: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unsupported and not self.leaks and not self.dates


def dates_in(text: str) -> Set[str]:
    """Every date in a text, whole."""
    return set(_DATE.findall(text))


def numbers_in(text: str) -> Set[str]:
    """Every number outside the dates of a text, normalised: a decimal comma becomes a point and
    leading zeros go. Part numbers still split into their numbers, as in the lab."""
    return {n.replace(",", ".").lstrip("0") or "0" for n in _NUMBER.findall(_DATE.sub(" ", text))}


def customer_part(answer: str) -> str:
    """The CUSTOMER ANSWER section only: the text that may leave the company.

    Without that heading the whole answer counts as the customer's, so a leak is never missed
    because a heading is.
    """
    match = re.search(r"CUSTOMER ANSWER:(.*?)(?:\n\s*SITUATION:|$)", answer, re.S | re.I)
    return match.group(1) if match else answer


def check_answer(answer: str, facts: str, confidential: Iterable[str] = ()) -> Check:
    """Check an answer against the text of its facts and the names it must not give the customer."""
    said = customer_part(answer).lower()
    return Check(
        unsupported=tuple(sorted(numbers_in(answer) - numbers_in(facts), key=float)),
        leaks=tuple(term for term in confidential if term.lower() in said),
        dates=tuple(sorted(dates_in(answer) - dates_in(facts))),
    )


def describe(check: Check) -> List[Tuple[str, str]]:
    """The check as (label, finding) lines, for a receipt."""
    return [
        ("numbers", "not in the facts: " + ", ".join(check.unsupported) if check.unsupported
         else "all in the facts"),
        ("dates", "not in the facts: " + ", ".join(check.dates) if check.dates
         else "all in the facts, compared as whole dates"),
        ("other customers", "named in the customer answer: " + ", ".join(check.leaks) if check.leaks
         else "none named in the customer answer"),
    ]
