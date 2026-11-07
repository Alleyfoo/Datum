# Protected ticket types: governed external execution

**Status:** added on branch `feat/governed-execution-protection` (2026-11-07). Opt-in: nothing changes for a
store in which no type is protected.

## Why

Some tickets stand for work that changes something outside Datum, such as a webshop. For such work, an
approval must be bound to what the approver was shown, used for one execution, and verified. The ticket
must also not end while it is unknown whether the outside change happened.

An execution layer outside Datum can keep that record. Without help from Datum, though, two of its
guarantees can be bypassed through Datum's ordinary calls (measured in Data Assurance's Q0′ experiment,
`research/ops-queue-q0/RESULTS.md`, L1 and L2):

- **Approval bypass:** `queue.approve()` accepts any effect, or none. Called directly, it finishes such a
  ticket without the layer's checks.
- **Unresolved close:** once an executor's lease runs out after a crash, any worker may close the ticket
  while the outcome of the outside change is still unknown. Datum then refuses every claim on the ticket, so
  the interrupted execution can never be reconciled.

## What a protected type is

```python
store.protect("ops.banner_replace", protection, by="anna")   # an approver, once; recorded and permanent
store.attach_protection("ops.banner_replace", protection)    # every later process, before it acts
```

A **protection** is any object with:

| Member | Called | Refuses by |
|---|---|---|
| `name` | Recorded with the type. Attaching a protection with another name is refused. | — |
| `approve(db, item, proposal, approver, attestation)` | In place of an effect, in every `queue.approve` of a ticket of the type, inside the approval's transaction. It returns what an effect returns. | raising `RecordError`, journaled as `approval_refused` |
| `reject(db, item, proposal, approver, reason)` | In place of an effect, in every `queue.reject` | the same, journaled as `rejection_refused` |
| `check_end(db, item, status, actor)` | Whenever a ticket of the type would become `closed` or `finished`, by any path: `close`, `finish`, `queue.approve`, or `update` directly | raising `RecordError`; nothing is written |

## Rules

1. **Opt-in.** Only an approver protects a type: a person, not agent-like, holding the role. The act is a
   journal entry (`type_protected`).
2. **Persistent.** The type and the protection's name are kept in `protected_types`. Triggers refuse any
   update or delete. A protection is never replaced by another name.
3. **Not bypassable through the store's calls.**
   - `queue.approve` and `queue.reject` refuse a caller's `effect` on a protected ticket (`protected_type`).
   - Every end of a protected ticket passes `check_end`, because `update` is the one boundary every status
     change goes through.
4. **Fail closed.** A process that has not attached the type's protection cannot approve, reject, close or
   finish its tickets (`protection_unavailable`). Ordinary tickets are unaffected.
5. **Unchanged otherwise.**
   - Ticket statuses, leases and resume, self-approval by a person holding both roles, the close and finish
     guards, retention and the sweep are all as before.
   - Claims, comments, links and status changes that do not end a ticket are not guarded. So once a lease
     has run out, another worker can still take an interrupted ticket over and reconcile it.

## `blockers(number, *, db=None)`

`blockers()` lists the unfinished tasks that `number` waits on (a closed blocker included), using the same
rule as `ready()`. Given an open transaction's `db`, it answers inside that transaction. A gate can then
check dependencies and claim its work in one commit, instead of reading Datum's tables itself.

## What it does not do

- It does not authenticate anyone. Names remain coordination labels.
- It does not stop code that writes to the SQLite file directly. That is the same boundary as every other
  rule here.
- It does not decide what "unresolved" means. The protection does.
