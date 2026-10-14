"""Closed tickets (owner answers S-closed, S-del and S-period, build-plan sections 27 to 29, and the
owner's review of round six, section 30): a ticket that cannot be finished is closed, only by close,
with its reason; the person who answers for it (its creator, or its recipient) is told, and may amend
it and repost it, or delete it; one nobody reacts to for 30 days is deleted by the sweep, with its
history, leaving one audit line."""

import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from babel.record import consultations as cons
from babel.record import queue, sweep
from babel.record.store import CLOSED, CLOSED_RETENTION_DAYS, FINISHED, REVIEW_QUEUE, RecordError, Store, notice

# the clock and store fixtures are in conftest.py

DAY = timedelta(days=1)
ROOT = Path(__file__).resolve().parent.parent
NOTICE = ("#{n} is closed: it could not be finished. pia, as its creator you may amend it and repost it, which "
          "opens it again with its history, or delete it. If nobody reacts to it for 30 days, it is deleted, "
          "with its history.")


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _closed(store, creator="pia", worker="ville"):
    """A task the creator wrote, which a worker took up and closed, with the reason."""
    task = store.add_task(creator, "Stock export from C-100", body="Check the week 34 export.")
    store.claim(task, worker)
    store.close(task, worker, "The supplier no longer sends this export")
    return task


def test_a_worker_closes_a_ticket_that_cannot_be_finished_and_its_creator_is_notified(store):
    # S-close and S-closed (build-plan sections 27 and 29): closed with a reason; the creator is told what to do
    task = store.add_task("pia", "Stock export from C-100", body="Check the week 34 export.")
    store.open_ticket(task, "ville")
    closed = store.close(task, "ville", "The supplier no longer sends this export")
    assert (closed["status"], closed["claimed_by"], closed["lease_until"]) == (CLOSED, None, None)
    entry, told = store.journal(task)[-2:]
    assert (entry["actor"], entry["role"], entry["action"], entry["at"]) == ("ville", "worker", "closed", store.now())
    assert entry["details"] == {"reason": "The supplier no longer sends this export",
                                "status": {"before": "in_progress", "after": "closed"}, "released": "ville"}
    assert (told["actor"], told["role"], told["action"], told["at"]) == ("system", "system", "notice", store.now())
    assert told["details"] == {"to": "pia", "text": NOTICE.format(n=task)}
    assert _code(store.claim, task, "ville") == "item_closed"
    assert _code(store.resume, task, "ville") == "item_closed"
    assert _code(store.finish, task, "anna", "Done after all") == "item_closed"


def test_closing_needs_the_claim_the_worker_role_and_a_reason(store):
    task = store.add_task("pia", "Stock export from C-100")
    assert _code(store.close, task, "ville", "Not ours") == "claim_required"
    store.claim(task, "ville")
    for reason in ("", "   "):
        assert _code(store.close, task, "ville", reason) == "invalid_argument"
    store.release(task, "ville")
    store.claim(task, "anna")
    assert _code(store.close, task, "anna", "Not ours") == "role_missing"  # workers close; anna only approves
    store.release(task, "anna")
    store.claim(task, "hook")
    assert _code(store.close, task, "hook", "Not ours") == "role_missing"  # a service account holds no role
    assert store.get(task)["status"] == "open"
    assert "closed" not in [e["action"] for e in store.journal(task)]


def test_a_ticket_waiting_on_a_proposal_or_already_ended_is_not_closed(store):
    waiting = store.add_task("pia", "Stock export from C-100")
    store.claim(waiting, "ville")
    queue.propose(store, waiting, "ville", "import", "Fits the schema")
    store.claim(waiting, "ville")
    assert _code(store.close, waiting, "ville", "Not ours") == "proposal_pending"  # the approver decides first
    closed = _closed(store)
    assert _code(store.close, closed, "ville", "Again") == "item_closed"
    finished = store.add_task("pia", "Week 33 export")
    store.finish(finished, "anna", "Imported and checked")
    assert _code(store.close, finished, "ville", "Not ours") == "item_finished"


