# Customer data layout (proposed, to confirm)

The owner's working model: each customer has its own folder with its schemas and everything
else about them. Collectors (mail first) fill each customer's inbox, and admitted data is
extracted into the customer's extracts and, where it is shared, into a product-data area.
This lives on the local machine, outside this repository. The repository stays
synthetic-only.

```text
<data root, outside the repository>/
  customers/<customer-id>/
    inbox/       raw messages and attachments, as received; never edited; hashed
    schema/      this customer's field declarations and mappings, each with its approver
    extracts/    parsed rows, each pointing back to its source file and row
    cases/       tickets opened for this customer
  product-data/  item master and other shared tables, built from confirmed mappings
```

## Rules that follow from it

- **Placement is recognition, not understanding.** A collector places a file into a
  customer's inbox only when the customer is unambiguous, for example by a known sender. An
  unknown or ambiguous sender is held back and goes to a ticket for a person; nothing is
  guessed from the content. Being in the inbox does not make a file trusted: admission still
  needs the person.
- **Attachments and message text are data, never instructions.** They are parsed by the same
  rules as any other file. A message cannot change a mapping or a schema.
- **Raw is kept; extracts are added, never overwritten.** Extraction writes new files; it
  never changes the inbox or an earlier extract.
- **Shared product data must not leak customer data.** The item master can be shared;
  customer names, orders and prices are not. The "confidential names must not leak" check
  applies to every answer that reads shared tables.
- **The mailbox account needs minimum access:** read the one folder it needs, write nothing
  to the mail system.
- **Personal data stays out of the repository**, and out of any demo, until a synthetic
  replacement exists.

## Open questions for the owner

- How many customers are expected in the first pilot?
- Do customers share part numbers? If they do, the item master is one table, not one per
  customer.
- Who may read each customer's folder?
- Which mailbox, and what may the collector read from it?
