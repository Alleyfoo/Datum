"""Read-only logical comparison for an explicitly authorized local task handoff.

The before JSON must contain the four tables captured before the handoff.
This check opens the database read-only and never uses task MCP tools.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import datum_engine
import task_domain

TABLES = ('tasks', 'evaluations', 'reviews', 'events')


def rows_by_task(rows, task_id, equal=True):
    return [row for row in rows if (row['task_id'] == task_id) == equal]


def verify(before, db_path, task_id):
    db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity check failed'
        assert not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign key check failed'
        after = {table: [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')] for table in TABLES}
    finally:
        db.close()
    for table in TABLES:
        assert rows_by_task(before[table],task_id,False) == rows_by_task(after[table],task_id,False), f'Unrelated {table} rows changed'
    old_task = rows_by_task(before['tasks'], task_id)
    new_task = rows_by_task(after['tasks'], task_id)
    assert len(old_task)==len(new_task)==1
    for field in ('task_id','task_type','recommendation','next_steps','created_at','created_by'):
        assert old_task[0][field]==new_task[0][field], f'Unexpected task change: {field}'
    old_params=json.loads(old_task[0]['parameters'])
    params=json.loads(new_task[0]['parameters'])
    assert old_params=={'machine_id':'BC-01','strategy':'baseline','allow_substitutes':False}
    assert params=={'machine_id':'BC-01','strategy':'delivery','allow_substitutes':False}
    old_evals=rows_by_task(before['evaluations'], task_id)
    new_evals=rows_by_task(after['evaluations'], task_id)
    assert len(new_evals)==len(old_evals)+1 and new_evals[:-1]==old_evals, 'Original evaluations were altered or unexpected evaluations added'
    old_reviews=rows_by_task(before['reviews'], task_id)
    new_reviews=rows_by_task(after['reviews'], task_id)
    assert len(new_reviews)==len(old_reviews)+1 and new_reviews[:-1]==old_reviews, 'Review history changed unexpectedly'
    old_events=rows_by_task(before['events'], task_id)
    new_events=rows_by_task(after['events'], task_id)
    assert new_events[:len(old_events)]==old_events, 'Existing events changed'
    appended=new_events[len(old_events):]
    kinds={event['event_type'] for event in appended}
    assert {'parameter_changed','data_sources_accessed','rule_applied','evaluation_completed','human_review_recorded','task_reopened'} <= kinds
    assert kinds <= {'parameter_changed','data_sources_accessed','evaluation_completed','human_review_recorded','parameters_validated','rule_applied','task_reopened','tool_invoked'}, 'Unexpected task events'
    review=new_reviews[-1]; evaluation=new_evals[-1]
    assert evaluation['initiator']=='human' and review['initiator']=='human', 'Expected unverified human labels'
    assert review['evaluation_id']==evaluation['evaluation_id'] and review['decision']=='needs_more_information'
    assert 'Automated UI test' in review['note'], 'Synthetic review is not explicitly labelled'
    review_events=[event for event in appended if event['event_type']=='human_review_recorded']
    assert len(review_events)==1 and json.loads(review_events[0]['details']).get('authorization') is False, 'Review must not be recorded as authorization'
    result=json.loads(evaluation['result'])
    original=json.loads(old_evals[0]['result'])
    captured=datum_engine.capture_sources()
    source_hashes=datum_engine.source_hashes(captured)
    assert original['receipt']['source_hashes']==source_hashes==result['receipt']['source_hashes'], 'Source hash mismatch'
    assert task_domain.evaluate_task(old_task[0]['task_type'],old_params,captured)==original, 'Original evaluation does not match its receipt and evidence'
    assert task_domain.evaluate_task(new_task[0]['task_type'],params,captured)==result, 'Recomputed evaluation does not match recorded receipt and evidence'
    assert json.loads(new_task[0]['outstanding_questions'])==result['unresolved']
    return {'status':'pass','database_integrity':'ok','foreign_keys':'ok','unrelated_rows':'unchanged',
            'target_task':task_id,'old_receipt':original['receipt']['run_id'],'new_receipt':result['receipt']['run_id'],
            'old_evaluation':old_evals[0]['evaluation_id'],'new_evaluation':evaluation['evaluation_id'],
            'review_id':review['review_id'],'review_decision':review['decision'],'initiator_label':review['initiator'],
            'source_hashes':source_hashes,'new_event_count':len(appended),'new_event_types':sorted(kinds)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',required=True,type=Path)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--task-id',required=True)
    args=parser.parse_args()
    print(json.dumps(verify(json.loads(args.before.read_text(encoding='utf-8')),args.db,args.task_id),indent=2))

if __name__=='__main__':
    main()