def test_whatever_closes_a_ticket_its_creator_is_notified(store):
    # S-closed: a task's close and a consultation's close are each followed by the notice to its creator
    task = _closed(store)
    call = cons.start(store, "ville", "Consultation: Customer one", subject={})["number"]
    cons.close(store, call, "ville", "The customer's machine is not one of ours")
    for number, creator in ((task, "pia"), (call, "ville")):
        closing, told = store.journal(number)[-2:]
        assert (closing["action"], closing["details"]["status"]["after"]) == ("closed", CLOSED)
        assert (told["action"], told["details"]) == ("notice", {"to": creator, "text": notice(number, creator)})


def test_set_status_never_closes_a_ticket_close_does_with_its_reason(store):
    # the owner's decision on R6-Q4 (build-plan section 30): no reasonless closure
    task = store.add_task("pia", "Stock export from C-100")
    store.claim(task, "ville")
    with pytest.raises(RecordError, match=rf"#{task} is closed only with a reason: close\(number, actor, reason\)") as refused:
        store.set_status(task, "ville", CLOSED)
    assert refused.value.code == "reason_required"
    assert store.get(task)["status"] == "open"
    assert [e["action"] for e in store.journal(task)] == ["created", "claimed"]  # no close and no notice
    assert store.close(task, "ville", "The supplier no longer sends this export")["status"] == CLOSED


def test_no_path_closes_a_ticket_without_its_reason_the_worker_role_and_the_claim(store):
    # the check sits at the store's boundary, Store.update, which every change of status goes through
    task = store.add_task("pia", "Stock export from C-100")
    store.claim(task, "ville")
    for actor, role, note, code in [
            ("ville", None, None, "reason_required"),
            ("ville", None, {"reason": "  "}, "reason_required"),
            ("ville", None, {"decision": 7}, "reason_required"),
            ("anna", None, {"reason": "Not ours"}, "role_missing"),  # an approver who decides never closes
            ("pia", "approver", {"reason": "Not ours"}, "role_missing"),
            ("pia", None, {"reason": "Not ours"}, "claim_required")]:  # a worker, but ville holds the claim
        with pytest.raises(RecordError) as refused:
            with store.transaction() as db:
                store.update(db, task, actor, role=role, note=note, status=CLOSED)
        assert refused.value.code == code, (actor, role, note)
    waiting = store.add_task("pia", "Week 35 export")
    store.claim(waiting, "ville")
    queue.propose(store, waiting, "ville", "import", "Fits the schema")
    with pytest.raises(RecordError) as refused:  # an approval whose effect would close the ticket
        queue.approve(store, waiting, "anna", "Not ours after all", effect=lambda db, item, proposal: {"status": CLOSED})
    assert (refused.value.code, store.journal(waiting)[-1]["action"]) == ("role_missing", "approval_refused")
    for status in (CLOSED, FINISHED):  # nor is a task created closed, or finished
        with pytest.raises(RecordError) as refused:
            with store.transaction() as db:
                store.create_item(db, "pia", "task", "task", "Born ended", status=status)
        assert refused.value.code == "invalid_status"
    assert [store.get(n)["status"] for n in (task, waiting)] == ["open", "needs_input"]
    assert "notice" not in [e["action"] for e in store.journal()]


def test_the_database_refuses_a_close_the_store_has_not_marked_with_its_actor_and_reason(store):
    task = store.add_task("pia", "Stock export from C-100")
    db = sqlite3.connect(store.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="a ticket is closed only by close"):
            db.execute("UPDATE items SET status='closed' WHERE number=?", (task,))
        for status in ("closed", "finished"):
            with pytest.raises(sqlite3.DatabaseError, match="a task is never created closed or finished"):
                db.execute("INSERT INTO items (kind, type, title, body, data, status, created_by, created_at,"
                           " updated_at, version) VALUES ('task', 'task', 'Born ended', '', '{}', ?, 'pia', '', '', 1)",
                           (status,))
    finally:
        db.rollback()
        db.close()
    assert [i["status"] for i in store.items()] == ["open"]


