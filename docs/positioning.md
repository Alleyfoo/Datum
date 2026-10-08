# Positioning

This system sits beside the ERP, not in place of it. The ERP is not yet known; until a real
connection exists, the stock figures come from an Excel export that other software
produces, and this system reads that export. The ERP is the system of record and does the
ordinary work. This system takes the work the ERP's rules cannot settle, records it as a
case, and keeps it open until a person decides. It does not take work away from people; it
gives them the facts and the reasoning for the hard cases.

## The escalation ladder

Each piece of work starts at the lowest level that can handle it. A level escalates only
when it cannot resolve the item, and it never overwrites the output of a lower level. It
adds to the case.

1. **Deterministic cleaning.** Rules and patterns: format checks, unit conversion, known
   aliases, product-name normalisation with regular expressions. This handles the bulk.
   No model is involved, and every result is reproducible.
2. **Classical ML.** Scores for what rules cannot express: anomaly scores on quantities,
   match confidence for product names that no pattern or alias covers, and the demand
   pattern class per part (the forecasting groups). Output is a score with its inputs, not
   a decision. Low confidence goes up.
3. **Ticket.** Anything unresolved or flagged becomes a case, with its evidence attached:
   source row, the rule that failed, the score, and the question left open.
4. **LLM consultant.** Works the case with the tools. Asks for missing facts, explains,
   and proposes options with their evidence. It does not decide facts and does not approve.
5. **Human.** Decides anything that changes data, allocates stock, or leaves the company.
   A case the consultant cannot close goes here with what is still unknown listed.

Every escalation records why: the failed rule, the score, or the open question.

**Example.** An export contains "Screw flight 400 mm SS". A pattern maps it to SP-1601
(name and dimension). "Screw flite 40 cm" has no pattern; the match score is below the
threshold, so it becomes a case. The consultant lays out the candidates and their evidence;
a data owner confirms the new alias. Next time the alias is found by rule, not by a case.

## What belongs where

| Work | Handled by |
|---|---|
| Ordinary orders, stock postings, reorder parameters, pricing | ERP, unchanged |
| Format and name cleaning, known aliases | Rules (level 1) |
| Unusual quantities, unmatched names, demand classes | Classical ML scores (level 2) |
| Competing claims on stock, stopped machines with conflicting allocation, unknown file formats, parameters that keep producing exceptions | Cases (levels 3 to 5) |

## Exception types (initial list, to be agreed)

Each type has an owner, the evidence it needs, and the decision a person makes.

- **Competing claim:** two customers need the same stock. Owner: service. Decision: who
  gets it.
- **Unusual order:** a quantity far from the customer's or part's usual. Owner: service or
  analyst. Decision: accept, split or query.
- **Unmatched product:** a name no rule or score can map. Owner: data owner. Decision:
  confirm the alias.
- **Changed format:** an incoming file no longer matches its declared format. Owner: data
  owner. Decision: accept the new format or refuse the file.
- **Policy signal:** the same part keeps producing the same exception. Owner: analyst,
  for the ERP owner. Decision: propose a change to the ERP parameter.

## Measures

The product measures the quality of exception handling, not hours saved:

- share of exceptions that reach a decision with complete evidence;
- time from exception to decision;
- decisions reopened or reversed later;
- how often the person had to search across systems for the facts.

Fill rate and emergency orders stay as outcomes to watch, not as the product's own targets.

## Boundary

- Read-only access to the ERP: extracts or views. No write-back. Until the ERP is known,
  the interface is the periodic Excel export.
- A person executes the decision in the ERP and records it in the case with the ERP
  document IDs, so the two systems can be matched.
- The share of exceptions in real data is the first thing to measure. If it is small, the
  value is small, and the pilot should say so early.
