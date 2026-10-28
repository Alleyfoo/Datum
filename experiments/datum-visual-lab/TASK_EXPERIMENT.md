# Experiment 3 — persistent task investigation

Tested locally on Windows 11 with Python 3.12, MCP Python SDK 2.3.0, the official `ext-apps` basic-host revision `07cda2513b0b691ac261ac69c856062c9afb2824`, and Chrome. Synthetic records only. The reference host negotiated core MCP `2025-11-25`; the view uses MCP Apps `2026-01-26`. The experiment does not connect to an ERP, reserve real stock, authenticate users, or authorize business actions.

## Architecture and boundaries

`datum_engine.py` remains the deterministic spare-parts engine. `task_domain.py` exposes machine, requirements, inventory, alternative evidence, scenario comparison and task evaluation. Each evaluation captures the four CSV byte strings once and uses those same bytes for parsing and SHA-256 hashes. The files are captured sequentially, so concurrent edits can yield a mixed multi-file snapshot. A missing matching claim means **unknown**, not that no alternative exists; `allow_substitutes` is recorded but never applies or approves a substitute. The inherited CP-09/CF-01 conflict rule is fixture-specific and is explicitly disclosed in the result.

`task_store.py` stores task state, append-only evaluation results/receipts, reviews and semantic events in SQLite. `task_experiment.py` binds both model-visible and app-only MCP tools to the same domain and store functions. `task_interface.py` composes a data-only UI description; `task_interface.html` is the one renderer for both task types. The host mediates messages between the renderer and server. An agent recommendation, deterministic rule result, and local human-labelled review are displayed separately. There is no authorized business action in this experiment.

## MCP tools and contracts

Inputs are typed in tool schemas; unknown IDs, incompatible parameter combinations, invalid scenarios and non-boolean substitution flags are rejected. Tool errors are returned through MCP; missing BOM and absent alternative evidence are explicit unknowns. Direct protocol clients can see app-only metadata, so visibility is host routing, not access control. All labels for agent/human initiators are **unverified claims**. A real system must enforce identity and permissions server-side.

| Tool | Parameters and result | Visibility and effect |
| --- | --- | --- |
| `datum_list_machines`, `datum_get_machine` | No parameters / `machine_id: string`; return synthetic machine data and source reference. | Model-visible; read-only. |
| `datum_get_required_parts` | `machine_id: string`; returns requirements or `known: false` for missing BOM. | Model-visible; read-only. |
| `datum_check_inventory` | `part_ids: string[]`; returns source stock, before priority allocation. | Model-visible; read-only. |
| `datum_find_alternatives` | `part_id: string`; returns relevant claim evidence or unknown, never a compatibility approval. | Model-visible; read-only. |
| `datum_compare_strategies` | `machine_id: string`, `allow_substitutes: boolean`; returns baseline and hypothetical-delivery evaluations against one capture. | Model-visible; read-only. |
| `datum_task_create` | `task_type: repair_investigation` plus `machine_id`, `strategy: baseline|delivery`, `allow_substitutes: boolean`, or `task_type: supplier_conflict_review` plus `part_id`. Optional `recommendation: string` and `next_steps: string[]` are unverified. | Model-visible; creates local task state after validation. |
| `datum_task_evaluate` | `task_id` and the explicit parameters appropriate to its task type; appends a deterministic result and receipt. | Model-visible; writes local evaluation history only. |
| `datum_task_get` | `task_id`; returns parameters, current result, all evaluations, reviews and events. | Model-visible; records a local tool event. |
| `datum_task_open` | `task_id`, optional `requested_components: string[]`; returns a validated interface description and records a reopen event. | Model-visible, UI-linked; writes local events. |
| `datum_task_ui_evaluate` | `task_id` and the same typed task parameters; calls the same domain/store implementation and returns a refreshed description. | App-only; writes local evaluation history. |
| `datum_task_ui_review` | `task_id`, displayed `evaluation_id`, `decision: reviewed|needs_more_information|disagree`, `note: string`; records a local review. | App-only; local write, not authorization. Rejects an evaluation ID if a newer evaluation was recorded. |

The server records a tool-invoked event for task-bound calls; independent discovery/read-only domain calls have no task ID and are not included in a task's event history. Requests rejected by MCP schema validation before entering application code are not recorded as task events.

## Dynamic interface contract

