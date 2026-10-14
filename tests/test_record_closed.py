"""Closed tickets (owner answers S-closed, S-del and S-period, build-plan sections 27 to 29): a ticket
that cannot be finished is closed, and its creator may amend it and repost it, or delete it; one
nobody reacts to for 30 days is deleted by the sweep, with its history, leaving one audit line."""

import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from babel.record.store import CLOSED, CLOSED_RETENTION_DAYS, FINISHED, RecordError, Store

# the clock and store fixtures are in conftest.py

DAY = timedelta(days=1)


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


def test_the_creator_reposts_a_closed_ticket_to_open_with_its_whole_history(store):
    task = _closed(store)
    store.amend(task, "pia", title="Stock export from C-100, week 35")
    history = store.journal(task)
    reposted = store.repost(task, "pia")
    assert (reposted["status"], reposted["claimed_by"], reposted["title"]) == (
        "open", None, "Stock export from C-100, week 35")
    *kept, entry = store.journal(task)
    assert kept == history  # nothing is rewritten or lost
    assert (entry["actor"], entry["role"], entry["action"], entry["details"]) == (
        "pia", "worker", "reposted", {"status": {"before": "closed", "after": "open"}})
    assert [t["number"] for t in store.ready("ville")] == [task]
    assert store.open_ticket(task, "ville")["status"] == "in_progress"  # the next handler takes it up


def test_a_repost_is_refused_unless_the_ticket_is_closed_and_the_actor_created_it(store):
    task = _closed(store)
    assert _code(store.repost, task, "ville") == "not_the_creator"
    store.repost(task, "pia")
    assert _code(store.repost, task, "pia") == "not_closed"  # open
    store.open_ticket(task, "ville")
    assert _code(store.repost, task, "pia") == "not_closed"  # in progress
    finished = store.add_task("pia", "Week 33 export")
    store.finish(finished, "anna", "Imported and checked")
    assert _code(store.repost, finished, "pia") == "not_closed"  # finished stays finished
    assert [e["action"] for e in store.journal(task)].count("reposted") == 1


def _audit_lines(store):
    return [e for e in store.journal() if e["action"] == "deleted"]


def test_a_closed_ticket_stays_for_30_days_and_is_deleted_after(store, clock):
    # S-period (build-plan section 29): 30 days without a reaction, a named setting
    assert CLOSED_RETENTION_DAYS == 30
    task = _closed(store)
    closed_at = clock()
    assert store.sweep(closed_at + 29 * DAY) == [] and store.get(task)["status"] == CLOSED
    assert store.sweep(closed_at + 30 * DAY) == []  # 30 days to the second is not more than 30 days
    assert store.sweep(closed_at + 30 * DAY + timedelta(seconds=1)) == [task]
    assert _code(store.get, task) == "unknown_item"
    assert (store.journal(task), store.items("task")) == ([], [])


def test_the_sweep_takes_its_date_reads_no_clock_and_runs_only_when_called(store, clock):
    first, second = _closed(store), _closed(store)  # closed at 09:00 on 2026-10-08
    clock.advance(days=45)
    assert {i["number"] for i in store.items("task")} == {first, second}  # nothing deletes them by itself
    store.clock = lambda: pytest.fail("the sweep read the clock")
    assert store.sweep(date(2026, 11, 7)) == []  # a date is its midnight in UTC: 29 days and 15 hours on
    assert store.sweep(date(2026, 11, 8)) == [first, second]
    assert _code(store.sweep, datetime(2026, 12, 1)) == "invalid_argument"  # a time needs its time zone
    assert _code(store.sweep, "2026-12-01") == "invalid_argument"


def test_a_finished_ticket_is_never_deleted_however_old(store, clock):
    task = store.add_task("pia", "Week 33 export")
    store.finish(task, "anna", "Imported and checked")
    history = store.journal(task)
    assert store.sweep(clock() + 3650 * DAY) == []
    assert (store.get(task)["status"], store.journal(task)) == (FINISHED, history)


def test_a_reaction_starts_the_30_days_again(store, clock):
    task = _closed(store)
    closed_at = clock()
    clock.advance(days=20)
    store.comment(task, "anna", "Is this export still needed?")
    assert store.sweep(closed_at + 31 * DAY) == []  # 11 days after the comment
    assert store.sweep(closed_at + 50 * DAY) == []  # 30 days after the comment, to the second
    assert store.sweep(closed_at + 50 * DAY + timedelta(seconds=1)) == [task]


def test_an_amendment_or_a_document_about_it_is_a_reaction_too(store, clock):
    amended, noted = _closed(store), _closed(store)
    closed_at = clock()
    clock.advance(days=25)
    store.amend(amended, "pia", title="Stock export from C-100, week 35")
    store.add_document("anna", "finding", "Still needed", "The week 34 export is needed after all", about=noted)
    assert store.sweep(closed_at + 31 * DAY) == []
    assert store.sweep(closed_at + 56 * DAY) == [amended, noted]


