# -*- coding: utf-8 -*-
{
    'name': "Bamboo Idempotent Offline Create",

    'summary': """
        Server-side dedup key so an offline client can retry a create safely""",

    'description': """
Gives every model a `bamboo_uuid` column with a UNIQUE index, and a
`bamboo_create_idempotent(vals, uuid)` method that returns the existing record
when that uuid has already been used.

Why this exists: a mobile client that queues writes offline cannot tell "the
server never got my create" from "the server committed it and the answer was
lost". Without a dedup key its only safe options are to refuse offline creates
for anything that matters, or to search for the record afterwards and hope the
search is unambiguous. A UNIQUE constraint removes the guesswork: the second
attempt cannot insert, so it reads back the first one's id instead.

Requires PostgreSQL 18 for `uuidv7()` — the server-side default. Clients mint
their own UUIDv7 for queued writes, so the default only covers records created
without one (the web UI, other addons, imports).
    """,

    'author': "dinhduongha@gmail.com",
    'website': "https://github.com/dinhduongha/bamboo-portal",
    'category': 'Technical',
    'version': '19.0.1.0',
    'depends': ['base'],
    'license': 'LGPL-3',
    # Nothing declarative: the marker model is abstract (so it needs no ACL,
    # and appears in ir.model, which is what a client probes) and the schema
    # work happens in Base._auto_init.
    'data': [],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
