"""Closed tickets (owner answers S-closed, S-del and S-period, build-plan sections 27 to 29): a ticket
that cannot be finished is closed, and its creator may amend it and repost it, or delete it."""

import pytest

from babel.record.store import CLOSED, RecordError

# the clock and store fixtures are in conftest.py


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _closed(store, creator="pia", worker="ville"):
    """A task the creator wrote, which a worker took up and closed."""
    task = store.add_task(creator, "Stock export from C-100", body="Check the week 34 export.")
    store.claim(task, worker)
    store.set_status(task, worker, CLOSED)
    return task


def test_the_creator_amends_a_closed_ticket_and_each_amendment_keeps_the_text_before_and_after(store):
    task = _closed(store)
    amended = store.amend(task, "pia", title="Stock export from C-100, week 35")
    assert (amended["title"], amended["body"], amended["status"]) == (
        "Stock export from C-100, week 35", "Check the week 34 export.", CLOSED)
    store.amend(task, "pia", title="Stock export from C-100, week 35", body="Check the week 35 export.")
    first, second = [e for e in store.journal(task) if e["action"] == "amended"]
    assert (first["actor"], first["role"], second["actor"]) == ("pia", "worker", "pia")
    assert first["details"] == {"title": {"before": "Stock export from C-100",
                                          "after": "Stock export from C-100, week 35"}}
    assert second["details"] == {"body": {"before": "Check the week 34 export.", "after": "Check the week 35 export."}}
    assert store.get(task)["status"] == CLOSED  # still closed: reposting is the creator's next step


def test_only_the_creator_amends_and_only_a_closed_ticket_with_new_text(store):
    task = _closed(store)
    assert _code(store.amend, task, "ville", title="Mine now") == "not_the_creator"
    assert _code(store.amend, task, "pia") == "invalid_argument"
    assert _code(store.amend, task, "pia", title=" ") == "invalid_argument"
    assert _code(store.amend, task, "pia", title="Stock export from C-100") == "nothing_changed"
    working = store.add_task("pia", "Another export")
    assert _code(store.amend, working, "pia", title="Renamed") == "not_closed"
    finding = store.add_document("pia", "finding", "A finding", "text")
    assert _code(store.amend, finding, "pia", title="Renamed") == "not_a_task"
    assert [e["action"] for e in store.journal(task)].count("amended") == 0
    assert store.get(working)["title"] == "Another export"
