# -*- coding: utf-8 -*-
"""`bamboo_uuid` on every model, and the create that honours it."""

import logging

from odoo import api, models, tools
from odoo.exceptions import UserError
from psycopg2 import errorcodes
from psycopg2.errors import UniqueViolation

from .fields import Uuid

_logger = logging.getLogger(__name__)

#: Whether this PostgreSQL can generate UUIDv7 (18+), resolved once per process.
#: `_auto_init` runs per table — several hundred of them — and the answer cannot
#: change under a running server.
_UUIDV7_AVAILABLE = None


def _uuidv7_available(cr):
    global _UUIDV7_AVAILABLE
    if _UUIDV7_AVAILABLE is None:
        cr.execute("SELECT 1 FROM pg_proc WHERE proname = 'uuidv7' LIMIT 1")
        _UUIDV7_AVAILABLE = bool(cr.fetchone())
        if not _UUIDV7_AVAILABLE:
            _logger.info(
                "bamboo_idempotency: no uuidv7() on this PostgreSQL (needs 18). "
                "Records created outside the app get no key; clients supply "
                "their own, which is the only path offline create depends on."
            )
    return _UUIDV7_AVAILABLE


#: Databases whose field xmlids have been protected in this process.
_XMLIDS_PROTECTED = set()


def _protect_field_xmlids(cr):
    """Mark our per-model field xmlids `noupdate`, or `-u` deletes the columns.

    The field is declared once on the abstract `base` model, but Odoo reflects
    it as one `ir.model.fields` record per model, each with its own xmlid. At
    the end of a load, `ir.model.data._process_end` deletes every non-noupdate
    xmlid belonging to an updated module that was not re-created during that
    run — and `-u bamboo_idempotency` only re-initialises part of the registry,
    so the rest look like records the module dropped. Deleting an
    `ir.model.fields` record drops its column, taking every stored key with it.

    Measured before this: `-u bamboo_idempotency` on a dev database took 408
    columns down to 87, with 418 `Deleting …bamboo_uuid` lines, and no
    subsequent `-u` put them back. That is silent data loss on the most routine
    operation there is.

    `_process_end`'s own query exempts `noupdate` rows, so one UPDATE is the
    whole fix. It covers every owning module, not just this one: models
    introduced by a module installed later have their xmlid attributed to that
    module (fastapi, endpoint_route_handler and auth_oauth each own a few), and
    those rows are just as purgeable.
    """
    if cr.dbname in _XMLIDS_PROTECTED:
        return
    cr.execute(
        r"""
        UPDATE ir_model_data SET noupdate = true
         WHERE model = 'ir.model.fields'
           AND name LIKE 'field\_%\_\_bamboo\_uuid'
           AND COALESCE(noupdate, false) = false
        """
    )
    if cr.rowcount:
        _logger.info(
            "bamboo_idempotency: protected %s bamboo_uuid field xmlids from "
            "the end-of-load purge.", cr.rowcount,
        )
    _XMLIDS_PROTECTED.add(cr.dbname)


