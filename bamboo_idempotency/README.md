# bamboo_idempotency

A server-side dedup key, so a mobile client that queued a create offline can
retry it without filing the record twice.

## The problem

A client that saves work offline cannot tell these two apart:

- the server never received my `create`;
- the server committed it and the answer was lost on the way back.

Both look identical from the device: a timeout. Without a dedup key the client
has only bad options — refuse offline creates for anything that matters, or
search for the record afterwards and hope exactly one thing matches. The search
is a *probe*: a check followed by a create, with a window in between that two
devices, or one device retrying, can both walk through.

A `UNIQUE` constraint removes the guesswork. The second attempt cannot insert,
so it reads back the first one's id instead.

## What it does

- Adds `bamboo_uuid` to **every** storable model (`_inherit = 'base'`): a native
  PostgreSQL `uuid` column, nullable, with a **partial** unique index
  (`WHERE bamboo_uuid IS NOT NULL`).
- Sets the column default to `uuidv7()` on PostgreSQL 18+, so records created
  any other way — the web UI, another addon, an import — also get a key.
- Adds `bamboo_create_idempotent(vals, uuid)` and `bamboo_find_by_uuid(uuid)` to
  every model.
- Declares an abstract `bamboo.idempotency` model purely as a marker, so a
  client can detect the addon by probing `ir.model` (which it can read) instead
  of `ir.module.module` (which it cannot).

```python
env['res.partner'].bamboo_create_idempotent({'name': 'Acme'}, uuid)
# -> {'id': 42, 'created': True}
env['res.partner'].bamboo_create_idempotent({'name': 'Acme'}, uuid)
# -> {'id': 42, 'created': False}   # same record; nothing changed
```

## Decisions worth knowing before you change something

**Every model, not a list.** A key that covers only the models somebody
remembered to enumerate is a deny-list: silent about the one nobody thought of,
and failing open. The cost is one nullable column and one partial index per
table — on a fresh Odoo 19, 103 columns and 74 indexes. The 29-table gap is
`TransientModel`s: they inherit the column from `base` but get no index, and
`bamboo_create_idempotent` **refuses** on them rather than returning something
that looks like a guarantee and is not.

**The index is partial.** Every row that predates the install has a null key,
and on a real database there can be millions. Excluding them keeps the index
proportional to the records clients actually created.

**The `uuidv7()` default is attached with `ALTER COLUMN`, never `ADD COLUMN`.**
PostgreSQL only takes the O(1) path for a *non-volatile* default; attaching a
volatile one while adding the column rewrites the whole table under an
`ACCESS EXCLUSIVE` lock. On `mail.message` or `ir.attachment` that is an outage,
not a migration.

**The lookup in `bamboo_create_idempotent` is the fast path, not the mechanism.**
Two devices draining one queue both pass the lookup and race to the insert. The
unique index settles it: the loser catches `UniqueViolation` inside a savepoint
and reads back the winner's id. Remove the index and this degrades to a probe
while still looking like a guarantee — which is exactly the failure mode the
addon exists to remove.

**UUIDv7, never v4.** Time-ordered keys keep the index appends local instead of
scattering them across the whole B-tree. Clients mint their own v7; the server
default matches.

## Requirements

PostgreSQL 18+ for `uuidv7()`. On older versions the column simply has no
default: records made outside the app carry no key, and idempotent create still
works exactly as designed, because the key that matters comes from the client.

## Install

```bash
odoo -d <db> -i bamboo_idempotency --stop-after-init
```

Expect DDL across every table. On a large database this is minutes, and the
post-install hook logs what it created so a quiet install is not mistaken for a
hung one.