def test_every_close_records_who_closed_the_ticket_and_why(store, clock):
    old = store.add_task("pia", "Week 32 export")
    db = sqlite3.connect(store.path)
    try:  # as the code before P25 left a close: the status done, and a store without a version
        db.execute("UPDATE items SET status='done' WHERE number=?", (old,))
        db.execute("PRAGMA user_version=0")
        db.commit()
    finally:
        db.close()
    reopened = Store(store.path, clock=clock)  # the migration closes it, as the store's own system user
    task = _closed(reopened)
    call = cons.start(reopened, "ville", "Consultation: Customer one", subject={})["number"]
    cons.close(reopened, call, "ville", "The customer's machine is not one of ours")
    closes = [e for e in reopened.journal() if (e["details"].get("status") or {}).get("after") == CLOSED]
    assert [(e["item"], e["actor"], e["details"]["reason"]) for e in closes] == [
        (old, "system", "the status done is called closed (owner answer P25, build-plan section 25)"),
        (task, "ville", "The supplier no longer sends this export"),
        (call, "ville", "The customer's machine is not one of ours")]
    with reopened.reading() as db:  # the database's mark lasts for the closing transaction only
        assert db.execute("SELECT COUNT(*) FROM closing").fetchone()[0] == 0


def _intake(store):
    """A ticket the hook opened for an arriving file, which a worker could not process and closed."""
    task = store.add_task("hook", "stock_export.xlsx: new kind of file for C-100: create a schema")
    store.claim(task, "ville")
    store.close(task, "ville", "The workbook's sheets cannot be read")
    return task


def test_a_closed_ticket_a_service_opened_is_notified_to_its_recipient_not_the_service(store):
    # the owner's decision on R6-Q2 (build-plan section 30): notices reach a person who answers for the ticket
    task = _intake(store)
    item = store.get(task)
    assert (item["created_by"], item["recipient"]) == ("hook", REVIEW_QUEUE)  # the hook stays its originator
    assert store.journal(task)[0]["details"]["recipient"] == REVIEW_QUEUE
    told = store.journal(task)[-1]
    assert (told["actor"], told["action"], told["details"]["to"]) == ("system", "notice", REVIEW_QUEUE)
    assert told["details"]["text"] == (
        f"#{task} is closed: it could not be finished. hook opened it and does not answer for it, so it is for "
        "the approval queue: an approver may amend it and repost it, which opens it again with its history, or "
        "delete it. If nobody reacts to it for 30 days, it is deleted, with its history.")
    assert [(n["number"], n["created_by"], n["notice"]) for n in store.notices(REVIEW_QUEUE)] == [
        (task, "hook", told["details"]["text"])]
    assert store.notices("hook") == []


def test_a_person_answers_for_a_ticket_a_service_opened_and_the_journal_names_that_person(store):
    task, other = _intake(store), _intake(store)
    for call, args in ((store.amend, {"title": "Mine now"}), (store.repost, {}), (store.delete, {})):
        assert _code(call, task, "hook", **args) == "not_a_person"  # though it opened the ticket
        assert _code(call, task, "ville", **args) == "not_responsible"  # a worker does not answer for the queue
    store.amend(task, "anna", title="stock_export.xlsx: the corrected export of week 35")
    reposted = store.repost(task, "anna")
    assert (reposted["status"], reposted["created_by"], reposted["title"]) == (
        "open", "hook", "stock_export.xlsx: the corrected export of week 35")
    assert [(e["actor"], e["role"], e["action"]) for e in store.journal(task)[-2:]] == [
        ("anna", "approver", "amended"), ("anna", "approver", "reposted")]
    store.delete(other, "pia")  # pia holds both roles: for the approval queue, she acts as an approver
    [line] = _audit_lines(store)
    assert (line["actor"], line["role"], line["details"]["ticket"]) == ("pia", "approver", other)