class Base(models.AbstractModel):
    """Adds the client-supplied dedup key to every model.

    `_inherit = 'base'` is the blunt instrument on purpose. The client queues
    writes for *any* model a module exposes, and a key that covers only the
    models somebody remembered to list is the deny-list problem again — silent
    about the one nobody thought of, and failing open.

    The column is nullable and has no ORM-level default. Records created any
    other way (the web UI, other addons, an import) simply have no key, which is
    correct: a key means "a client asked for this exact record once".
    """

    _inherit = 'base'

    bamboo_uuid = Uuid(
        string='Bamboo Idempotency Key',
        index=True,
        copy=False,
        readonly=True,
        help="Client-generated UUIDv7 identifying the create request that made "
             "this record. Unique per table, so a retried create cannot file a "
             "second copy.",
    )

    @api.model
    def bamboo_create_idempotent(self, vals, uuid):
        """Create a record for `uuid`, or return the one it already made.

        Returns ``{'id': int, 'created': bool}``. ``created`` is False when the
        uuid was already used — the caller's earlier attempt did reach the
        server, and this call changed nothing.

        The lookup-then-create is deliberately *not* the mechanism; it is the
        fast path. Two devices draining one queue, or one device retrying while
        the first attempt is still in flight, both pass the lookup and race to
        the insert. The UNIQUE index is what settles it: the loser gets a
        UniqueViolation and reads back the winner's id. That is the difference
        between this and a client-side probe, and it is the whole reason a
        client may queue an invoice offline once this addon is installed.
        """
        if not uuid:
            raise UserError("bamboo_create_idempotent requires a uuid.")
        if not self._bamboo_uuid_enforced():
            # Without the index this is a lookup-then-create with a race in the
            # middle — a probe wearing a guarantee's clothes. Transient models
            # land here (they get the column from `base` but no index, and
            # nobody queues a wizard offline anyway). Say so rather than
            # returning something that looks like a promise.
            raise UserError(
                f"{self._name} has no unique bamboo_uuid index, so an "
                "idempotent create cannot be guaranteed on it."
            )

        existing = self.search([('bamboo_uuid', '=', uuid)], limit=1)
        if existing:
            return {'id': existing.id, 'created': False}

        vals = dict(vals or {}, bamboo_uuid=uuid)
        # A savepoint, so losing the race does not roll back the caller's whole
        # transaction — this method is routinely one of several in a drain.
        try:
            with self.env.cr.savepoint():
                record = self.create(vals)
        except UniqueViolation as e:
            if e.pgcode != errorcodes.UNIQUE_VIOLATION:
                raise
            _logger.info(
                "bamboo_create_idempotent: %s uuid=%s lost the insert race; "
                "adopting the record that won.", self._name, uuid,
            )
            winner = self.search([('bamboo_uuid', '=', uuid)], limit=1)
            if not winner:
                # The violation was on some *other* unique constraint of this
                # model, which is a business error and belongs to the caller.
                raise
            return {'id': winner.id, 'created': False}

        return {'id': record.id, 'created': True}

    @api.model
    @tools.ormcache('self._name')
    def _bamboo_uuid_enforced(self):
        """Whether this model's table actually carries the unique index.

        Cached per model: it is decided at install and cannot change while the
        registry is up.
        """
        if not self._auto or self._abstract or self._transient:
            return False
        self.env.cr.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s",
            (f'{self._table}_bamboo_uuid_uniq',),
        )
        return bool(self.env.cr.fetchone())

    @api.model
    def bamboo_find_by_uuid(self, uuid):
        """The id `uuid` created, or False. For a client checking after a
        timeout without wanting to create anything."""
        if not uuid:
            return False
        found = self.search([('bamboo_uuid', '=', uuid)], limit=1)
        return found.id if found else False

    def _auto_init(self):
        """Add the UNIQUE index and the server-side default.

        Both are done here rather than declaratively, for reasons that only show
        up on a database with real data in it:

        * The index is **partial** (`WHERE bamboo_uuid IS NOT NULL`). Every row
          that predates this addon has a null key, and there can be millions of
          them; excluding them keeps the index proportional to the records
          clients actually created.
        * The `uuidv7()` default is set with `ALTER COLUMN`, never as part of
          `ADD COLUMN`. Postgres only takes the O(1) path for a *non-volatile*
          default; attaching a volatile one while adding the column rewrites
          the entire table under an ACCESS EXCLUSIVE lock. On `mail.message` or
          `ir.attachment` that is an outage, not a migration.
        """
        res = super()._auto_init()
        # Once per database per process, and before `_process_end` runs at the
        # end of this load — which is the only window in which it helps.
        _protect_field_xmlids(self.env.cr)
        if not self._auto or self._abstract or self._transient:
            return res
        if 'bamboo_uuid' not in self._fields:
            return res

        cr = self.env.cr
        index_name = f'{self._table}_bamboo_uuid_uniq'
        cr.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", (index_name,),
        )
        if not cr.fetchone():
            cr.execute(
                f'CREATE UNIQUE INDEX "{index_name}" ON "{self._table}" '
                '(bamboo_uuid) WHERE bamboo_uuid IS NOT NULL'
            )

        cr.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'bamboo_uuid'",
            (self._table,),
        )
        row = cr.fetchone()
        if row and not row[0] and _uuidv7_available(cr):
            cr.execute(
                f'ALTER TABLE "{self._table}" '
                'ALTER COLUMN bamboo_uuid SET DEFAULT uuidv7()'
            )
        return res
