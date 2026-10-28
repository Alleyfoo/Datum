# Experiment 5: Native Codex conversation test

**Status, 2026-10-28: blocked at connection to the current conversation.** The server has been registered and independently responds over stdio, but this already-running Codex conversation does not know about it. No Datum tool was called by Codex, no Datum UI was rendered, and bidirectional conversation has not been demonstrated. Do not treat the diagnostic client or earlier reference-host experiments as a Codex result.

## Environment and setup

- Windows 11; this is a graphical Codex desktop conversation. The browser integration reports app version `26.1023.50603`; the Windows package version could not be independently obtained because `Get-AppxPackage` returned access denied.
- The desktop-bundled executable reports `codex-cli 0.165.0-alpha.1.2`. The separate `codex` on PATH reports `0.136.0` and could not parse the existing `ultra` reasoning-effort setting. Use the bundled executable for these checks.
- The bundled CLI registered the enabled stdio server `datum-visual-lab-experiment5`, using the project's existing MCP SDK environment and `server.py:mcp`. It points `DATUM_TASK_DB` at the disposable local file `C:\Users\pertt\Babel-Tower\output\experiment5-codex.sqlite`.
- Test setup created **one** system-labelled synthetic repair investigation, `task-fb98220dbaab4c1fba9255096dae51c4`, for `BC-01`, baseline, substitutes disabled. Its initial revision is 1 and receipt is `3F1E688E4C515BC9`. The task was prepared directly by Python, not by a model; initiator labels are unverified. The disposable database contains one task, one evaluation and no reviews. Existing experiment databases were not used.
- `codex mcp get datum-visual-lab-experiment5` confirms the stored configuration, not a live Codex connection. Registration modified the local Codex user configuration and was left in place for a subsequent real conversation test. No feature flags were changed.

## Observations and capability negotiation

1. Before registration, the local user configuration had no Datum server. This conversation's available tool inventory contained no Datum tool. After registration, the inventory still contained none, and both MCP resource and resource-template requests for this server returned `unknown MCP server 'datum-visual-lab-experiment5'`. This establishes that it was unavailable **to this running turn**; it does not establish whether a later turn or restarted client will load it.
2. A separate, non-model diagnostic client launched the exact registered stdio command **outside the Windows sandbox**. It initialized using MCP protocol `2025-11-25`, discovered `datum_task_open`, and listed `ui://datum/task-experiment`. Another bounded initialization probe negotiated `2025-06-18`. These are server diagnostics, not Codex capability negotiation and not a tool invocation or render by Codex.
3. The same startup probe inside this turn's Windows sandbox produced no initialize response within 12 seconds, including after using a writable temporary directory. This is a sandbox-specific observation, not proof of the cause or proof that the desktop's MCP launcher will fail in the same way.
4. `codex features list` for the bundled CLI and its effective CLI configuration reported `enable_mcp_apps` as **under development, false**; `apps` was **stable, true**. These CLI observations do not prove the desktop host's effective flags. The current [Codex source](https://github.com/openai/codex/blob/main/codex-rs/features/src/lib.rs) also identifies `enable_mcp_apps` as under development and disabled by default. Enabling it globally would not by itself prove rendering and was not attempted.
5. The desktop's computer-use inventory exposed a `Codex MCP Apps` side-panel browser with no tabs in this session. Its presence shows a graphical surface exists in the client; it does **not** show that the Datum app was retrieved, that arbitrary local MCP Apps are enabled, or that an app would appear inline in the conversation. A side panel is distinct from an inline message.
6. No Datum app was initialized by the desktop host. Therefore no actual host initialization payload or advertised values for `ui/message`, `ui/update-model-context`, app-only tool calls, teardown or other UI lifecycle events were observed. Their status is **unknown**, not unsupported. No `ui://` resource read by Codex was observed.

The [OpenAI MCP quickstart](https://developers.openai.com/plugins/build/app-quickstart) documents server tools for ChatGPT and Codex and an optional iframe UI in ChatGPT. It does not, by itself, establish that this Codex build supports the requested inline Datum UI. The [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) describes configuring MCP servers; configuration is distinct from a successful connection.

## Results

| Question or check | Result | Evidence and qualification |
| --- | --- | --- |
| Can Codex discover and call Datum tools? | **Untested / blocked** | Configured after this turn began; tool inventory and resource lookup do not expose it to this turn. No Codex invocation occurred. |
| Can Codex display Datum inline in conversation? | **Untested / blocked** | No Codex tool call, resource retrieval or app render. The empty MCP Apps side-panel inventory is not an inline-render test. |
| Can the user operate the UI without a model response? | **Untested** | No UI was mounted. |
| Can the UI pass context to the model? | **Untested** | No host capability negotiation or `ui/update-model-context` call. |
| Can the UI initiate a conversational turn? | **Untested** | No host capability negotiation or `ui/message` call. |
| Can Codex change the task through MCP while the UI remains visible? | **Untested** | Neither Codex connection nor UI was established. |
| Does an existing view persist, refresh, or need reopening? | **Untested** | No view existed in Codex. |
| Does the registered server respond and expose the UI? | **Pass, diagnostic only** | Independent SDK client outside the sandbox initialized, listed the tool and listed the resource; it did not render or exercise the UI. |

No screenshot is supplied: there was no Datum interface to capture, and a screenshot of a generic desktop surface would not demonstrate the requested result.

## Verification and continuation

The first Python unit run failed with 37 errors and one skip because the default Windows sandbox temporary directory denied access. With `TEMP` and `TMP` set to `C:\Users\pertt\Babel-Tower\output\experiment5-temp`, the same discovery run completed: **41 passed, one skipped**. The skipped protocol test requires a separately started, isolated server. Neither run is evidence of a Codex App render.

For the next actual Codex turn, check the available tool inventory and request **“Open the existing BC-01 repair investigation in Datum”**, using the disposable task ID above if required. If the server remains unavailable, investigate whether the current conversation needs to be reloaded or the desktop needs a restart; do not assume either action will fix it. Once connected, record the actual host initialization capabilities and whether it fetches the `ui://` resource before testing the graphical controls. If the app cannot render, stop that path and retain the actual limitation. Do not use the separate Python diagnostic as a substitute for the requested conversation test.

The server registration can be inspected or removed with the desktop-bundled `codex mcp get datum-visual-lab-experiment5` or `codex mcp remove datum-visual-lab-experiment5`. The disposable database is under `output/` and is not committed. The experiment used no remote MCP service, ERP writes, production data changes, or GitHub push. Official documentation was consulted online.
