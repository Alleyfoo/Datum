# Local MCP Apps experiment — test report

Tested 27 October 2026 on Windows 11, with Python 3.12.14, MCP Python SDK 2.3.0, Node 24.14.1, Chrome and official ext-apps basic-host revision `07cda2513b0b691ac261ac69c856062c9afb2824`. All data is synthetic and all actions read-only. See README for reproducible setup.

## Normal browser

The offline HTML opens with three precomputed Python snapshots and is clearly labelled offline. The automated mocked-host browser test also checks offline rendering, empty live startup, rejection of text-only results, and scenario requests. Offline data changes require `python build.py`; they do not prove MCP connectivity.

## Official MCP Apps reference host

The local host connected to the Python server over Streamable HTTP, read the `ui://datum/visual-lab` resource and rendered it in the host's nested sandbox iframe. Its log showed app initialization and delivery of `structuredContent`. The automated reference-host test called baseline, delivery and quarantine using the app's scenario control. For each, it compared the actual structured payload with a fresh Python evaluation, and checked displayed machine rows and counts. It exercised graph zoom and node selection, displayed two claims and the rejected `1?` quantity, and verified priority allocation of the single bearing in the delivery scenario.

The test temporarily changed the copied `machines.csv` name from `Belt conveyor` to `LIVE TEST conveyor`, then requested baseline through the already loaded app. The new name and changed result appeared without rebuilding HTML. The test restores the original file bytes in `finally`. The name is test-only; see `screenshots/reference-host-changed-record.png`. Screenshots also capture the baseline, graph and quarantine views. The original source CSV hash matched the restored copy.

The official Python MCP client independently listed the tool and HTML resource and called all three scenarios; their ready/blocked/review counts were 3/3/3, 5/1/3 and 3/3/3. The initial CLI server failed browser CORS preflight, captured in `host-initial.png`. The local launcher adds CORS for the reference host's two loopback origins; a different origin was rejected. After the fix, there were no Playwright page errors. Chrome logged one unattributed 404; the response observer did not identify its URL. It is not established to be harmless.

## Actual AI assistant

Not tested. The reference host is a manual test client, not an AI assistant. No assistant compatibility or model tool-selection behavior is claimed.

## Limitations and remaining work

- The table supports search and status filtering, but not sorting. A larger network, charts, timelines, and controls for requesting other contextual information have not been implemented or validated.
- Pan, wheel zoom, keyboard access, narrow windows, memory use, large datasets, and JSON/SVG exports have not received systematic real-host verification. Graphs show a partial per-machine evidence view. Source inspection currently shows a provenance link, not the original CSV row contents.
- The tests compare every overview row and count, plus selected graph, claim and quarantine details, not every value in every view. More complete UI-to-result assertions remain needed.
- Supplier-conflict logic is tailored to the synthetic CP-09 and CF-01 case and is not a general claims-resolution engine. In particular, a CP-09 requirement may cause review for a different shortage, and changing claims alone does not drive the conflict rule. Do not use this demonstration for operational decisions.
- Duplicate machine IDs, duplicate BOM machine/part pairs, duplicate stock IDs and unknown BOM parts are now rejected. Other malformed or large inputs have not been comprehensively validated. The engine's hypothetical delivery depends on specific fixture IDs.
- Host CSP, sandbox sizing, downloads, clipboard and cross-origin policy differ by host. The local CORS launcher is intended for the loopback reference-host experiment, not production deployment.
- No ERP connection, write-back, real reservation, approval, or model-generated business decision is provided.

## Checks

The original six unit tests passed before changes. The working copy has 12 Python tests and they pass; in this sandbox the temporary directory had to be redirected to a writable workspace directory. `tests/test_bridge.cjs` passes in Chrome. `tests/test_reference_host.cjs` passes against the pinned reference host and captures screenshots; it temporarily edits a synthetic fixture and restores it. Run it only with a disposable local copy and no concurrent fixture edits.

The [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx) defines the resource and message lifecycle. The [official basic-host README](https://github.com/modelcontextprotocol/ext-apps/blob/main/examples/basic-host/README.md) describes its host and sandbox. The MCP server serves the application HTML as a resource; no separate application HTML server is needed, although the reference host runs its own local web and sandbox servers.
