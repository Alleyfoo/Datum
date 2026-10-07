# Interaction: how the desk is used

Status: draft for review, 2026-10-08.

There is no separate application. The MCP server *is* the interface: a person talks to an
AI assistant, and the server decides what the person sees. That makes using it simple and
the system behind it complex. This document fixes the experience before more code is
written.

## The flow

The order is always the same, and typing freely is always allowed:

```text
1 SEARCH     "Who or what is this about?"
                 one match  → open it
                 several    → list them; the person picks (never the first one by default)
                 none       → say so; nothing is guessed
2 CONTEXT    a card for what was found, drawn by code: a machine and its parts, a part and its stock
3 QUESTION   only the questions that apply to this thing
                 facts only the person knows are asked, never guessed ("Has the machine stopped?")
4 ANSWER     tools compute, rules decide, the assistant explains
                 every answer has a receipt: tools run · sources · checks · not known · who approves
```

**Who does what in each step:**

| Step | Code | Assistant | Person |
|---|---|---|---|
| Search | finds matches, applies the 0/1/many rule | passes on what the person said | chooses between several matches |
| Context | draws the card | shows it unchanged | reads it |
| Question | offers the questions that apply | — | chooses; supplies facts only they know |
| Answer | computes facts, applies rules, runs checks | explains, drafts the customer reply | approves anything that leaves the company |

## The search rule (0 / 1 / many)

Search covers every kind of thing in the schema. For spare parts that means customers,
sites, machines and parts, by ID, name or description.

- **Exactly one match** opens directly.
- **Several matches** are listed with enough to tell them apart (type, owner, status). The
  person picks. Order never decides, and the assistant does not pick for them.
- **No match** is reported as no match, with what was searched. The person can rephrase.
- An ID typed exactly (`CH-02`, `SP-1601`) is one match by definition.

## Three ways to show it

Clients differ in what they can render. The same flow works in all three tiers, and each
tier is fully usable on its own. The plain-text tier is the baseline every client gets.

| Client can show | Search | Context | Question |
|---|---|---|---|
| Plain text only | the assistant asks "who or what?", calls `search` and shows the numbered matches as returned | a numbered card drawn by code | the person replies with a number or a word |
| Forms (MCP elicitation) | a text field, then a pick-list of the matches | the card as text above a pick-list | form choices, including "Has it stopped?" |
| Apps (MCP Apps: UI inside the chat) | a live search box | cards with status pills | buttons; the answer is posted into the conversation |

In the Apps tier, the search and browse calls go straight from the UI to the server
(app-only tools). The assistant is not involved until a question is asked. That keeps
navigation fast, deterministic and cheap.

## Walkthrough in the plain-text tier

All tool output below comes from the existing desk tools on synthetic data, with today
fixed at Fri 2026-10-02. The status marks, the card and the receipt's tool list are real output; the
search tool and the menu lines ("Ask about", the question letters) are proposed.

A service person types: *"The reclaim screw at the pulp mill has stopped."*

**1. Search: several matches.** If the assistant searches only `screw`:

```text
search "screw": 4 matches. Which one?

 1  machine  SC-01    Screen feed screw          Sawmill customer       ▲
 2  machine  SC-11    Fuel screen screw          Power plant customer   ▲
 3  machine  CH-02    Chip pile reclaim screw    Pulp mill customer     ✖
 4  part     SP-1601  Screw flight section, 400 mm
```

The person answers `3`. Searching with the person's own words, `reclaim screw`, gives one
match and opens it directly.

**2. Context.**

```text
CH-02 Chip pile reclaim screw · screw conveyor · criticality A

 #  PART     DESCRIPTION                        INST   FI   SE  STATUS
 1  SP-1601  Screw flight section, 400 mm ★        4    0    0  ✖  due 2026-11-01
 2  SP-1502  Electric motor 15 kW IE3 ★            1    1    0  ●

★ critical spare   ● covered   ▲ low   ✖ none in stock   ? no parts list

Ask about:  1 a part (number)   S service demand for the whole machine
```

The person answers `1`. The part applies to two questions:

```text
SP-1601 on CH-02:   A availability   L lead time
```

They answer `A`. Availability depends on something only the person knows:

```text
Has CH-02 stopped?   B yes, it is waiting for this part   P no, this is planned service
```

The person answers `B`. The assistant must not infer it from "has stopped" in the first
message. It asks, because the answer changes the rule that applies.

**3. Answer with a receipt.** The assistant explains the facts the tools produced:

```text
CUSTOMER ANSWER
We have no screw flight sections in stock. A purchase order with the full set of 4
arrives at our Finnish warehouse on Thu 2026-10-22; we will deliver from that.

SITUATION
- CH-02 is criticality A and has stopped; it uses 4 x SP-1601.
- Stock is 0 in FI and SE. No approved substitute.
- PO-4718 brings 4 pcs to FI on Thu 2026-10-22. A new order would arrive Mon 2026-11-16 (45 days).

RECOMMENDATION
- Company rule for a breakdown: fastest option, so take PO-4718.
- SC-01 (another customer, FI) is overdue for 3 pcs of the same part: decide who gets PO-4718.

RECEIPT
  asked of the person   machine stopped: yes (breakdown)
  tools run             machine_context · stock_by_warehouse · fastest_supply · incoming_orders ·
                        lead_time · substitutes · conflicts · where_used · due_soon · recommended_plan
  rule applied          breakdown → fastest option
  checks                numbers: all in the facts · other customers named in the customer answer: none
  not known             competing claims on PO-4718 are not modelled: SC-01 is overdue for 3 pcs,
                        also served from FI
  needs approval        the customer answer is queued; a person approves it before it is sent
```

The "not known" line is real. The conflict check covers stock on hand, not incoming orders,
so the rule hands PO-4718 to CH-02 without weighing SC-01. The receipt says so instead of
hiding it. This is the kind of gap an analyst then turns into a case.

## The same steps in the other tiers

- **Forms:**
  - Search is one form with a text field. Several matches come back as a pick-list in a
    second form.
  - The machine card is shown as text, then a pick-list: "Service demand (whole machine)"
    or one of its parts.
  - The question and "Has CH-02 stopped?" are pick-lists too (the existing `open_desk`
    pattern).
- **Apps:**
  - One panel in the chat. A search box at the top, with results updating as the person
    types.
  - Clicking a machine shows its card with status pills. Clicking a part shows the question
    buttons.
  - "Has it stopped?" is two buttons. Asking posts the question into the conversation; the
    assistant's answer and its receipt appear there.
  - The panel stays, so the next question starts from the same context.

## Free text

The person can skip the menu at any point: *"Can we get the screw flights to the pulp mill
before the 20th?"*

- The assistant resolves names with the same `search` tool and the same 0/1/many rule.
- It asks for facts it does not have (stopped or planned).
- It answers with the same receipt.

The menu is a faster path, not a requirement.

## Not specific to spare parts

The flow uses three general ideas:
- **things** that can be searched;
- **context cards** that show a thing and its relations;
- **questions** registered for a kind of thing, each declaring what it must ask the person.

The spare-parts domain supplies customers → machines → parts and three questions. Another
domain supplies its own things and questions; the flow stays the same.

## Open points

- Should search also match open cases and pending approvals ("what is waiting for me")?
- When the person's first message already contains the answer to a person-only fact ("has
  stopped"), may the assistant pre-select it if the person still confirms with one click?
- How much of the receipt is shown by default vs. folded away, per tier.