The description is `schema_version: datum-task-ui-v1`, task identifier and type, title, an ordered `components` list and a `data` map keyed by each component's `source`. The finite renderer vocabulary is `parameter_form`, `data_table`, `evidence_graph`, `status_summary` and `decision_receipt`. Forms contain typed fields, values/options and an action descriptor; the renderer only accepts the two allowed app-only tool names. Tables define columns and rows; graphs define nodes and edges; status and receipt components define label/value items and notes. JavaScript inserts text as text, and no model-supplied JavaScript executes.

Python chooses component order and data for each task. Repair includes machine/strategy/substitution controls, a graph, requirements and alternative-evidence tables, status and receipt; supplier conflict review uses its part selector and claim/provenance table with status and receipt. Both use the same HTML and renderer functions, without task-specific JavaScript branches. `requested_components` may filter/order supported types; unsupported, duplicate or unavailable types are rejected. Current fixture data supplies selector choices; recorded conclusions and evidence come from saved results. If current inputs are missing or invalid, the renderer retains the old evidence, labels the problem and disables reevaluation.

## Task lifecycle, handoff and evidence

1. An agent-facing client discovers tools and creates a local task with explicit parameters, optional recommendation and proposed next steps. An evaluation calls the deterministic domain rules and appends a result.
2. `datum_task_open` returns the server-composed view. The host loads the single `ui://datum/task-experiment` HTML resource and sends the result to its sandboxed iframe.
3. A person can change parameters, request another evaluation, inspect the evidence and record a review through app-only calls. The app requires a host advertising server-tool support. No model turn is needed for these actions. A review is tied to the displayed evaluation; a stale review is rejected.
4. A later MCP call can recover the changed state and all earlier receipts. Closing the browser or creating a new MCP connection does not erase the SQLite records. Reopening records an event.

A receipt links result and parameters to rule versions, input signature, hashes of source bytes and unresolved assumptions. For repair, the input signature hashes normalized evaluation input; the supplier review signature hashes the source-hash mapping. Evaluation history retains full result and evidence payloads, not only the latest result. It retains source version hashes, not a durable archive of all original CSV bytes. Events record task creation, task-tool invocation, parameter validation/change, source hashes accessed, rule application, completion, review and reopening. These events are execution history; the evidence-bearing receipt is a distinct object. There is no tamper-evident audit, concurrency-safe external source snapshot or verified identity.

## Results

### Verified Python behavior

All 37 Python unittest cases passed with the opt-in protocol case enabled against an isolated local server. Without the opt-in environment variables, that case is skipped. Tests cover source-byte/hash consistency, unknown inputs, both task types, deterministic scenarios, no inferred substitution, persistent receipts and review history, stale review rejection and serialized concurrent evaluations. A captured-file test verifies fixture bytes do not change. Saved evidence remains viewable if present-day inputs cannot be loaded.

### Scripted MCP protocol behavior

The scripted harness discovered the tools and typed schemas, called the functions for BC-01, evaluated baseline and hypothetical delivery, created a task, compared agent-facing and app-only results for identical parameters and source hashes, recorded a changed evaluation and review, rejected invalid inputs and stale reviews, and recovered state through a new connection. It checked source hashes before and after. Direct app-only calls in this harness test the server and protocol, not host access enforcement. This is **not an autonomous AI-agent run**.

### Reference-host rendering

An automated Chrome test created an agent-labelled task over MCP, opened the resource in the official host, and drove the GUI. The same parameters and unchanged source snapshot produced equal complete business results for agent-facing and GUI calls. It changed the scenario and substitution flag, requested reevaluation, recorded a local human-labelled review, retrieved it through MCP, closed and reopened the app, and verified the evaluation history and parameters. A second task displayed conflicting supplier claims through the same renderer with a different Python composition. The last successful host run preceded a receipt-label wording change and a new graph-node click assertion; those final changes were not rerun in the host because automatic approval review rejected the local review mutation. A separate nonmutating Chrome test with a mocked host bridge passed graph-node source inspection and unavailable-source disabling; it is browser-only, not reference-host evidence. Automation operated the human controls; this is not a test with a real human. No extra LLM call was used for these UI operations. Screenshots: [repair](screenshots/task-repair.png), [evidence graph](screenshots/task-repair-graph.png), [review](screenshots/task-human-review.png), [supplier claims](screenshots/task-supplier-conflict.png).

