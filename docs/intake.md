# Intake: how a file becomes data

Everything about how an arriving file is preserved, checked, decided and admitted. The
board of what is built and what is still open is in [plan.md](plan.md); the item list is in
[backlog.md](backlog.md).

## The import definition

The reference for how imports work is `mcp-messy-data` (`C:\Users\pertt\Desktop\cowork\mcp-messy-data`),
built on the sequence `Preserve → Reveal → Define → Map → Validate → Publish`. Its
`docs/DOCTRINE.md` and `docs/ARCHITECTURE.md` are the rules this plan inherits. (The
`shopflow-furniture` repository covers the shop's own intake and is not the import definition.)

| Stage | What happens | Where it lives here |
|---|---|---|
| **Preserve** | The arrival is copied in, hashed and made read-only. Its id is derived from its content, so registering the same bytes twice does nothing new. | `inbox/` (raw, never edited) |
| **Reveal** | Staging: every cell stored as text with a one-character type code (empty, string, number, bool, date, formula, error). Nothing is trimmed, parsed, coerced, de-duplicated or renamed. Staging is never changed by cleaning. Blank and total rows are kept and flagged. Each row keeps its source file, sheet and exact spreadsheet row. Column ids are mechanical; source headers are data, not identifiers. | staging area of the trial |
| **Define** | The schema is the organisation's statement of meaning. It is versioned: a change creates version N+1 and leaves N intact. An agent may propose; only a named human approves, and the system rejects approvals under an agent name. | the create-schema process |
| **Map** | Each source cell gets a result: the target value, its status, the rule chain and the reason. Nothing is written to the record. | the trial's per-row results |
| **Validate** | Checks run on the mapping (for example, counts, required fields, conservation). A failed check stops the run. | the verification in the routing |
| **Publish** | Only approved rules and decisions produce output. Before and after the run, the decision and record tables are compared, and the run must leave them unchanged. | admission, after the person's choice |

**Worked example** (from `F4.1-MAPPING-EXECUTION.md`): a supplier workbook of 1105 rows, mapped
to 41 target fields, gives 45 305 cell results. 14 fields were mapped and 14 of 14 validation
checks passed, with 0 execution errors. The result is a candidate for review, not an approved
import: it stays `DISCOVERED`, nothing is published, and the record is hashed before and after
to prove it.

**Rules to carry over:**

- **Assumptions have scope and a lifecycle** (`OBSERVED → PROVISIONAL → APPROVED`, or
  `REJECTED`, `SUPERSEDED`). A first observation never becomes a permanent rule.
- **Executors are pure and deterministic.** A rule is a small function with exact arithmetic
  (the doctrine uses decimals, so `30.5 × 10` is exactly `305`). The same input gives the same
  output, and the output is reproducible from raw evidence.
- **Reference workbooks are evidence, not truth.** A reference (for example, a hand-built
  comparison file) is registered as `MANUAL_REFERENCE`. A mismatch with it is a finding, not
  an overwrite, and the reference never overrides an approved decision.
- **Preview before apply.** A rule is previewed (for example, 16 matches, 1089 empty source
  cells, 0 differences) before it is run.
- **Roundtable.** Ambiguous meanings are queued as decisions for a person. Each decision
  becomes a rule once it is approved, and replay from immutable evidence shows its effect.
- **The system becomes more deterministic as knowledge accumulates,** not more dependent on
  repeated model work.

**What this changes.** The trial in the routing is the Reveal and Map stages. It must not
coerce or trim, and its results must be per cell, not a single pass/fail. The create-schema
gate is the Define stage, with its versioning and named approver. The arriving file's record
(hash, source id, rows) is the Preserve stage. Traceability comes from the per-row provenance,
not a later addition.

## Modules

Every processing step is a module, and the core does not know what any module does. A
module declares:

- **Input:** what it reads (a file in `inbox/`, a scanned page, a table).
- **Output and destination:** what it writes and where. An OCR reader, for example, writes
  text with a confidence per field to `customers/<id>/extracts/`.
- **Approver and limitations:** a named person establishes the module, and the known
  limitations are recorded with the approval (the Shop-flow pattern).
- **Failures:** a refusal becomes a ticket with the reason.

Adding an OCR reader means declaring its contract, establishing it, and pointing its output
at the customer folder. Nothing else changes. Its output is new data, so it opens a ticket
for a person to work through before it is admitted.

Collectors (mail, folder watchers) are modules too, with the same contract. They may run on
a schedule and write only to a customer's `inbox/`. They never write to `extracts/`, the
schema or the product data.

## What happens to an arriving file

A file that arrives for a known customer goes into that customer's `inbox/` and opens a
ticket. The file may arrive by a collector or be dragged into the folder by a person. The process is
the same either way: the sender is recorded if it is known, and it is not needed for the trial.

The system does not need to know how the file got there. The schema alone decides whether the data is
valid. A valid file goes to the person for admission. An invalid file opens a ticket, and the reason
is verified before the ticket states it. A folder hook detects the arrival: a trigger module that fires when a file is
created in an `inbox/` folder and does nothing else. On each arrival the hook:

1. waits until the file is complete (a partly written file is not processed);
2. hashes the file and checks the hash against the inbox ledger, so a repeated file is
   linked to its first arrival, not imported twice;
3. opens the ticket;
4. tries the customer's existing schema against the file, in staging, and routes the file
   by the result (below).

Staging writes nothing to `extracts/`, the schema or product data.

**Roles in the ticket.** A worker processes the ticket and may draft a schema or a disposition.
An approver confirms a schema and admits data. The same person may hold both roles, as the owner
decided; the record still names who drafted and who confirmed.

**Routing by the hook's trial.**

| Trial result | What the ticket says | Person's choice |
|---|---|---|
| No schema for this kind of file | "New kind of file: create a schema" | create schema, or drop |
| Schema exists, file fits | "Fits schema X: ready to import" | import, or drop |
| Schema exists, file does not fit | "Does not fit schema X: here is what failed" | create a new schema version, or drop |

"Fits" is strict. Zero refusals is the rule for now; a tolerance is a later decision. The
file must pass the schema with no refusals. Header similarity, a guessed synonym or a
position match is never used to make it fit (the rule from the lab's source-owner contract).
Where a file does not fit, the ticket lists each failed row, field and rule, so the person
sees exactly what changed.

**Verifying a mismatch before the ticket states it.** A failed trial is not reported as
"does not fit" until the hook has checked which kind of failure it is:

1. **Wrong file:** the check is that the headers match the schema of the company the file is filed under.
   When fewer than half of the declared headers are found, the file is not that company's file of
   this kind: it is held, not compared against this customer's schema at all.
2. **Structural change:** a column is renamed, added, removed or reordered. The hook
   checks the header against the schema's declared structure and lists the differences.
3. **Value problem:** the structure matches, but values fail declared rules (type, unit,
   range, duplicate key, unknown reference). The hook counts and lists the failing rows.
4. **Schema defect:** the schema itself rejects rows that the customer's earlier accepted
   files pass. Here the schema is suspect, not the file.

Each check is deterministic and reproducible. The ticket states the verified kind, the
evidence, and the number of rows affected. A failure that cannot be classified is stated as
unclassified, with the raw evidence, and goes to a person without a suggested cause.

When no schema exists, the create-schema process starts. The assistant drafts a schema from
the file, as options with evidence, and the draft waits on the ticket. A person confirms it,
with their name recorded, before it becomes the customer's schema. A new schema version is
handled the same way.

**The create-schema gate is strict.** A draft becomes active only when all of these hold:

- the file it was drafted from passes it with zero refusals, after cleaning (below);
- files the customer already accepted stay accepted under the version they were accepted with.
  A new version is not checked against them, so an amendment never blocks old files. Old files
  are re-checked only when someone asks;
- the draft's rules are listed in full on the ticket, not summarised, so the approver sees
  exactly what they are approving;
- a person with access to the company's folder confirms it, with their name and the reason
  recorded. A confirmer may be the drafter. The approver role confirms and admits.

Nothing is activated by the assistant, by a timeout or by the hook.

## Dispositions

The table above sets which choices the ticket offers. The three dispositions are:

- **Import.** The file's content already fits an approved schema for this customer. The
  content is extracted (through an OCR or parsing module if it is a scan or a PDF) into
  `extracts/`, and each row keeps its source file and location.
- **Create schema.** The file does not fit yet. A new mapping for this customer is drafted
  (by the assistant, from the file, as options with evidence), and a person confirms it with
  their name recorded. Only then does the import run. A new schema for the customer is a
  schema change, so it always has an approver.
- **Drop.** The file is not needed (a duplicate, spam, out of scope). It stays in `inbox/`
  and is marked dropped with the reason. Nothing is deleted.

A PDF starts as unstructured data. Whether it can be imported depends on an extraction module
being established for that kind of document. Until one exists, the only dispositions are
create-schema-later or drop.

The hook does not admit anything. Admission is the person's choice on the ticket, so the hook
can be fully automatic without moving the human gate. The hook never fires on `extracts/`,
`schema/` or `product-data/`, which avoids loops. It runs under its own named identity with
the rights of an inbox writer (see the identity item in [backlog.md](backlog.md)).

## Establishing a customer (separate process)

A file from a company with no folder is never placed in an inbox. It opens an establishment
ticket instead, handled as its own process:

1. The company is identified (name, identifiers, how its files are recognised).
2. A person creates the customer folder and records who approved it and why.
3. Only after that can collectors deliver files for the company.

Until a company is established, its files are held outside every customer folder, and the
held files are listed on the establishment ticket.

## Cleaning: a stage of its own, driven by the schema

Cleaning sits between Reveal and the trial. It is not part of staging, and it is not hidden in
the schema check.

- **Default for every text cell and every header: trim leading and trailing whitespace.** The
  owner decided this for all sources.
- **Other transformations are declared per field in the schema:** case (for example, upper case
  for a part number), format (for example, a date pattern), units. A field with no declaration
  gets only the default.
- **Every change is recorded** against its cell: the original text, the transformed text and the
  rule that made the change. Raw and staging are not changed.
- **The trial runs on cleaned values.** The zero-refusal rule applies after cleaning.
- **Headers are cleaned too.** Whitespace in a header is not significant, so a header with a
  stray space still matches.

Only a declared transformation changes a value. Nothing is guessed.

## Scope notes

- **Email** is not in scope yet. Collectors and mail routing are designed later, when a real
  mailbox exists.
- **Schemas can be amended.** An amendment is a new version. Files accepted under an earlier
  version keep that version (see the gate above).
