# Research: the import before the trial and the create-schema gate

The research pass asked for in [build-plan.md](../build-plan.md) section 5. It reads the
sibling repositories and the lab's evidence; it writes no code and changes no decision. Where
the evidence does not settle a question the answer says **open** and names what would settle
it. The decision list at the end is a set of proposals for the owner.

Sources were read at these commits. They are frozen and were only read.

| Short name | Repository | Commit |
|---|---|---|
| messy-data | `C:\Users\pertt\Desktop\cowork\mcp-messy-data` | `3e9a0925da4a445457ddaa2a2cb1a7c7cec3b766` |
| lab | `C:\Users\pertt\Predictive-Spare-Parts-Lab` | `fa3836f68242fc2ce200f78e66374d1e673edb44` |
| Subroutine | the `subroutine` plugin's skill, `~\.claude\plugins\cache\subroutine\subroutine\0.9.13\skills\subroutine\SKILL.md` | plugin version 0.9.13 |

Subroutine is not a sibling repository. It is read only for question 5, because the owner chose
its ticket model (build-plan G10).

## 1. Which header drifts happen in real supplier files, and how often?

**What the evidence contains.** One real supplier workbook: messy-data's `messy-data.xlsx`
(Nomla furniture, three sheets). There is no second real delivery of the same file kind in
either repository. The "second delivery" in messy-data (`showcase/nomla_delivery_s1.xlsx`) is a
26-product package cut from the pilot file. Every drift variant in both repositories is a
constructed fixture. All lab workbooks are synthetic and marked TEST ONLY.

**Observed in the one real workbook:**

| Drift | Seen | Source |
|---|---|---|
| Multiple header rows | yes: the target sheet `Täydennetyt tiedot` has a five-row header stack (group, label, type, note, code); the detector found three equally good header rows and chose none | messy-data `docs/F1-F2-RECONNAISSANCE.md` lines 24–42; `docs/EVALUATION.md` lines 54–58 |
| Duplicate header labels | yes: `ASSEMBLY INSTRUCTIONS` six times and `FUNCTIONS AND DETAILS` repeated, on the data sheet | messy-data `docs/F1-F2-RECONNAISSANCE.md` lines 40–42 and 52–53; `docs/EVALUATION.md` lines 60–64 |
| Merged cells and preamble rows | yes, read by the pipeline; the documents do not say on which sheet or how many | messy-data `docs/PILOT-RECAP.md` lines 40–41 |
| Mixed-language labels | yes: `Numer paczki [Package number]` | messy-data `docs/F1-F2-RECONNAISSANCE.md` lines 18–20 |
| Renamed, added, removed or reordered columns between deliveries | **not observable**: no repeat delivery exists | — |

**Constructed only (no frequency meaning):** two columns swapped, a column inserted, a sheet
renamed, a preamble row added, every label prefixed or upper-cased (messy-data
`showcase/fixtures/fixtures.manifest.json` lines 2–13; `docs/S1-CASE-RECOGNITION.md` lines
106–114); one column renamed, `quantity` to `amount_requested` (lab
`tests/fixtures/source_contract/README.md` line 9; `evidence/source_contract_v1/refusal_cases.md`
line 10).

**Answer.** The real evidence shows multi-row headers, duplicate labels, merged cells and
preamble rows inside one file. How often renames, additions, removals and reorders happen
between deliveries is **open**: the evidence has one real file and no repeat delivery. It is
settled by a run of real deliveries of one file kind (for example ten weekly exports from one
source), each passed through the trial, counting the structural differences by type.

## 2. What minimum header declaration tells one file kind from another, without values?

**messy-data's case signature** (`docs/S1-CASE-RECOGNITION.md` lines 24–73): the sheet name, the
header layout (header rows and label row), the identifier column's label at its position, and
the label of every load-bearing column at its position. Labels are compared after whitespace
normalisation; nothing else is fuzzy. MATCHED when all hold; DRIFT when the identifier label is
present and at least half the load-bearing labels appear somewhere; UNKNOWN otherwise. In its
controls this separated a renamed copy of the same file (MATCHED), moved and inserted columns
(DRIFT), another sheet of the same workbook (UNKNOWN, 0 of 54 labels) and the same products under
another table's header (UNKNOWN, 2 of 54 labels). File name, path, hash, row count and values
are excluded on purpose (lines 53–58).

**The lab's source definition** (`docs/source_owner_contract.md` line 18; `desk/source_contract.py`
lines 242–253): exact sheet names, exact header names in exact order, one optional trailing
column, and an identity block (provider, system, type) carried inside the file. "No header
similarity, positional fallback or guessed synonym."

**Answer.** In the evidence, the sheet name, the header row and the header names at their
positions were enough to tell the kinds apart; neither source needed values or types for
recognition. Types
matter for the value check, not for recognition. Two points are **open**:

- whether whitespace inside a header counts (messy-data normalises it, the lab does not); settled
  by an owner decision;
- whether names and order are enough when two kinds from one company share their headers (two
  exports from the same ERP); settled by a real second file kind from the demo company.

## 3. How are formula cells and cached values handled when software produces the file?