### Actual local AI-agent behavior

Two actual, local-only Ollama model runs were separate from the scripted test. The bounded harness sent the model the discovered, model-visible MCP schemas; it did not choose the model's calls or arguments, and did not render the interface. The [Ollama tool-calling API](https://docs.ollama.com/capabilities/tool-calling) mediated the model requests. No cloud model or service was used.

- **Llama 3.1 8B:** The model chose seven calls. Machine lookup and strategy comparisons returned results, but it used invalid arguments for alternative lookup, task creation, opening and retrieval. It did not create a task. Its final response inconsistently claimed task creation and overstated the synthetic delivery result as actual repairability. This run preceded the strict-boolean correction: its string `"False"` was coerced by the SDK in a comparison call. That defect was subsequently fixed and regression-tested. See the [full Llama transcript](evidence/llama3.1-agent-run.json).
- **Qwen 3.5 9B:** On the corrected server the model autonomously selected nine successful calls: machine, BOM, inventory, alternative evidence for each required part, strategy comparison, task creation, evaluation and interface request. It created task `task-505c37db5e974f53a60a0003871bac6c` with a baseline result and uncertainty. It did not populate the task recommendation or next steps, and did not summarize the hypothetical-delivery comparison despite calling it. Its final phrase that the machine “cannot be repaired” overstated a limited synthetic stock-readiness result, even though it also stated the limited scope. Its answer is not an authorization or proof of operational suitability. See the [full Qwen transcript](evidence/qwen3.5-agent-run.json).

The reference-host test completed the handoff on a **scripted agent-labelled task**, including the recommendation and next steps. A separate optional test was prepared for the actual Qwen-created task, but its reevaluation and review were not performed: automatic approval review rejected the local SQLite mutation twice, citing an earlier read-only constraint, even though the current request explicitly permits local synthetic review updates and the database was disposable. Therefore no model-created task was modified through the GUI and no real-model retrieval of that modified state was established. The task's missing recommendation and next steps are an additional gap. `tests/test_model_handoff.cjs` is available for a specifically authorized follow-up; it simulates the person with Playwright and does not establish authenticated human identity.

## Reproduction

Follow the Python SDK and pinned basic-host setup in [README.md](README.md). Use a disposable SQLite path and start the server from this directory:

```powershell
$env:DATUM_TASK_DB = (Join-Path (Get-Location) 'task-test.sqlite')
.\.venv\Scripts\python.exe run_reference_host.py
```

Start the official basic-host in a second terminal as in the README. In another terminal, with the same server running, run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:DATUM_HOST = 'http://127.0.0.1:8000/mcp'
$env:DATUM_TASK_TEST_DATABASE_ISOLATED = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_task_protocol.py -v
$env:NODE_PATH = 'C:\path\to\ext-apps\node_modules'
$env:DATUM_BROWSER = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:DATUM_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$env:DATUM_HOST = 'http://localhost:8080/'
node tests/test_task_reference_host.cjs
node tests/test_task_renderer_browser.cjs
```

These checks create synthetic tasks in the server's database. Use a disposable DB, not a store with valued data. An optional local model run uses `task_local_agent.py`; it discovers MCP tool schemas and allows only loopback endpoints and locally installed non-cloud models. It does not download a model or render an MCP App. See its `--help`; the bounded harness follows the [Ollama tool-calling API](https://docs.ollama.com/capabilities/tool-calling). Test results depend on the selected model and machine.

## Limitations and unanswered questions

- The prototype has no authentication, verified human identity, ERP integration, write-back, real authorization or operational approval. App-only visibility cannot enforce these.
- Full raw source files are not archived with each receipt; hashes and result evidence identify versions but cannot recover lost files. Capturing multiple files is not atomic. Task-event logging does not cover pre-validation failures or unbound read-only calls.
- Alternatives are not established; strategy `delivery` is hypothetical. A true substitution cannot be evaluated without a verified mapping and policy. Machine condition, labor, safety and supplier commitments remain unknown.
- The reference-host run is one host/browser combination; accessibility, larger datasets, other host permissions, deployment and real multi-user operation are not established. A generic console 404 was observed without an identified cause; no page errors were observed.
- The renderer covers a small fixed vocabulary, not arbitrary business applications. Server-described content and component selection require validation, and model output remains untrusted. A local review is not proof of human identity.
