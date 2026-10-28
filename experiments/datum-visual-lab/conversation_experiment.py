"""Compact conversation experiment; persistent state stays in the task service."""
from pathlib import Path
from typing import Literal

from mcp.types import CallToolResult, TextContent
from pydantic import StrictBool, StrictInt

import task_domain
from task_store import TaskStore

URI = 'ui://datum/conversation-experiment'
Scenario = Literal['baseline', 'delivery']


def compact(task: dict) -> dict:
    result = task.get('current_result') or {}
    evidence = result.get('evidence') or {}
    receipt = result.get('receipt') or {}
    requirements = evidence.get('evaluation_machine', {}).get('requirements', [])
    claims = evidence.get('claims', [])
    return {
        'task_id': task['task_id'], 'task_type': task['task_type'], 'revision': task['revision'],
        'evaluation_id': task['evaluations'][-1]['evaluation_id'] if task['evaluations'] else None,
        'receipt_id': receipt.get('run_id'), 'parameters': task['parameters'],
        'status': result.get('conclusion', {}).get('status', 'not evaluated'),
        'reasons': result.get('conclusion', {}).get('reasons', []),
        'scope': result.get('conclusion', {}).get('scope', 'No evaluation recorded.'),
        'unknowns': result.get('unresolved', []),
        'requirements': [{k: r[k] for k in ('part', 'part_name', 'required', 'available_before', 'source')} for r in requirements],
        'claims': [{k: c.get(k) for k in ('id', 'claim', 'source', 'record_source')} for c in claims],
        'review_count': len(task['reviews']),
    }


def _result(task: dict, text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type='text', text=text)], structured_content=compact(task))


def datum_conversation_open(task_id: str) -> CallToolResult:
    """Open one existing synthetic task in a compact MCP App; records a reopen event."""
    store=TaskStore()
    store.record_tool_invocation(task_id, 'datum_conversation_open', 'agent')
    return _result(store.get(task_id, reopen=True, initiator='agent'), 'Synthetic task view; no approval or ERP action.')


def datum_conversation_refresh(task_id: str) -> CallToolResult:
    """App-only: fetch the current authoritative state of this task."""
    store=TaskStore()
    store.record_tool_invocation(task_id, 'datum_conversation_refresh', 'human')
    return _result(store.get(task_id), 'Current synthetic task state.')


def _update(task_id: str, strategy: Scenario, allow_substitutes: bool,
            expected_revision: int, initiator: str, tool: str) -> dict:
    store=TaskStore()
    store.record_tool_invocation(task_id, tool, initiator)
    task=store.get(task_id)
    if task['task_type'] != 'repair_investigation':
        raise ValueError('Scenario changes require a repair investigation')
    params={'machine_id': task['parameters']['machine_id'], 'strategy': strategy,
            'allow_substitutes': allow_substitutes}
    data=task_domain.evaluate_task('repair_investigation', params)
    # The check and write occur under the store's same SQLite transaction.
    return store.evaluate(task_id, params, data, initiator, expected_revision=expected_revision)


def datum_conversation_evaluate(task_id: str, strategy: Scenario, allow_substitutes: StrictBool,
                                expected_revision: StrictInt) -> CallToolResult:
    """App-only: evaluate a synthetic scenario, rejecting stale view revisions."""
    try:
        return _result(_update(task_id, strategy, allow_substitutes, expected_revision, 'human', 'datum_conversation_evaluate'),
                       'Synthetic evaluation saved; not operational approval.')
    except ValueError as exc:
        return CallToolResult(content=[TextContent(type='text', text=str(exc))], is_error=True)


def datum_conversation_update(task_id: str, strategy: Scenario, allow_substitutes: StrictBool,
                              expected_revision: StrictInt) -> CallToolResult:
    """Agent: update the existing task using its current revision; reject stale edits."""
    try:
        return _result(_update(task_id, strategy, allow_substitutes, expected_revision, 'agent', 'datum_conversation_update'),
                       'Synthetic task updated; hypothetical scenario is not an ERP action.')
    except ValueError as exc:
        return CallToolResult(content=[TextContent(type='text', text=str(exc))], is_error=True)


def register_apps(apps):
    apps.tool(name='datum_conversation_open', resource_uri=URI, description=datum_conversation_open.__doc__)(datum_conversation_open)
    apps.tool(name='datum_conversation_refresh', resource_uri=URI, visibility=['app'], description=datum_conversation_refresh.__doc__)(datum_conversation_refresh)
    apps.tool(name='datum_conversation_evaluate', resource_uri=URI, visibility=['app'], description=datum_conversation_evaluate.__doc__)(datum_conversation_evaluate)
    apps.add_html_resource(URI, Path(__file__).with_name('conversation_view.html').read_text(encoding='utf-8'), title='Datum — compact task', prefers_border=True)


def register_tools(mcp):
    mcp.tool(name='datum_conversation_update', description=datum_conversation_update.__doc__)(datum_conversation_update)
