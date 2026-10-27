# Datum Visual Lab

This local, read-only experiment shows synthetic spare-parts decisions and their evidence. The Python rules engine validates input, allocates stock and produces the structured result. The HTML visualizes that result; it does not make ERP changes or grant authorisation.

There are two distinct modes:

- **Offline snapshot:** open `datum_visual_lab.html` directly in a browser. It contains three precomputed Python results. Changing a CSV does not change this page until it is rebuilt.
- **MCP tool data:** an MCP Apps host loads `app.template.html` as a `ui://` resource. It starts without embedded scenario results and waits for the host to deliver the `datum_visualize` tool's `structuredContent`. Scenario controls request a fresh result through the host and server. There is no separate application HTML server.

The views include a searchable, status-filtered machine table, an SVG evidence graph with zoom, pan and node inspection, supplier-claim comparison, quarantine details, a decision receipt, and scenario comparisons. JSON receipt and SVG graph export use browser downloads. The table is not sortable. Evidence graphs are partial and are not a full supply-chain model.

## Standalone offline mode

Open `datum_visual_lab.html` in a browser. To regenerate its snapshots after editing synthetic CSV input, run from this folder:

```powershell
python build.py
python -m unittest discover -s tests -v
```

The standalone build and engine use Python's standard library. The page is an offline demonstration, not a live connection to the CSV files.

## Local MCP Apps reference host

This setup uses the official Python SDK and official reference host on the same machine. It was tested with Python 3.11+, Node.js 24.14.1 and npm 11.12.1. In PowerShell, from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp==2.3.0"
.\.venv\Scripts\python.exe run_reference_host.py
```

The last command starts Streamable HTTP on `127.0.0.1:8000/mcp`. It adds CORS only for the local reference host origins on port 8080; the plain SDK CLI's default HTTP endpoint does not add those browser CORS headers. This entry point is for the local experiment, not a deployment configuration.

In a second terminal, clone and start the reference host at the revision used for this experiment:

```powershell
git clone https://github.com/modelcontextprotocol/ext-apps.git
cd ext-apps
git checkout 07cda2513b0b691ac261ac69c856062c9afb2824
npm install
cd examples/basic-host
$env:SERVERS='["http://localhost:8000/mcp"]'
npm run start
```

Open `http://localhost:8080`. Select `datum_visualize`, supply a `scenario` of `baseline`, `delivery`, or `quarantine`, and call it. The reference host serves its own page on port 8080 and its sandbox proxy on port 8081. Consult [TEST_REPORT.md](TEST_REPORT.md) for observed results and limitations; merely loading the standalone HTML does not establish host compatibility.

## Checks

Run the Python engine tests and, with the server running, the MCP protocol probe:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe protocol_probe.py
```

The probe lists tools and resources and calls all three scenarios; it does not render a view. An optional bridge check uses Node and Playwright installed with the reference-host dependencies and a local Chromium browser. Adjust the paths if your checkout or browser differs:

```powershell
$env:NODE_PATH = 'C:\path\to\ext-apps\node_modules'
$env:DATUM_BROWSER = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node tests/test_bridge.cjs
```

The bridge check simulates host messages and verifies the live loading state, data delivery, scenario request and offline snapshot. It does not replace the official-host test.

## Boundaries and data

The synthetic CSVs remain source records, and the engine records their hashes. Conflicting claims remain unresolved; quarantined rows do not become validated stock. Hypothetical scenarios are evaluations of synthetic data, not actual reservations, deliveries or approvals. Capacity, equipment condition, safety checks and real lead times are outside this experiment. Host sandbox rules and capabilities can affect export, sizing and interaction. Actual assistant support must be tested in that assistant.

The [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx) defines the UI resource and message lifecycle. The [official basic-host README](https://github.com/modelcontextprotocol/ext-apps/blob/main/examples/basic-host/README.md) describes its local host and sandbox.

To run the official-host browser check, start both the server and basic-host as above, then in this directory:

```powershell
$env:NODE_PATH = 'C:\path\to\ext-apps\node_modules'
$env:DATUM_BROWSER = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:DATUM_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
node tests/test_reference_host.cjs
```

The test temporarily edits `fixtures/machines.csv` and restores its original bytes. Run it only in a disposable copy without other processes editing the fixtures. It captures screenshots in `screenshots/`. Set `DATUM_HOST` to override the default host URL. If your environment denies writes to the normal temporary directory, set `TEMP` and `TMP` to an existing writable local directory before running the Python tests.

