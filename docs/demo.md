# Demo

## What the demo shows: one world, several people, one shared record

- **Home:** the domain's overview. For spare parts that is the plant map, with machines
  coloured by spare-part coverage.
- **Role conversations that follow the same entity.** Chat on the left; on the right, the MCP
  tool calls and the shared record they read or write.
  1. **Customer service (built first):** "CH-02 has stopped, the customer needs SP-1601."
     Availability → fastest supply → conflicts → draft reply → checks → approval queue. The
     agent also sees the part's open case.
  2. **Data owner:** this week's Excel export. Recognised; a renamed column is refused; a
     mapping is proposed and confirmed; the import runs. An unusual request (40 against a
     usual 2) opens a case.
  3. **Analyst:** "Is SP-1601 at risk? How long do orders really take?" Actual vs. quoted lead
     time, demand forecast, findings into the case, and a pre-order proposal for a buyer.
- **People decide:** approval queue and proposals.
- **Conversation mode:** recorded replays of real tool runs by default (deterministic,
  hostable). Live runs use Claude through MCP (build-plan section 17); no local model. A section explains
  how to connect the server to an MCP client.
- **Tools per role:** visible in the demo; each role sees only its own tools.

## Steps to a meaningful demo

Each step ends with something a viewer can watch. The demo is meaningful when steps 1 to 5
run from a clean checkout with no live model, from recorded runs.

1. **The company.** Synthetic company with its history, and the schema it is described in.
2. **A call becomes a ticket.** A customer's conveyor stops. The consultant opens the ticket,
   asks "has it stopped?", runs the tools and rules, passes the checks, and the reply waits in
   the approval queue. The person approves; the ticket records who and when.
3. **A file arrives.** This week's stock export is recognised and loaded. A file with a renamed
   column is refused, the refusal sits on its own ticket, and the mapping is confirmed by a
   person before rows load.
4. **An unusual number opens a ticket.** An order of 40 against a usual 2 becomes an analysis
   ticket. The analyst consultant checks lead times and the forecast, records a finding and
   proposes a pre-order for a buyer to approve.
5. **The loop closes.** The service ticket for the same part shows the open analysis ticket.
   The gap from the earlier answer (a competing claim on incoming stock) is now a recorded
   finding, and the next service answer uses it. This is the payoff: one record, several roles.
6. **Live mode.** A local model runs the same consultant role, and the recorded runs are
   refreshed from real sessions.
7. **Connection.** The real server connects to a desktop assistant.
8. **A second domain sketch.** A different kind of data goes through the same schema and ticket
   flow, to test that the core holds.