def test_a_person_answers_for_a_ticket_an_agent_opened_and_the_agent_does_not(store):
    store.add_user("drafting-assistant", ["worker"], kind="agent")
    call = cons.start(store, "drafting-assistant", "Consultation: Customer one", subject={})["number"]
    cons.close(store, call, "drafting-assistant", "The customer's machine is not one of ours")
    assert store.get(call)["recipient"] == REVIEW_QUEUE
    assert store.journal(call)[-1]["details"] == {"to": REVIEW_QUEUE,
                                                  "text": notice(call, REVIEW_QUEUE, "drafting-assistant")}
    assert f"Notice to {REVIEW_QUEUE}: #{call} is closed" in cons.view_text(cons.view(store, call))
    assert _code(store.repost, call, "drafting-assistant") == "not_a_person"
    assert store.repost(call, "anna")["status"] == "open"
    assert [(e["actor"], e["action"]) for e in store.journal(call)[-1:]] == [("anna", "reposted")]


def test_a_named_recipient_answers_for_a_ticket_and_is_told_by_name(store):
    store.add_user("drafting-assistant", ["worker"], kind="agent")
    assert _code(store.add_task, "hook", "A file arrived", recipient="drafting-assistant") == "not_a_person"
    assert _code(store.add_task, "hook", "A file arrived", recipient="nobody") == "unknown_user"
    assert _code(store.add_user, REVIEW_QUEUE, ["worker"]) == "invalid_argument"  # the queue is not a user
    task = store.add_task("hook", "Stock export from C-200", recipient="ville")  # say, the company's data owner
    store.claim(task, "pia")
    store.close(task, "pia", "The supplier no longer sends this export")
    assert store.journal(task)[-1]["details"] == {"to": "ville", "text": notice(task, "ville", "hook")}
    assert "ville, as the person who answers for it (it was opened by hook) you may amend it" in notice(task, "ville", "hook")
    assert _code(store.repost, task, "anna") == "not_responsible"  # a named person answers for it, not the queue
    store.repost(task, "ville")
    assert [(e["actor"], e["role"], e["action"]) for e in store.journal(task)[-1:]] == [("ville", "worker", "reposted")]


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


def test_only_the_person_answering_for_it_amends_and_only_a_closed_ticket_with_new_text(store):
    task = _closed(store)
    _code(store.amend, task, "ville", title="Mine now")  # refused: pia created it, and its notices go to her
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


def test_a_repost_is_refused_unless_the_ticket_is_closed_and_the_actor_answers_for_it(store):
    task = _closed(store)
    _code(store.repost, task, "ville")  # refused: pia created it, and its notices go to her
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


def _run_sweep(*args):
    """The daily sweep as a scheduler runs it: the command, in a process of its own."""
    return subprocess.run([sys.executable, "-m", "babel.record.sweep", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=120)


def test_the_daily_sweep_is_a_command_that_runs_on_the_date_it_is_given(store, capsys):
    # the owner's review of round six (build-plan section 30): an entry point a daily scheduler calls
    task = _closed(store)  # closed at 09:00 on 2026-10-08
    early = _run_sweep("--store", str(store.path), "--today", "2026-11-07")
    assert (early.returncode, early.stdout, early.stderr) == (0, "sweep 2026-11-07: nothing to delete\n", "")
    ran = _run_sweep("--store", str(store.path), "--today", "2026-11-08")
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, f"sweep 2026-11-08: deleted #{task}\n", "")
    [line] = _audit_lines(store)  # stamped with the date it was given: it read no clock
    assert (line["actor"], line["at"], line["details"]["ticket"]) == ("system", "2026-11-08T00:00:00+00:00", task)
    assert sweep.main(["--store", str(store.path), "--today", "2026-11-08"]) == 0  # again: nothing is left
    assert capsys.readouterr() == ("sweep 2026-11-08: nothing to delete\n", "")