def test_one_audit_line_stays_with_the_number_and_the_times_and_no_content(store, clock):
    task = _closed(store)
    closed_at = store.now()
    store.add_document("ville", "finding", "Header differs", "Column c004 is renamed", about=task)
    when = clock() + 31 * DAY
    store.sweep(when)
    [line] = _audit_lines(store)
    deleted_at = when.isoformat(timespec="seconds")
    assert (line["item"], line["actor"], line["role"], line["at"]) == (None, "system", "system", deleted_at)
    assert line["details"] == {"ticket": task, "closed_at": closed_at, "deleted_at": deleted_at}
    kept = json.dumps([store.journal(), store.items()], ensure_ascii=False)
    for content in ("Stock export from C-100", "Check the week 34 export.", "Header differs", "c004"):
        assert content not in kept, content


def test_the_documents_only_about_it_go_with_it_and_the_others_stay(store, clock):
    task, other = _closed(store), store.add_task("hook", "Another file arrived")
    only = store.add_document("ville", "finding", "Header differs", "Column c004 is renamed", about=task)
    shared = store.add_document("ville", "finding", "One supplier", "Both files come from one supplier", about=task)
    store.link("ville", shared, "about", other)
    store.link("ville", task, "blocks", other)
    assert store.sweep(clock() + 31 * DAY) == [task]
    assert (_code(store.get, only), store.journal(only)) == ("unknown_item", [])
    assert (store.get(shared)["title"], store.linked(shared, "about")) == ("One supplier", [other])
    assert store.linked(other, "blocks", incoming=True) == []
    assert [e["action"] for e in store.journal(shared)] == ["created", "linked", "linked"]  # its history stays


def test_a_deleted_tickets_number_is_never_used_again(store, clock):
    task = _closed(store)
    store.sweep(clock() + 31 * DAY)
    assert store.add_task("hook", "Next file") == task + 1


def _referred_to(store, number):
    """A kept record that refers to the ticket, as a schema version refers to the ticket it was drafted on."""
    store.ensure("CREATE TABLE IF NOT EXISTS kept_records (ticket INTEGER NOT NULL REFERENCES items(number));")
    with store.transaction() as db:
        db.execute("INSERT INTO kept_records VALUES (?)", (number,))


def test_a_closed_ticket_a_kept_record_refers_to_is_kept(store, clock):
    kept, gone = _closed(store), _closed(store)
    _referred_to(store, kept)
    assert store.sweep(clock() + 31 * DAY) == [gone]
    assert store.get(kept)["status"] == CLOSED
    assert [line["details"]["ticket"] for line in _audit_lines(store)] == [gone]


def test_the_database_refuses_every_other_delete(store, clock):
    closed, working = _closed(store), store.add_task("hook", "Another file arrived")
    store.sweep(clock() + 31 * DAY)
    again = _closed(store)
    db = sqlite3.connect(store.path)
    try:
        for statement in (f"DELETE FROM items WHERE number={again}", f"DELETE FROM journal WHERE item={again}",
                          "DELETE FROM journal WHERE item IS NULL"):  # the store did not mark them; nor the audit line
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(statement)
        db.execute(f"INSERT INTO deleting VALUES ({working})")
        with pytest.raises(sqlite3.DatabaseError):  # marked or not, a task that is not closed stays
            db.execute(f"DELETE FROM items WHERE number={working}")
    finally:
        db.rollback()
        db.close()
    assert [len(store.journal(n)) > 0 for n in (working, again)] == [True, True]
    assert [line["details"]["ticket"] for line in _audit_lines(store)] == [closed]


def _with_the_old_guards(store):
    """Leave the store as round five wrote it: delete guards that refused every delete, and version 1."""
    db = sqlite3.connect(store.path)
    try:
        db.executescript("""
            DROP TRIGGER items_no_delete_but_closed;
            DROP TRIGGER journal_no_delete_but_closed;
            DROP TABLE deleting;
            CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal
            BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END;
            CREATE TRIGGER items_no_delete BEFORE DELETE ON items
            BEGIN SELECT RAISE(ABORT, 'items are never deleted, so a number is never reused'); END;
            PRAGMA user_version=1;""")
    finally:
        db.close()


def test_an_older_store_opens_with_every_ticket_and_lets_a_closed_one_go_in_time(store, clock):
    closed, working = _closed(store), store.add_task("hook", "Another file arrived")
    _with_the_old_guards(store)
    before = store.items()
    reopened = Store(store.path, clock=clock)
    assert reopened.items() == before  # no ticket lost, none changed
    db = sqlite3.connect(store.path)
    try:
        triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        version = db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()
    assert {"items_no_delete_but_closed", "journal_no_delete_but_closed"} <= triggers
    assert not {"items_no_delete", "journal_no_delete"} & triggers and version >= 2
    assert reopened.sweep(clock() + 31 * DAY) == [closed]
    assert [i["number"] for i in reopened.items()] == [working]