**messy-data** reads the sheet twice, once for cached values and once for formulas
(`src/mcpdd/staging.py` lines 63–124). A formula with a cached value is staged as that value with
the value's own type code, and the fact that it was a formula is not kept. Only a formula with no
cached value is staged as its formula text with code `f` (`src/mcpdd/cells.py` lines 8–21;
`docs/F4.2-EXTRACTION.md` lines 29–31), and is then read as an empty result
(`docs/F4.2D-INTERPRETATION.md` lines 200–201). Its one formula workbook, `answers.xlsx`, is
described as hand-built (`docs/PILOT-RECAP.md` line 31) and holds both calculated formulas and
product rows with uncached formulas (`docs/F4.2-EXTRACTION.md` lines 452–457).

**The lab** refuses any workbook that contains a formula cell (`desk/source_contract.py` lines
159–160; `docs/source_owner_contract.md` lines 101–106).

**Answer.** The two sources disagree: messy-data trusts the cached value and loses the formula
marker; the lab refuses formulas outright. Neither repository holds a software-produced export
(an ERP stock export) with formulas, so how such files carry formulas is **open**. It is settled
by inspecting the first real stock export (P17) for formula cells and cached values, and by an
owner decision on whether a cached value may be accepted as a value. The build brief already
fixes staging: a formula cell keeps code `f`, its cached value and its formula text, so either
decision can be applied later without re-reading the file differently.

## 4. What must the trial report per cell for a person to decide in under a minute?

**messy-data's per-cell mapping result** (`docs/F4.1-MAPPING-EXECUTION.md` lines 47–71): source row
and row id, source columns, source value and its shape, target value, rule chain, operations,
status and reason, with a status for an empty source cell so absence is not hidden. **Its
question document** (`docs/S1-QUESTION-DOCUMENT.md` lines 25–50 and 77–85): for a structural
change, each column's expected label, found label and where the expected label is now, whether
the values followed the label, and one question per change that one answer resolves; known
holds are not asked again. Its decision items always have the same shape: observed, declared,
conflict, question, options, consequences, still unknown, evidence (`docs/ARCHITECTURE.md` lines
239–245).

**The lab's validation report** (`docs/source_owner_contract.md` lines 92–99;
`evidence/source_contract_v1/refusal_cases.md` lines 8–12): row numbers, stable record ids, every
reason code per row, warnings, and the owner action needed.

**Answer.** Per cell the evidence points to: sheet, source row, column id and header, the cell's
raw text and type code, the rule it was checked against, the status and a reason code; then one
statement per kind of failure with the number of rows affected (also asked by
[intake.md](../intake.md)). The time target is **open**: neither repository measured how long a
person needs. messy-data states it as design intent ("answerable in seconds",
`docs/SHOWCASE-DEMO.md` lines 72–73; "30 seconds" as an estimate, `docs/F3.5-DECISION-PACK.md`
line 273), and the lab records that no timed study was run
(`evidence/streamlit_demo_v1/conclusion.md` line 14). It is settled by timing a person on recorded
trial tickets, for example the C25 fixtures and a value-problem variant.

## 5. How does a lease on a ticket behave when its holder stops working?

**The lab** (`desk/cases.py` lines 460–487; `docs/case_resumption_contract.md` lines 157–180;
`evidence/case_resumption_v1/conclusion.md` line 19): a claim has no timeout and survives a
restart. Only the holder releases it. An abandoned claim is freed by a human operator with a
local force-release that records the previous holder, the operator and the reason. No tool can
expire someone else's claim. Writes need the holder's current claim, and a closed case is read
only.

**Subroutine** (SKILL.md, sections on claiming): a claim is a lease that expires by itself.
Every write by the holder (an edit, a status change, a comment) extends it, so a worker who
stops stops renewing. Finishing hands the claim back; an explicit release exists for putting
work down unfinished. Anyone can see who holds an item and until when, and an expired claim can
be taken.

**Answer.** The sources disagree, and the owner has chosen Subroutine's model (build-plan G10):
when the holder stops, the lease runs out, the ticket can be claimed again, and nothing the
holder wrote is lost, because comments and the journal are append-only. Two points are **open**:
the length of the lease (neither source states one), settled by the owner after real use; and
whether a holder whose lease ran out may write without claiming again (not stated in either
source).

## Decision list for the owner

Nothing below is decided. Each line is a proposal with the build's current behaviour, so the
owner can confirm or change it.

| # | Proposal | What the build does meanwhile |
|---|---|---|
| 1 | Measure drift on real deliveries before adding any tolerance (Q1) | Every header difference is a structural change; zero refusals stays the rule |
| 2 | A file kind is declared by sheet name, header row and the ordered, exact header names with their types (Q2) | Headers are compared exactly, whitespace included, following the lab |
| 3 | A formula cell is refused by the trial until the owner decides whether a cached value may count (Q3) | Staging keeps code `f`, the cached value and the formula text; the trial refuses the cell with `formula_cell` |
| 4 | The trial reports per cell: sheet, row, column, header, text, type code, rule, status, reason; grouped per failure kind with row counts (Q4) | Implemented that way; the one-minute target is unmeasured |
| 5 | Leases expire after a set term; writes by the holder renew them; finishing releases them; an expired holder must claim again (Q5) | Placeholder term of 30 minutes, not tuned |