def test_a_failing_sweep_exits_non_zero_and_says_why_on_stderr(tmp_path):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"These bytes are not a SQLite database. " * 10)
    failed = _run_sweep("--store", str(broken), "--today", "2026-11-08")
    assert (failed.returncode, failed.stdout) == (1, "")
    assert "Traceback" in failed.stderr
    assert "sweep failed on 2026-11-08: DatabaseError: file is not a database" in failed.stderr
    missing = tmp_path / "nowhere" / "babel.sqlite"
    gone = _run_sweep("--store", str(missing), "--today", "2026-11-08")
    assert (gone.returncode, gone.stdout) == (1, "") and "there is no store at" in gone.stderr
    assert not missing.parent.exists()  # nothing is created
    for wrong in (["--store", str(broken)], ["--store", str(broken), "--today", "8.11.2026"],
                  ["--store", str(broken), "--today", "2026-02-30"]):
        refused = _run_sweep(*wrong)
        assert (refused.returncode, refused.stdout) == (2, "") and "--today" in refused.stderr, wrong


def test_the_command_reports_a_failure_of_the_sweep_itself(store, monkeypatch, capsys):
    _closed(store)

    def failing(self, today):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    monkeypatch.setattr(Store, "sweep", failing)
    assert sweep.main(["--store", str(store.path), "--today", "2026-11-08"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "Traceback" in err
    assert err.endswith("sweep failed on 2026-11-08: IntegrityError: FOREIGN KEY constraint failed\n")


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


def test_an_automated_entry_does_not_start_the_30_days_again(store, clock):
    # the owner's review of round six (build-plan section 30): no automated write postpones a deletion
    store.add_user("drafting-assistant", ["worker"], kind="agent")
    task = _closed(store)
    closed_at = clock()
    clock.advance(days=20)
    store.comment(task, "hook", "The same file arrived again as week34.xlsx; nothing else was done.")  # a service
    store.comment(task, "drafting-assistant", "This export may be needed later.")  # an agent
    store.add_document("drafting-assistant", "finding", "Week 35 is alike", "The same header as week 34", about=task)
    assert _code(queue.approve, store, task, "anna", "Fine") == "nothing_to_decide"  # refused, and journaled
    assert [e["action"] for e in store.journal(task)][-3:] == ["comment", "comment", "approval_refused"]
    assert store.sweep(closed_at + 30 * DAY + timedelta(seconds=1)) == [task]  # 30 days after it was closed


def test_a_repost_or_a_decision_starts_the_30_days_again(store, clock):
    # a person's comment and amendment do too (the two tests above)
    reposted, decided = _closed(store), _closed(store)
    closed_at = clock()
    clock.advance(days=20)
    store.repost(reposted, "pia")
    store.add_document("anna", "decision", f"Kept: #{decided}", "Keep it: the supplier may send it again",
                       data={"decision": "kept", "ticket": decided, "approver": "anna",
                             "reason": "The supplier may send it again"}, about=decided)
    clock.advance(days=5)
    store.claim(reposted, "ville")
    store.close(reposted, "ville", "The supplier confirmed that the export has stopped")
    assert store.sweep(closed_at + 31 * DAY) == []
    assert store.sweep(closed_at + 50 * DAY + timedelta(seconds=1)) == [decided]  # 30 days after the decision
    assert store.sweep(closed_at + 55 * DAY + timedelta(seconds=1)) == [reposted]  # 30 days after its new close


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
    store.finish(other, "anna", "Imported and checked")  # the task it blocked waits on it no more
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


def test_a_closed_ticket_is_kept_while_a_kept_record_refers_to_a_document_only_about_it(store, clock):
    task = _closed(store)
    finding = store.add_document("ville", "finding", "Header differs", "Column c004 is renamed", about=task)
    _referred_to(store, finding)
    assert store.sweep(clock() + 31 * DAY) == []
    assert _code(store.delete, task, "pia") == "still_referred_to"
    assert (store.get(task)["status"], store.get(finding)["title"]) == (CLOSED, "Header differs")


def test_the_sweep_raises_what_fails_instead_of_skipping_it(store, clock, monkeypatch):
    # the owner's review of round six (build-plan section 30): the sweep never swallows an exception. It used to
    # skip any deletion the database refused with a FOREIGN KEY error, whatever had caused it
    first, second = _closed(store), _closed(store)

    def refused(db, number, actor, role, at):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    monkeypatch.setattr(store, "_delete", refused)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.sweep(clock() + 31 * DAY)
    assert [store.get(n)["status"] for n in (first, second)] == [CLOSED, CLOSED]


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


def test_the_creator_deletes_a_closed_ticket_now_with_the_same_one_audit_line(store, clock):
    task = _closed(store)
    closed_at = store.now()
    store.add_document("ville", "finding", "Header differs", "Column c004 is renamed", about=task)
    clock.advance(hours=2)
    assert store.delete(task, "pia") is None
    assert (_code(store.get, task), store.journal(task)) == ("unknown_item", [])
    [line] = _audit_lines(store)
    assert (line["item"], line["actor"], line["role"], line["at"]) == (None, "pia", "worker", store.now())
    assert line["details"] == {"ticket": task, "closed_at": closed_at, "deleted_at": store.now()}
    assert "Header differs" not in json.dumps(store.journal(), ensure_ascii=False)


def test_only_the_person_answering_for_it_deletes_and_only_a_closed_ticket_nobody_refers_to(store):
    task, kept = _closed(store), _closed(store)
    _code(store.delete, task, "ville")  # refused: pia created it, and its notices go to her
    store.repost(task, "pia")
    assert _code(store.delete, task, "pia") == "not_closed"
    finished = store.add_task("pia", "Week 33 export")
    store.finish(finished, "anna", "Imported and checked")
    assert _code(store.delete, finished, "pia") == "not_closed"
    _referred_to(store, kept)
    assert _code(store.delete, kept, "pia") == "still_referred_to"
    assert [store.get(n)["status"] for n in (task, finished, kept)] == ["open", FINISHED, CLOSED]
    assert _audit_lines(store) == []


def test_a_closed_ticket_a_task_waits_on_is_not_deleted_until_the_dependency_is_resolved(store, clock):
    # the owner's decision on R6-Q1 (build-plan section 30): deleting it would remove an unresolved blocker
    # without a word, so the deletion is refused, by the sweep and by its creator alike
    blocker, waiting = _closed(store), store.add_task("pia", "Import the week 34 export")
    store.link("ville", blocker, "blocks", waiting)
    assert store.sweep(clock() + 31 * DAY) == []
    with pytest.raises(RecordError, match=f"#{blocker} stays: #{waiting} waits on it") as refused:
        store.delete(blocker, "pia")
    assert refused.value.code == "still_blocking"
    assert (store.get(blocker)["status"], store.linked(waiting, "blocks", incoming=True)) == (CLOSED, [blocker])
    assert store.ready() == [] and _audit_lines(store) == []
    store.resolve_dependency(waiting, blocker, "anna", "The import goes ahead without it")
    assert store.sweep(clock() + 31 * DAY) == [blocker]
    assert [t["number"] for t in store.ready()] == [waiting]


def test_a_closed_blocker_of_a_closed_task_goes_once_that_task_is_gone(store, clock):
    blocker, waiting = _closed(store), _closed(store)
    store.link("ville", blocker, "blocks", waiting)
    assert store.sweep(clock() + 31 * DAY) == [waiting]  # reposted, a closed task would wait on it again
    assert store.sweep(clock() + 32 * DAY) == [blocker]  # gone, it leaves nothing waiting


def _with_the_old_guards(store):
    """Leave the store as round five wrote it: delete guards that refused every delete, no guard on how a
    ticket is created or closed, and version 1."""
    db = sqlite3.connect(store.path)
    try:
        db.executescript("""
            DROP TRIGGER items_no_delete_but_closed;
            DROP TRIGGER journal_no_delete_but_closed;
            DROP TABLE deleting;
            DROP TRIGGER IF EXISTS items_closed_with_a_reason;
            DROP TRIGGER IF EXISTS items_created_open;
            DROP TABLE IF EXISTS closing;
            CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal
            BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END;
            CREATE TRIGGER items_no_delete BEFORE DELETE ON items
            BEGIN SELECT RAISE(ABORT, 'items are never deleted, so a number is never reused'); END;
            PRAGMA user_version=1;""")
    finally:
        db.close()


def test_an_older_store_finishes_its_approved_closed_tickets_and_tells_the_creators_of_the_rest(store, clock):
    # S-finish and S-closed: older code closed a ticket for every end, an approval's too
    approved, stopped, working = (store.add_task("pia", f"Week {week} export") for week in (33, 34, 35))
    store.claim(approved, "ville")
    queue.propose(store, approved, "ville", "import", "Fits the schema")
    queue.approve(store, approved, "anna", "Imported and checked")
    [decision] = store.documents_about(approved, "decision")
    _with_the_old_guards(store)
    db = sqlite3.connect(store.path)
    try:  # as round five's code left them: the approval's end and a close without a decision, both closed
        db.execute("UPDATE items SET status='closed' WHERE number IN (?, ?)", (approved, stopped))
        db.commit()
    finally:
        db.close()
    before = {i["number"]: i for i in store.items()}
    clock.advance(hours=1)
    reopened = Store(store.path, clock=clock)
    after = {i["number"]: i for i in reopened.items()}
    assert sorted(after) == sorted(before)  # no ticket and no document is lost
    assert [after[n]["status"] for n in (approved, stopped, working)] == [FINISHED, CLOSED, "open"]
    assert after[approved]["version"] == before[approved]["version"] + 1
    migrated = reopened.journal(approved)[-1]
    assert (migrated["actor"], migrated["action"], migrated["at"]) == ("system", "migrated", reopened.now())
    assert (migrated["details"]["status"], migrated["details"]["decision"]) == (
        {"before": "closed", "after": "finished"}, decision["number"])
    told = reopened.journal(stopped)[-1]
    assert (told["actor"], told["action"], told["at"]) == ("system", "notice", reopened.now())
    assert told["details"] == {"to": "pia", "text": NOTICE.format(n=stopped)}
    assert [e["action"] for e in reopened.journal(working)] == ["created"]
    assert reopened.sweep(clock() + 29 * DAY) == []  # its 30 days start when its creator is told
    assert reopened.sweep(clock() + 3650 * DAY) == [stopped]  # and the finished one is never deleted
    entries = len(reopened.journal())
    Store(store.path, clock=clock)  # opened again: the steps have run, and nothing more changes
    assert len(reopened.journal()) == entries


def _as_round_six_left_it(store):
    """Leave the store as round six wrote it: no guard on how a ticket is created or closed, and version 3."""
    db = sqlite3.connect(store.path)
    try:
        db.executescript("""
            DROP TRIGGER IF EXISTS items_closed_with_a_reason;
            DROP TRIGGER IF EXISTS items_created_open;
            DROP TABLE IF EXISTS closing;
            PRAGMA user_version=3;""")
    finally:
        db.close()


@pytest.mark.parametrize("older, told", [(_with_the_old_guards, True), (_as_round_six_left_it, False)],
                         ids=["round five", "round six"])
def test_an_older_store_finishes_what_its_approvers_dropped_and_keeps_its_workers_drops_closed(
        store, clock, older, told):
    # the owner's decision on R6-Q3 (build-plan section 30): older code closed the ticket of every drop
    by_approver, by_worker = store.add_task("hook", "Week 33 export"), store.add_task("hook", "Week 34 export")
    decisions = {}
    for number, by, role in ((by_approver, "anna", "approver"), (by_worker, "ville", "worker")):
        decisions[number] = store.add_document(
            by, "decision", f"Dropped: #{number}", f"Dropped by {by} ({role}): a duplicate",
            data={"decision": "dropped", "disposition": "drop", "ticket": number, "by": by, "role": role,
                  "reason": "A duplicate of last week's export"}, about=number, role=role)
    older(store)
    db = sqlite3.connect(store.path)
    try:  # as older code left a drop: the decision on the ticket, and the ticket closed
        for number, decision in decisions.items():
            db.execute("UPDATE items SET status='closed', data=? WHERE number=?",
                       (json.dumps({"decisions": [decision]}), number))
        db.commit()
    finally:
        db.close()
    clock.advance(hours=1)
    reopened = Store(store.path, clock=clock)
    assert [reopened.get(n)["status"] for n in (by_approver, by_worker)] == [FINISHED, CLOSED]
    migrated = reopened.journal(by_approver)[-1]
    assert (migrated["actor"], migrated["action"], migrated["at"]) == ("system", "migrated", reopened.now())
    assert (migrated["details"]["status"], migrated["details"]["decision"]) == (
        {"before": "closed", "after": "finished"}, decisions[by_approver])
    assert "notice" not in [e["action"] for e in reopened.journal(by_approver)]  # never told it is closed
    # a worker's drop stays closed; round five's store tells its creator now, round six told it at the close
    assert ("notice" in [e["action"] for e in reopened.journal(by_worker)]) is told
    entries = len(reopened.journal())
    Store(store.path, clock=clock)  # opened again: the steps have run, and nothing more changes
    assert len(reopened.journal()) == entries
    assert reopened.sweep(clock() + 3650 * DAY) == [by_worker]  # the finished one is never deleted


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


def test_an_older_store_gives_each_task_its_recipient_and_tells_the_approval_queue_what_the_hook_was_told(
        store, clock, monkeypatch):
    # the owner's decision on R6-Q2 (build-plan section 30): a notice older code addressed to the hook reached nobody
    def to_the_creator(db, item):  # what the store wrote on a close before the decision
        store.write_journal(db, item["number"], "system", "system", "notice",
                            {"to": item["created_by"], "text": notice(item["number"], item["created_by"])})
    monkeypatch.setattr(store, "_notify", to_the_creator)
    by_hook, by_pia, working = (store.add_task(creator, f"Week {week} export")
                                for creator, week in (("hook", 33), ("pia", 34), ("hook", 35)))
    for number in (by_hook, by_pia):
        store.claim(number, "ville")
        store.close(number, "ville", "The workbook's sheets cannot be read")
    db = sqlite3.connect(store.path)
    try:  # and with no recipient, at version 4
        db.executescript("ALTER TABLE items DROP COLUMN recipient; PRAGMA user_version=4;")
    finally:
        db.close()
    before = [i["number"] for i in store.items()]
    clock.advance(hours=1)
    reopened = Store(store.path, clock=clock)
    assert [i["number"] for i in reopened.items()] == before  # no ticket and no document is lost
    assert [reopened.get(n)["recipient"] for n in (by_hook, by_pia, working)] == [REVIEW_QUEUE, "pia", REVIEW_QUEUE]
    told = reopened.journal(by_hook)[-1]
    assert (told["actor"], told["action"], told["at"]) == ("system", "notice", reopened.now())
    assert told["details"] == {"to": REVIEW_QUEUE, "text": notice(by_hook, REVIEW_QUEUE, "hook")}
    assert [e["details"]["to"] for e in reopened.journal(by_pia) if e["action"] == "notice"] == ["pia"]  # told once
    assert [e["action"] for e in reopened.journal(working)] == ["created"]
    assert reopened.sweep(clock() + 29 * DAY) == []  # the approval queue's 30 days start when it is told
    entries = len(reopened.journal())
    Store(store.path, clock=clock)  # opened again: the steps have run, and nothing more changes
    assert len(reopened.journal()) == entries
