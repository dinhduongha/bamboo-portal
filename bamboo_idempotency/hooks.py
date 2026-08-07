# -*- coding: utf-8 -*-
"""Install-time reporting. The schema work itself happens in `Base._auto_init`."""

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Say what just happened, because it is not a small thing.

    Installing this addon adds a column and a partial unique index to every
    storable table in the database. That is deliberate — a dedup key that covers
    only the models somebody remembered to list is the deny-list problem again —
    but on a database with a long history it is minutes of DDL, and an operator
    who was not told will assume the install hung.
    """
    cr = env.cr
    cr.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE column_name = 'bamboo_uuid' AND table_schema = current_schema()"
    )
    columns = cr.fetchone()[0]
    cr.execute(
        "SELECT count(*) FROM pg_indexes "
        "WHERE indexname LIKE %s AND schemaname = current_schema()",
        ('%\\_bamboo\\_uuid\\_uniq',),
    )
    indexes = cr.fetchone()[0]

    available = env['bamboo.idempotency']._uuidv7_available()
    _logger.info(
        "bamboo_idempotency installed: %s columns, %s unique indexes, "
        "server-side uuidv7() %s.",
        columns,
        indexes,
        "available" if available else
        "NOT available (PostgreSQL < 18) — clients supply their own keys, "
        "which is the only path that matters for offline create",
    )
